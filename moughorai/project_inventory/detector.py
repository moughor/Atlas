"""Deterministic technology detection for project inventories."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from moughorai.project_inventory.detection_models import (
    DetectedTechnology,
    ProjectDetection,
    TechnologyCategory,
)
from moughorai.project_inventory.models import ProjectInventory


class ProjectTechnologyDetector:
    """Detect project technologies from inventory paths and file metadata."""

    def detect(self, inventory: ProjectInventory) -> ProjectDetection:
        """Return all technologies detected in an inventory."""

        evidence: dict[
            tuple[str, TechnologyCategory, float],
            set[Path],
        ] = defaultdict(set)

        relative_paths = {
            file.relative_path.as_posix().casefold(): file.relative_path
            for file in inventory.files
        }
        filenames: dict[str, list[Path]] = defaultdict(list)

        for file in inventory.files:
            filenames[file.relative_path.name.casefold()].append(
                file.relative_path
            )

        self._detect_build_systems(filenames, evidence)
        self._detect_platforms(filenames, evidence)
        self._detect_infrastructure(relative_paths, filenames, evidence)
        self._detect_packaging(inventory, evidence)
        self._detect_languages(inventory, evidence)

        technologies = tuple(
            sorted(
                (
                    DetectedTechnology(
                        name=name,
                        category=category,
                        confidence=confidence,
                        evidence=tuple(
                            sorted(
                                paths,
                                key=lambda path: path.as_posix().casefold(),
                            )
                        ),
                    )
                    for (name, category, confidence), paths in evidence.items()
                ),
                key=lambda technology: (
                    technology.category.value,
                    technology.name.casefold(),
                ),
            )
        )

        return ProjectDetection(technologies=technologies)

    @staticmethod
    def _add(
        evidence: dict[
            tuple[str, TechnologyCategory, float],
            set[Path],
        ],
        *,
        name: str,
        category: TechnologyCategory,
        confidence: float,
        paths: list[Path] | tuple[Path, ...],
    ) -> None:
        if not paths:
            return

        evidence[(name, category, confidence)].update(paths)

    def _detect_build_systems(
        self,
        filenames: dict[str, list[Path]],
        evidence: dict[
            tuple[str, TechnologyCategory, float],
            set[Path],
        ],
    ) -> None:
        self._add(
            evidence,
            name="Maven",
            category=TechnologyCategory.BUILD,
            confidence=1.0,
            paths=filenames.get("pom.xml", []),
        )

        gradle_paths = (
            filenames.get("build.gradle", [])
            + filenames.get("build.gradle.kts", [])
            + filenames.get("settings.gradle", [])
            + filenames.get("settings.gradle.kts", [])
        )
        self._add(
            evidence,
            name="Gradle",
            category=TechnologyCategory.BUILD,
            confidence=1.0,
            paths=gradle_paths,
        )

        self._add(
            evidence,
            name="npm",
            category=TechnologyCategory.BUILD,
            confidence=1.0,
            paths=filenames.get("package.json", []),
        )

        python_paths = (
            filenames.get("pyproject.toml", [])
            + filenames.get("requirements.txt", [])
            + filenames.get("setup.py", [])
        )
        self._add(
            evidence,
            name="Python Packaging",
            category=TechnologyCategory.BUILD,
            confidence=0.95,
            paths=python_paths,
        )

    def _detect_platforms(
        self,
        filenames: dict[str, list[Path]],
        evidence: dict[
            tuple[str, TechnologyCategory, float],
            set[Path],
        ],
    ) -> None:
        self._add(
            evidence,
            name="Node.js",
            category=TechnologyCategory.PLATFORM,
            confidence=0.95,
            paths=filenames.get("package.json", []),
        )

        python_paths = (
            filenames.get("pyproject.toml", [])
            + filenames.get("requirements.txt", [])
            + filenames.get("setup.py", [])
        )
        self._add(
            evidence,
            name="Python",
            category=TechnologyCategory.PLATFORM,
            confidence=0.95,
            paths=python_paths,
        )

    def _detect_infrastructure(
        self,
        relative_paths: dict[str, Path],
        filenames: dict[str, list[Path]],
        evidence: dict[
            tuple[str, TechnologyCategory, float],
            set[Path],
        ],
    ) -> None:
        docker_paths = filenames.get("dockerfile", [])
        docker_paths += [
            path
            for normalized, path in relative_paths.items()
            if normalized.endswith("/dockerfile")
        ]
        self._add(
            evidence,
            name="Docker",
            category=TechnologyCategory.CONTAINER,
            confidence=1.0,
            paths=docker_paths,
        )

        git_paths = [
            path
            for normalized, path in relative_paths.items()
            if normalized == ".gitignore"
            or normalized == ".gitattributes"
            or normalized.startswith(".github/")
        ]
        self._add(
            evidence,
            name="Git",
            category=TechnologyCategory.VERSION_CONTROL,
            confidence=0.9,
            paths=git_paths,
        )

    def _detect_packaging(
        self,
        inventory: ProjectInventory,
        evidence: dict[
            tuple[str, TechnologyCategory, float],
            set[Path],
        ],
    ) -> None:
        packaging = {
            ".ear": "EAR",
            ".war": "WAR",
            ".jar": "JAR",
        }

        for extension, name in packaging.items():
            paths = [
                file.relative_path
                for file in inventory.files
                if file.extension == extension
            ]
            self._add(
                evidence,
                name=name,
                category=TechnologyCategory.PACKAGING,
                confidence=1.0,
                paths=paths,
            )

    def _detect_languages(
        self,
        inventory: ProjectInventory,
        evidence: dict[
            tuple[str, TechnologyCategory, float],
            set[Path],
        ],
    ) -> None:
        languages: dict[str, list[Path]] = defaultdict(list)

        for file in inventory.files:
            if file.language is not None:
                languages[file.language].append(file.relative_path)

        for language, paths in languages.items():
            self._add(
                evidence,
                name=language,
                category=TechnologyCategory.LANGUAGE,
                confidence=1.0,
                paths=paths,
            )
