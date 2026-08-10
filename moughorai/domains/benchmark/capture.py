"""Immutable exact-byte captures for Benchmark Intelligence."""

from __future__ import annotations

from dataclasses import InitVar, KW_ONLY, dataclass, field
import re

from .canonical import canonical_json, canonical_json_bytes, normalize_text, sha256_hex


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID = re.compile(r"^source:[a-z0-9][a-z0-9-]*$")
_MEDIA_TYPE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$"
)


class CaptureValidationError(ValueError):
    """The supplied bytes or capture metadata violate the capture contract."""


def _normalized_text(value: str, label: str) -> str:
    try:
        return normalize_text(value)
    except ValueError as error:
        raise CaptureValidationError(f"{label} contains invalid Unicode") from error


def _source_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("source identifier must be a string or None")
    normalized = _normalized_text(value, "source identifier")
    if _SOURCE_ID.fullmatch(normalized) is None:
        raise CaptureValidationError(
            "source identifier must use the source:<lowercase-slug> form"
        )
    return normalized


def _media_type(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("media type must be a string or None")
    normalized = _normalized_text(value, "media type")
    if _MEDIA_TYPE.fullmatch(normalized) is None:
        raise CaptureValidationError("media type must be a bare type/subtype value")
    return normalized.lower()


@dataclass(frozen=True, slots=True)
class CapturedSourceV1:
    """Exact caller-supplied bytes with content identity and narrow metadata."""

    payload: bytes = field(repr=False)
    _: KW_ONLY
    expected_sha256: InitVar[str | None] = None
    source_identifier: str | None = None
    media_type: str | None = None

    def __post_init__(self, expected_sha256: str | None) -> None:
        if type(self.payload) is not bytes:
            raise TypeError("capture payload must be bytes")
        if expected_sha256 is not None:
            if not isinstance(expected_sha256, str):
                raise TypeError("expected SHA-256 must be a string or None")
            if _SHA256.fullmatch(expected_sha256) is None:
                raise CaptureValidationError(
                    "expected SHA-256 must be 64 lowercase hexadecimal characters"
                )

        digest = sha256_hex(self.payload)
        if expected_sha256 is not None and expected_sha256 != digest:
            raise CaptureValidationError(
                "capture SHA-256 does not match the expected digest"
            )

        source_identifier = _source_identifier(self.source_identifier)
        object.__setattr__(self, "source_identifier", source_identifier)
        object.__setattr__(self, "media_type", _media_type(self.media_type))

    @property
    def sha256(self) -> str:
        return sha256_hex(self.payload)

    @property
    def capture_id(self) -> str:
        return f"capture:sha256:{self.sha256}"

    @property
    def byte_length(self) -> int:
        return len(self.payload)

    def to_metadata_dict(self) -> dict[str, object]:
        return {
            "byte_length": self.byte_length,
            "capture_id": self.capture_id,
            "media_type": self.media_type,
            "sha256": self.sha256,
            "source_identifier": self.source_identifier,
        }

    def to_metadata_json(self) -> str:
        return canonical_json(self.to_metadata_dict())

    def to_metadata_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_metadata_dict())
