"""Immutable models for project technology detection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class TechnologyCategory(str, Enum):
    """High-level categories for detected technologies."""

    BUILD = "build"
    LANGUAGE = "language"
    PLATFORM = "platform"
    CONTAINER = "container"
    VERSION_CONTROL = "version_control"
    PACKAGING = "packaging"


@dataclass(frozen=True)
class DetectedTechnology:
    """One technology detected from deterministic project evidence."""

    name: str
    category: TechnologyCategory
    confidence: float
    evidence: tuple[Path, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")


@dataclass(frozen=True)
class ProjectDetection:
    """Collection of technologies detected in one project."""

    technologies: tuple[DetectedTechnology, ...]

    def has(self, name: str) -> bool:
        """Return whether a technology was detected by name."""

        normalized = name.casefold()
        return any(
            technology.name.casefold() == normalized
            for technology in self.technologies
        )

    def by_category(
        self,
        category: TechnologyCategory,
    ) -> tuple[DetectedTechnology, ...]:
        """Return all technologies matching a category."""

        return tuple(
            technology
            for technology in self.technologies
            if technology.category is category
        )
