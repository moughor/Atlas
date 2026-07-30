from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re

from moughorai.dependency_intelligence import DependencyIntelligenceService
from moughorai.project_inventory import (
    FileKind,
    ProjectClassifier,
    ProjectStatisticsCollector,
    ProjectTechnologyDetector,
    ScannedFile,
)
from moughorai.project_inventory.detection_models import TechnologyCategory
from moughorai.project_inventory.framework_service import MavenFrameworkService
from moughorai.project_inventory.maven_parser import MavenParseError
from moughorai.workspace import Project, WorkspaceService
from moughorai.workspace.files import project_files

from .models import ProjectSummary, RepositorySummary


class RepositorySummaryService:
    """Compose existing Atlas inventory services into one repository model."""

    _TEST_PARTS = frozenset({"test", "tests", "testing", "__tests__", "spec", "specs"})
    _FRAMEWORK_DEPENDENCIES = {
        "flask": "Flask", "fastapi": "FastAPI", "django": "Django",
        "sqlalchemy": "SQLAlchemy", "celery": "Celery", "react": "React",
        "@nestjs/core": "NestJS", "@angular/core": "Angular",
    }

    def __init__(
        self,
        service: WorkspaceService,
        *,
        classifier: ProjectClassifier | None = None,
        statistics: ProjectStatisticsCollector | None = None,
        detector: ProjectTechnologyDetector | None = None,
        dependencies: DependencyIntelligenceService | None = None,
        maven_frameworks: MavenFrameworkService | None = None,
    ) -> None:
        self.service = service
        self.classifier = classifier or ProjectClassifier()
        self.statistics = statistics or ProjectStatisticsCollector()
        self.detector = detector or ProjectTechnologyDetector()
        self.dependencies = dependencies or DependencyIntelligenceService()
        self.maven_frameworks = maven_frameworks or MavenFrameworkService()

    def build(self) -> RepositorySummary:
        projects: list[ProjectSummary] = []
        language_counts: Counter[str] = Counter()
        dependency_counts: Counter[str] = Counter()
        dependency_manifests: set[tuple[str, Path]] = set()
        build_systems: set[str] = set()
        frameworks: set[str] = set()
        entry_points: set[str] = set()
        framework_evidence: set[tuple[str, str, str, str]] = set()
        production = test = generated = 0
        for project in sorted(self.service.workspace.projects, key=lambda item: item.name):
            summary, project_dependencies = self._project(project)
            projects.append(summary)
            language_counts.update(dict(summary.languages))
            dependency_counts.update(item.ecosystem for item in project_dependencies)
            dependency_manifests.update(
                (item.ecosystem, item.source.resolve())
                for item in project_dependencies
            )
            build_systems.update(summary.build_systems)
            frameworks.update(summary.frameworks)
            framework_evidence.update(
                (framework, project.name, scope, reference)
                for framework, scope, reference in summary.framework_evidence
            )
            entry_points.update(f"{project.name}:{path}" for path in summary.entry_points)
            production += summary.production_files
            test += summary.test_files
            generated += summary.generated_files
        return RepositorySummary(
            self.service.workspace.root,
            tuple(projects),
            tuple(sorted(language_counts.items())),
            tuple(sorted(build_systems)),
            tuple(sorted(frameworks)),
            tuple(sorted(entry_points)),
            self._hierarchy(),
            production,
            test,
            generated,
            tuple(sorted(dependency_counts.items())),
            tuple(sorted(Counter(
                ecosystem for ecosystem, _ in dependency_manifests
            ).items())),
            tuple(sorted(framework_evidence)),
        )

    def _project(self, project: Project):
        paths = self._paths(project)
        scanned = tuple(
            ScannedFile(
                path,
                path.relative_to(project.path.resolve()),
                self._size(path),
                path.suffix.casefold(),
            )
            for path in paths
        )
        classified = self.classifier.classify_many(scanned)
        directories = {item.relative_path.parent for item in classified}
        inventory = self.statistics.collect(
            root=project.path.resolve(),
            files=classified,
            total_directories=len(directories),
        )
        detection = self.detector.detect(inventory)
        builds = tuple(sorted(
            item.name for item in detection.technologies
            if item.category is TechnologyCategory.BUILD
        ))
        dependencies = self.dependencies.analyze(project.path, paths)
        frameworks, framework_evidence = self._frameworks(project, paths, dependencies)
        entries = self._entry_points(project, classified)
        generated = sum(item.kind is FileKind.GENERATED for item in classified)
        tests = sum(
            item.kind is FileKind.SOURCE and self._is_test(item.relative_path)
            for item in classified
        )
        production = sum(
            item.kind is FileKind.SOURCE
            and not self._is_test(item.relative_path)
            for item in classified
        )
        try:
            project_path = project.path.resolve().relative_to(self.service.workspace.root).as_posix()
        except ValueError:
            project_path = project.path.resolve().as_posix()
        summary = ProjectSummary(
            project.name,
            project_path or ".",
            inventory.total_files,
            inventory.total_size,
            tuple(sorted((item.name, item.files) for item in inventory.languages)),
            builds,
            frameworks,
            entries,
            production,
            tests,
            generated,
            len(dependencies),
            framework_evidence,
        )
        return summary, dependencies

    def _paths(self, project: Project) -> tuple[Path, ...]:
        nested_roots = tuple(
            candidate.path.resolve()
            for candidate in self.service.workspace.projects
            if candidate is not project
            and self._contains(project.path.resolve(), candidate.path.resolve())
        )
        return tuple(
            path
            for path in project_files(project.path, project.include, project.exclude)
            if not any(self._contains(root, path.resolve()) for root in nested_roots)
        )

    def _frameworks(self, project, paths, dependencies):
        values: set[str] = set()
        evidence: set[tuple[str, str, str]] = set()
        scope = self._framework_scope(project)
        for dependency in dependencies:
            normalized = dependency.name.casefold()
            for token, framework in self._FRAMEWORK_DEPENDENCIES.items():
                if normalized == token or token in normalized:
                    values.add(framework)
                    evidence.add((framework, scope, dependency.name))
            for token, framework in (
                ("spring", "Spring"), ("quarkus", "Quarkus"), ("micronaut", "Micronaut"),
            ):
                if token in normalized:
                    values.add(framework)
                    evidence.add((framework, scope, dependency.name))
        for pom in (path for path in paths if path.name == "pom.xml"):
            try:
                for item in self.maven_frameworks.analyze(pom).technologies:
                    values.add(item.name)
                    for detail in item.evidence:
                        evidence.add((item.name, scope, detail.coordinate))
            except (MavenParseError, OSError, ValueError):
                continue
        return tuple(sorted(values)), tuple(sorted(evidence))

    def _framework_scope(self, project: Project) -> str:
        try:
            relative = project.path.resolve().relative_to(
                self.service.workspace.root.resolve()
            )
        except ValueError:
            relative = Path(project.name)
        terms = {
            part.casefold()
            for part in (*relative.parts, project.name)
        }
        markers = ("test", "tests", "sample", "samples", "example", "examples", "documentation", "tooling")
        if any(marker in term for marker in markers for term in terms):
            return "test-or-sample"
        return "project-local"

    def _entry_points(self, project: Project, files) -> tuple[str, ...]:
        entries: set[str] = set()
        for item in files:
            relative = item.relative_path.as_posix()
            if item.path.name in ("__main__.py", "manage.py"):
                entries.add(relative)
                continue
            if item.path.name == "package.json":
                entries.update(self._package_entries(item.path))
                continue
            if item.extension not in (".java", ".py", ".js", ".ts", ".tsx"):
                continue
            try:
                source = item.path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                continue
            if (
                item.extension == ".java" and re.search(r"\bstatic\s+void\s+main\s*\(", source)
                or item.extension == ".py" and '__name__' in source and '"__main__"' in source
            ):
                entries.add(relative)
        return tuple(sorted(entries))

    @staticmethod
    def _package_entries(path: Path) -> set[str]:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return set()
        return {
            str(item)
            for key in ("main", "module", "bin")
            if (item := value.get(key)) is not None and isinstance(item, str)
        }

    def _hierarchy(self) -> tuple[tuple[str, str | None], ...]:
        projects = self.service.workspace.projects
        result = []
        for project in projects:
            parents = [
                candidate
                for candidate in projects
                if candidate is not project
                and self._contains(candidate.path.resolve(), project.path.resolve())
            ]
            parent = max(parents, key=lambda item: len(item.path.resolve().parts), default=None)
            result.append((project.name, None if parent is None else parent.name))
        return tuple(sorted(result))

    @staticmethod
    def _contains(parent: Path, child: Path) -> bool:
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False

    @classmethod
    def _is_test(cls, path: Path) -> bool:
        return bool({part.casefold() for part in path.parts} & cls._TEST_PARTS)

    @staticmethod
    def _size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0
