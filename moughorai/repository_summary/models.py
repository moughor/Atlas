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
    file_size_error_count: int = 0

    def __post_init__(self) -> None:
        if self.file_size_error_count < 0:
            raise ValueError("file size error count must be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            # Keep the original keys below for snapshot and API compatibility.
            # The explicit aliases define both the population and the unit.
            "files": self.files,
            "size": self.size,
            "languages": dict(self.languages),
            "inventoried_file_count": self.files,
            "inventoried_file_bytes": self.size,
            "inventoried_file_size_error_count": self.file_size_error_count,
            "language_file_counts": dict(self.languages),
            "build_systems": list(self.build_systems),
            "frameworks": list(self.frameworks),
            "entry_points": list(self.entry_points),
            "production_files": self.production_files,
            "test_files": self.test_files,
            "generated_files": self.generated_files,
            "dependencies": self.dependencies,
            "classified_non_test_source_files": self.production_files,
            "classified_test_source_files": self.test_files,
            "classified_generated_files": self.generated_files,
            "declared_dependency_records": self.dependencies,
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
        inventoried_files = sum(project.files for project in self.projects)
        inventoried_bytes = sum(project.size for project in self.projects)
        size_errors = sum(project.file_size_error_count for project in self.projects)
        declared_dependencies = sum(value for _, value in self.dependencies_by_ecosystem)
        return {
            "schema_version": self.schema_version,
            "root": self.root.as_posix(),
            "projects": [project.to_dict() for project in self.projects],
            "project_count": len(self.projects),
            "languages": dict(self.languages),
            "language_file_counts": dict(self.languages),
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
            "inventoried_file_count": inventoried_files,
            "inventoried_file_bytes": inventoried_bytes,
            "inventoried_file_size_error_count": size_errors,
            "classified_non_test_source_files": self.production_files,
            "classified_test_source_files": self.test_files,
            "classified_generated_files": self.generated_files,
            "dependencies_by_ecosystem": dict(self.dependencies_by_ecosystem),
            "declared_dependency_count_by_ecosystem": dict(self.dependencies_by_ecosystem),
            "total_declared_dependencies": declared_dependencies,
            "total_declared_dependency_records": declared_dependencies,
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
