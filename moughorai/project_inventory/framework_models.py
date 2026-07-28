"""Immutable models for deterministic framework detection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class FrameworkCategory(str, Enum):
    """High-level categories for detected project technologies."""

    FRAMEWORK = "framework"
    PERSISTENCE = "persistence"
    DATABASE = "database"
    LOGGING = "logging"
    TESTING = "testing"
    MIGRATION = "migration"
    SECURITY = "security"
    MESSAGING = "messaging"
    API = "api"


@dataclass(frozen=True)
class FrameworkEvidence:
    """One piece of evidence supporting a framework detection."""

    coordinate: str
    source: Path
    version: str | None = None
    scope: str | None = None
    kind: str = "dependency"


@dataclass(frozen=True)
class DetectedFramework:
    """A framework or related technology detected from build metadata."""

    name: str
    category: FrameworkCategory
    confidence: float
    evidence: tuple[FrameworkEvidence, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")

    @property
    def coordinates(self) -> tuple[str, ...]:
        """Return the unique supporting Maven coordinates."""

        return tuple(
            sorted(
                {item.coordinate for item in self.evidence},
                key=str.casefold,
            )
        )


@dataclass(frozen=True)
class FrameworkReport:
    """Collection of technologies detected for one Maven project."""

    source: Path
    technologies: tuple[DetectedFramework, ...]

    def has(self, name: str) -> bool:
        """Return whether a technology was detected by name."""

        normalized = name.casefold()
        return any(
            technology.name.casefold() == normalized
            for technology in self.technologies
        )

    def get(self, name: str) -> DetectedFramework | None:
        """Return one detected technology by case-insensitive name."""

        normalized = name.casefold()

        for technology in self.technologies:
            if technology.name.casefold() == normalized:
                return technology

        return None

    def by_category(
        self,
        category: FrameworkCategory,
    ) -> tuple[DetectedFramework, ...]:
        """Return all technologies in one category."""

        return tuple(
            technology
            for technology in self.technologies
            if technology.category is category
        )
