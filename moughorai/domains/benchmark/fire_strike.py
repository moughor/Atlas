"""Immutable canonical model for one Fire Strike Standard submission."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .canonical import canonical_json, canonical_json_bytes, canonical_sha256
from .evidence import FieldEvidenceV1


FIRE_STRIKE_SUBMISSION_SCHEMA_VERSION = 1
FIRE_STRIKE_STANDARD_BENCHMARK_ID = "benchmark:ul:3dmark:fire-strike-standard"
_SOURCE_ID = re.compile(r"^source:[a-z0-9][a-z0-9-]*$")
_NATIVE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def source_submission_identity(source_identifier: str, native_identifier: str) -> str:
    """Build the stable identity of one source-owned submission record."""

    if not isinstance(source_identifier, str) or _SOURCE_ID.fullmatch(source_identifier) is None:
        raise ValueError("source identifier must use the source:<slug> form")
    if not isinstance(native_identifier, str) or _NATIVE_ID.fullmatch(native_identifier) is None:
        raise ValueError("native submission identifier must be portable lowercase text")
    return f"submission:{source_identifier}:{native_identifier}"


@dataclass(frozen=True, slots=True)
class FireStrikeSubmissionV1:
    source_identifier: str
    native_submission_identifier: str
    overall_score: FieldEvidenceV1
    graphics_score: FieldEvidenceV1
    physics_score: FieldEvidenceV1
    combined_score: FieldEvidenceV1

    def __post_init__(self) -> None:
        source_submission_identity(
            self.source_identifier,
            self.native_submission_identifier,
        )
        for label, field in self._fields():
            if not isinstance(field, FieldEvidenceV1):
                raise TypeError(f"{label} must be FieldEvidenceV1")
            if (
                field.source_identifier != self.source_identifier
                or field.native_submission_identifier != self.native_submission_identifier
            ):
                raise ValueError(f"{label} provenance does not belong to this submission")
            if field.unit != "marks":
                raise ValueError(f"{label} must use the marks unit")

    @property
    def schema_version(self) -> int:
        return FIRE_STRIKE_SUBMISSION_SCHEMA_VERSION

    @property
    def benchmark_id(self) -> str:
        return FIRE_STRIKE_STANDARD_BENCHMARK_ID

    @property
    def submission_id(self) -> str:
        return source_submission_identity(
            self.source_identifier,
            self.native_submission_identifier,
        )

    @property
    def canonical_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def _fields(self) -> tuple[tuple[str, FieldEvidenceV1], ...]:
        return (
            ("overall score", self.overall_score),
            ("graphics score", self.graphics_score),
            ("physics score", self.physics_score),
            ("combined score", self.combined_score),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "benchmark_id": self.benchmark_id,
            "combined_score": self.combined_score.to_dict(),
            "graphics_score": self.graphics_score.to_dict(),
            "native_submission_identifier": self.native_submission_identifier,
            "overall_score": self.overall_score.to_dict(),
            "physics_score": self.physics_score.to_dict(),
            "schema_version": self.schema_version,
            "source_identifier": self.source_identifier,
            "submission_id": self.submission_id,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())
