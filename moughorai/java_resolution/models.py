"""Immutable models for deterministic Java type resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    PRIMITIVE = "primitive"


@dataclass(frozen=True)
class TypeResolution:
    requested_name: str
    normalized_name: str
    status: ResolutionStatus
    qualified_name: str | None = None
    candidates: tuple[str, ...] = ()

    @property
    def is_resolved(self) -> bool:
        return self.status in {
            ResolutionStatus.RESOLVED,
            ResolutionStatus.PRIMITIVE,
        }


@dataclass(frozen=True)
class ResolvedTypeReference:
    owner: str
    role: str
    name: str
    resolution: TypeResolution
