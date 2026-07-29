"""Java import and cross-file type resolution."""

from moughorai.java_resolution.models import (
    ResolvedTypeReference,
    ResolutionStatus,
    TypeResolution,
)
from moughorai.java_resolution.resolver import JavaTypeResolver
from moughorai.java_resolution.service import JavaTypeResolutionService

__all__ = [
    "JavaTypeResolver",
    "JavaTypeResolutionService",
    "ResolvedTypeReference",
    "ResolutionStatus",
    "TypeResolution",
]
