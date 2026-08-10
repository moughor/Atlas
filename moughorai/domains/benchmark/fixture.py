"""Strict parser for the single Atlas-owned Fire Strike fixture schema V1."""

from __future__ import annotations

from collections.abc import Mapping
import json
import re

from .canonical import sha256_hex
from .evidence import FieldEvidenceV1, FieldState
from .fire_strike import FIRE_STRIKE_STANDARD_BENCHMARK_ID, FireStrikeSubmissionV1


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROOT_FIELDS = {
    "benchmark_id",
    "native_submission_identifier",
    "schema_version",
    "scores",
    "source_identifier",
}
_SCORE_FIELDS = {"combined_score", "graphics_score", "overall_score", "physics_score"}
_BASE_FIELD_FIELDS = {"field_locator", "state", "unit"}
_OBSERVED_FIELD_FIELDS = _BASE_FIELD_FIELDS | {"normalized_value", "raw_value"}
_CONFLICTING_FIELD_FIELDS = _BASE_FIELD_FIELDS | {"alternatives"}


class FixtureParseError(ValueError):
    """The supplied bytes do not satisfy the Fire Strike fixture V1 contract."""


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise FixtureParseError(f"{label} must be an object")
    return value


def _exact_fields(value: Mapping[str, object], expected: set[str], label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise FixtureParseError(f"{label} is missing fields: {', '.join(missing)}")
    if unknown:
        raise FixtureParseError(f"{label} contains unknown fields: {', '.join(unknown)}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FixtureParseError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> object:
    raise FixtureParseError(f"invalid JSON numeric constant: {value}")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise FixtureParseError(f"{label} must be a string")
    return value


def _parse_field(
    value: object,
    *,
    source_identifier: str,
    native_submission_identifier: str,
    capture_sha256: str,
    label: str,
    require_observed: bool = False,
) -> FieldEvidenceV1:
    raw = _mapping(value, label)
    state_text = _string(raw.get("state"), f"{label} state")
    try:
        state = FieldState(state_text)
    except ValueError as error:
        raise FixtureParseError(f"{label} has unsupported state: {state_text}") from error
    if require_observed and state is not FieldState.OBSERVED:
        raise FixtureParseError(f"{label} must be observed")

    if state is FieldState.OBSERVED:
        _exact_fields(raw, _OBSERVED_FIELD_FIELDS, label)
        alternatives: tuple[FieldEvidenceV1, ...] = ()
        raw_value = _string(raw["raw_value"], f"{label} raw value")
        normalized_value = _string(raw["normalized_value"], f"{label} normalized value")
    elif state is FieldState.CONFLICTING:
        _exact_fields(raw, _CONFLICTING_FIELD_FIELDS, label)
        raw_alternatives = raw["alternatives"]
        if not isinstance(raw_alternatives, list):
            raise FixtureParseError(f"{label} alternatives must be an array")
        alternatives = tuple(
            _parse_field(
                item,
                source_identifier=source_identifier,
                native_submission_identifier=native_submission_identifier,
                capture_sha256=capture_sha256,
                label=f"{label} alternative {index}",
                require_observed=True,
            )
            for index, item in enumerate(raw_alternatives)
        )
        raw_value = None
        normalized_value = None
    else:
        _exact_fields(raw, _BASE_FIELD_FIELDS, label)
        alternatives = ()
        raw_value = None
        normalized_value = None

    try:
        return FieldEvidenceV1(
            state=state,
            source_identifier=source_identifier,
            native_submission_identifier=native_submission_identifier,
            capture_sha256=capture_sha256,
            field_locator=_string(raw["field_locator"], f"{label} locator"),
            raw_value=raw_value,
            normalized_value=normalized_value,
            unit=_string(raw["unit"], f"{label} unit"),
            alternatives=alternatives,
        )
    except (TypeError, ValueError) as error:
        raise FixtureParseError(f"invalid {label}: {error}") from error


def parse_fire_strike_submission_fixture(
    payload: bytes,
    expected_capture_sha256: str,
) -> FireStrikeSubmissionV1:
    """Parse one verified Atlas fixture without performing acquisition or I/O."""

    if not isinstance(payload, bytes):
        raise TypeError("fixture payload must be bytes")
    if not isinstance(expected_capture_sha256, str) or _SHA256.fullmatch(expected_capture_sha256) is None:
        raise FixtureParseError("expected capture SHA-256 must be 64 lowercase hexadecimal characters")
    actual_digest = sha256_hex(payload)
    if actual_digest != expected_capture_sha256:
        raise FixtureParseError("fixture capture SHA-256 does not match the supplied digest")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FixtureParseError("fixture must be valid UTF-8") from error
    try:
        decoded = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_constant,
        )
    except FixtureParseError:
        raise
    except json.JSONDecodeError as error:
        raise FixtureParseError("fixture must be valid JSON") from error

    root = _mapping(decoded, "fixture")
    _exact_fields(root, _ROOT_FIELDS, "fixture")
    version = root["schema_version"]
    if type(version) is not int or version != 1:
        raise FixtureParseError(f"unsupported fixture schema version: {version!r}")
    benchmark_id = _string(root["benchmark_id"], "benchmark identifier")
    if benchmark_id != FIRE_STRIKE_STANDARD_BENCHMARK_ID:
        raise FixtureParseError("fixture benchmark must be Fire Strike Standard")

    source_identifier = _string(root["source_identifier"], "source identifier")
    native_identifier = _string(
        root["native_submission_identifier"],
        "native submission identifier",
    )
    scores = _mapping(root["scores"], "fixture scores")
    _exact_fields(scores, _SCORE_FIELDS, "fixture scores")

    fields = {
        name: _parse_field(
            scores[name],
            source_identifier=source_identifier,
            native_submission_identifier=native_identifier,
            capture_sha256=actual_digest,
            label=name.replace("_", " "),
        )
        for name in sorted(_SCORE_FIELDS)
    }
    try:
        return FireStrikeSubmissionV1(
            source_identifier=source_identifier,
            native_submission_identifier=native_identifier,
            overall_score=fields["overall_score"],
            graphics_score=fields["graphics_score"],
            physics_score=fields["physics_score"],
            combined_score=fields["combined_score"],
        )
    except (TypeError, ValueError) as error:
        raise FixtureParseError(f"invalid Fire Strike submission: {error}") from error
