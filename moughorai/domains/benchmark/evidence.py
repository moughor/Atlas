"""Field-level provenance for the first Fire Strike submission model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

from .canonical import normalize_decimal, normalize_text


_SOURCE_ID = re.compile(r"^source:[a-z0-9][a-z0-9-]*$")
_NATIVE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class FieldState(StrEnum):
    OBSERVED = "observed"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    CONFLICTING = "conflicting"
    NOT_APPLICABLE = "not_applicable"


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = normalize_text(value)
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class FieldEvidenceV1:
    """One score field and the direct capture provenance supporting its state."""

    state: FieldState
    source_identifier: str
    native_submission_identifier: str
    capture_sha256: str
    field_locator: str
    raw_value: str | None
    normalized_value: str | None
    unit: str
    alternatives: tuple["FieldEvidenceV1", ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.state, FieldState):
            raise TypeError("field state must be a FieldState")

        source = _text(self.source_identifier, "source identifier")
        native = _text(self.native_submission_identifier, "native submission identifier")
        capture = _text(self.capture_sha256, "capture SHA-256")
        locator = _text(self.field_locator, "field locator")
        unit = _text(self.unit, "field unit")
        if _SOURCE_ID.fullmatch(source) is None:
            raise ValueError("source identifier must use the source:<slug> form")
        if _NATIVE_ID.fullmatch(native) is None:
            raise ValueError("native submission identifier must be portable lowercase text")
        if _SHA256.fullmatch(capture) is None:
            raise ValueError("capture SHA-256 must contain 64 lowercase hexadecimal characters")
        if not locator.startswith("/"):
            raise ValueError("field locator must be an absolute JSON Pointer")

        object.__setattr__(self, "source_identifier", source)
        object.__setattr__(self, "native_submission_identifier", native)
        object.__setattr__(self, "capture_sha256", capture)
        object.__setattr__(self, "field_locator", locator)
        object.__setattr__(self, "unit", unit)

        if not isinstance(self.alternatives, tuple):
            raise TypeError("field alternatives must be a tuple")
        if self.state is FieldState.OBSERVED:
            if self.raw_value is None or self.normalized_value is None:
                raise ValueError("an observed field requires raw and normalized values")
            raw = _text(self.raw_value, "raw field value")
            normalized = normalize_decimal(self.normalized_value)
            object.__setattr__(self, "raw_value", raw)
            object.__setattr__(self, "normalized_value", normalized)
            if self.alternatives:
                raise ValueError("an observed field cannot contain alternatives")
            return

        if self.raw_value is not None or self.normalized_value is not None:
            raise ValueError("a non-observed field cannot contain a direct value")
        if self.state is not FieldState.CONFLICTING:
            if self.alternatives:
                raise ValueError("only a conflicting field may contain alternatives")
            return

        if len(self.alternatives) < 2:
            raise ValueError("a conflicting field requires at least two alternatives")
        for alternative in self.alternatives:
            if not isinstance(alternative, FieldEvidenceV1):
                raise TypeError("conflicting alternatives must be FieldEvidenceV1 values")
            if alternative.state is not FieldState.OBSERVED:
                raise ValueError("conflicting alternatives must be observed values")
            if (
                alternative.source_identifier != source
                or alternative.native_submission_identifier != native
                or alternative.capture_sha256 != capture
                or alternative.unit != unit
            ):
                raise ValueError("conflicting alternatives must retain the same field provenance")
        values = {alternative.normalized_value for alternative in self.alternatives}
        if len(values) != len(self.alternatives):
            raise ValueError(
                "conflicting alternatives must have distinct normalized values; "
                "duplicate normalized values are not allowed"
            )
        ordered = tuple(
            sorted(
                self.alternatives,
                key=lambda item: (
                    item.normalized_value or "",
                    item.raw_value or "",
                    item.field_locator,
                ),
            )
        )
        object.__setattr__(self, "alternatives", ordered)

    def to_dict(self) -> dict[str, object]:
        return {
            "alternatives": [item.to_dict() for item in self.alternatives],
            "capture_sha256": self.capture_sha256,
            "field_locator": self.field_locator,
            "native_submission_identifier": self.native_submission_identifier,
            "normalized_value": self.normalized_value,
            "raw_value": self.raw_value,
            "source_identifier": self.source_identifier,
            "state": self.state.value,
            "unit": self.unit,
        }
