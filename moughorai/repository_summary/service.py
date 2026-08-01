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
    TEST_TREE_DIRECTORY_NAMES,
    is_test_source_path,
)
from moughorai.project_inventory.detection_models import TechnologyCategory
from moughorai.project_inventory.framework_service import MavenFrameworkService
from moughorai.project_inventory.framework_rules import FRAMEWORK_RULES
from moughorai.project_inventory.maven_parser import MavenParseError
from moughorai.workspace import Project, WorkspaceService
from moughorai.workspace.files import project_files

from .models import ProjectSummary, RepositorySummary


class RepositorySummaryService:
    """Compose existing Atlas inventory services into one repository model."""

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
        scanned_items = []
        size_error_count = 0
        for path in paths:
            size, errors = self._size(path)
            size_error_count += errors
            scanned_items.append(ScannedFile(
                path,
                path.relative_to(project.path.resolve()),
                size,
                path.suffix.casefold(),
            ))
        scanned = tuple(scanned_items)
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
        test_project = self._is_test_project_area(project)
        tests = sum(
            item.kind is FileKind.SOURCE
            and (test_project or self._is_test(item.relative_path))
            for item in classified
        )
        production = sum(
            item.kind is FileKind.SOURCE
            and not test_project
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
            size_error_count,
        )
        return summary, dependencies

    def _paths(self, project: Project) -> tuple[Path, ...]:
        project_root = project.path.resolve()
        nested_roots: list[Path] = []
        for candidate in self.service.workspace.projects:
            if candidate is project:
                continue
            candidate_root = candidate.path.resolve()
            if self._contains(project_root, candidate_root):
                nested_roots.append(candidate_root)
        paths: list[Path] = []
        for path in project_files(project.path, project.include, project.exclude):
            resolved_path = path.resolve()
            if not any(self._contains(root, resolved_path) for root in nested_roots):
                paths.append(path)
        return tuple(paths)

    def _frameworks(self, project, paths, dependencies):
        values: set[str] = set()
        evidence: set[tuple[str, str, str]] = set()
        project_scope = self._framework_scope(project)
        project_root = project.path.resolve()
        for dependency in dependencies:
            # Maven has a coordinate-aware detector below. Re-running broad token
            # matching over Maven coordinates produced false positives such as
            # "react" in "reactive" and Spring adoption from integration artifact
            # names. Other ecosystems use exact package identities only.
            if dependency.ecosystem == "maven":
                continue
            normalized = dependency.name.casefold()
            evidence_scope = self._dependency_scope(
                self._manifest_scope(
                    project_scope,
                    project_root,
                    dependency.source,
                ),
                dependency.scope,
                dependency.optional,
            )
            if dependency.ecosystem == "gradle" and ":" in dependency.name:
                group_id, artifact_id = dependency.name.split(":", 1)
                for rule in FRAMEWORK_RULES:
                    if rule.matches(group_id, artifact_id):
                        values.add(rule.name)
                        evidence.add((rule.name, evidence_scope, dependency.name))
                continue
            for token, framework in self._FRAMEWORK_DEPENDENCIES.items():
                if normalized == token:
                    values.add(framework)
                    evidence.add((
                        framework,
                        evidence_scope,
                        dependency.name,
                    ))
        for pom in sorted(
            (path for path in paths if path.name == "pom.xml"),
            key=Path.as_posix,
        ):
            try:
                for item in self.maven_frameworks.analyze(pom).technologies:
                    values.add(item.name)
                    for detail in item.evidence:
                        evidence.add((
                            item.name,
                            self._maven_evidence_scope(
                                self._manifest_scope(
                                    project_scope,
                                    project_root,
                                    detail.source,
                                ),
                                detail,
                            ),
                            detail.coordinate,
                        ))
            except (MavenParseError, OSError, ValueError):
                pass
        return tuple(sorted(values)), tuple(sorted(evidence))

    @staticmethod
    def _dependency_scope(
        project_scope: str,
        dependency_scope: str,
        optional: bool,
    ) -> str:
        if project_scope in {"test-or-sample", "documentation", "build-tooling"}:
            return project_scope
        if optional or dependency_scope.casefold() == "optional":
            return "optional"
        if dependency_scope.casefold() in {
            "test", "testimplementation", "development", "dev",
        }:
            return "test-only"
        return "project-local"

    @classmethod
    def _maven_evidence_scope(cls, project_scope: str, detail) -> str:
        if project_scope in {"test-or-sample", "documentation", "build-tooling"}:
            return project_scope
        if detail.kind == "plugin":
            return "build-tooling"
        return cls._dependency_scope(
            project_scope,
            detail.scope or "compile",
            False,
        )

    @classmethod
    def _manifest_scope(
        cls,
        project_scope: str,
        project_root: Path,
        manifest: Path,
    ) -> str:
        if project_scope in {"test-or-sample", "documentation", "build-tooling"}:
            return project_scope
        try:
            relative = manifest.resolve().relative_to(project_root)
        except ValueError:
            return project_scope
        terms = {
            token
            for part in relative.parts[:-1]
            for token in re.split(r"[^a-z0-9]+", part.casefold())
            if token
        }
        return cls._scope_from_terms(terms, default=project_scope)

    def _framework_scope(self, project: Project) -> str:
        try:
            relative = project.path.resolve().relative_to(
                self.service.workspace.root.resolve()
            )
        except ValueError:
            relative = Path(project.name)
        terms = {
            token
            for part in (*relative.parts, project.name)
            for token in re.split(r"[^a-z0-9]+", part.casefold())
            if token
        }
        return self._scope_from_terms(terms, default="project-local")

    def _is_test_project_area(self, project: Project) -> bool:
        """Use workspace structure, never the project name alone, for test scope."""

        try:
            relative = project.path.resolve().relative_to(
                self.service.workspace.root.resolve()
            )
        except ValueError:
            return False
        terms = {
            token
            for part in relative.parts
            for token in re.split(r"[^a-z0-9]+", part.casefold())
            if token
        }
        return bool(terms & TEST_TREE_DIRECTORY_NAMES)

    @staticmethod
    def _scope_from_terms(terms: set[str], *, default: str) -> str:
        if terms & {"documentation", "docs"}:
            return "documentation"
        if (
            terms & {"tooling", "buildtools"}
            or {"build", "logic"} <= terms
            or {"build", "tools"} <= terms
        ):
            return "build-tooling"
        if terms & TEST_TREE_DIRECTORY_NAMES:
            return "test-or-sample"
        return default

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
        resolved = tuple((project, project.path.resolve()) for project in projects)
        result = []
        for project, project_path in resolved:
            parents = [
                (candidate, candidate_path)
                for candidate, candidate_path in resolved
                if candidate is not project
                and self._contains(candidate_path, project_path)
            ]
            parent = max(parents, key=lambda item: len(item[1].parts), default=None)
            result.append((project.name, None if parent is None else parent[0].name))
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
        return is_test_source_path(path)

    @staticmethod
    def _size(path: Path) -> tuple[int, int]:
        try:
            return path.stat().st_size, 0
        except OSError:
            return 0, 1
