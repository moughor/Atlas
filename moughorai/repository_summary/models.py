from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    name: str
    path: str
    files: int
    size: int
    languages: tuple[tuple[str, int], ...]
    build_systems: tuple[str, ...]
    frameworks: tuple[str, ...]
    entry_points: tuple[str, ...]
    production_files: int
    test_files: int
    generated_files: int
    dependencies: int
    framework_evidence: tuple[tuple[str, str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "files": self.files,
            "size": self.size,
            "languages": dict(self.languages),
            "build_systems": list(self.build_systems),
            "frameworks": list(self.frameworks),
            "entry_points": list(self.entry_points),
            "production_files": self.production_files,
            "test_files": self.test_files,
            "generated_files": self.generated_files,
            "dependencies": self.dependencies,
            "framework_evidence": [
                {"framework": framework, "scope": scope, "reference": reference}
                for framework, scope, reference in self.framework_evidence
            ],
        }


@dataclass(frozen=True, slots=True)
class RepositorySummary:
    root: Path
    projects: tuple[ProjectSummary, ...]
    languages: tuple[tuple[str, int], ...]
    build_systems: tuple[str, ...]
    frameworks: tuple[str, ...]
    entry_points: tuple[str, ...]
    module_hierarchy: tuple[tuple[str, str | None], ...]
    production_files: int
    test_files: int
    generated_files: int
    dependencies_by_ecosystem: tuple[tuple[str, int], ...]
    dependency_manifests_by_ecosystem: tuple[tuple[str, int], ...] = ()
    framework_evidence: tuple[tuple[str, str, str, str], ...] = ()
    schema_version: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "root": self.root.as_posix(),
            "projects": [project.to_dict() for project in self.projects],
            "languages": dict(self.languages),
            "build_systems": list(self.build_systems),
            "frameworks": list(self.frameworks),
            "entry_points": list(self.entry_points),
            "module_hierarchy": [
                {"project": project, "parent": parent}
                for project, parent in self.module_hierarchy
            ],
            "production_files": self.production_files,
            "test_files": self.test_files,
            "generated_files": self.generated_files,
            "dependencies_by_ecosystem": dict(self.dependencies_by_ecosystem),
            "declared_dependency_count_by_ecosystem": dict(self.dependencies_by_ecosystem),
            "total_declared_dependencies": sum(value for _, value in self.dependencies_by_ecosystem),
            "dependency_manifest_count_by_ecosystem": dict(
                self.dependency_manifests_by_ecosystem
            ),
            "total_dependency_manifests": sum(
                value for _, value in self.dependency_manifests_by_ecosystem
            ),
            "framework_evidence": [
                {
                    "framework": framework,
                    "project": project,
                    "scope": scope,
                    "reference": reference,
                }
                for framework, project, scope, reference in self.framework_evidence
            ],
        }
