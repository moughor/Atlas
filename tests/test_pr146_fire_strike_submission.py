from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from moughorai.domains.benchmark import (
    FIRE_STRIKE_STANDARD_BENCHMARK_ID,
    FieldEvidenceV1,
    FieldState,
    canonical_json,
    normalize_decimal,
    parse_fire_strike_submission_fixture,
    sha256_hex,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "benchmark_intelligence"
    / "fire_strike_submission_v1.json"
)


def _fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


def _fixture_mapping() -> dict[str, object]:
    return json.loads(_fixture_bytes())


def _parse_mapping(value: dict[str, object], *, sort_keys: bool = False):
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=sort_keys,
    ).encode("utf-8")
    return parse_fire_strike_submission_fixture(payload, sha256_hex(payload))


def test_primary_fixture_parses_to_one_canonical_fire_strike_submission() -> None:
    payload = _fixture_bytes()
    capture_sha256 = sha256_hex(payload)

    submission = parse_fire_strike_submission_fixture(payload, capture_sha256)

    assert submission.schema_version == 1
    assert submission.benchmark_id == FIRE_STRIKE_STANDARD_BENCHMARK_ID
    assert submission.submission_id == (
        "submission:source:atlas-fixture:fire-strike-submission-v1"
    )
    expected = {
        "overall_score": ("30,000", "30000"),
        "graphics_score": ("40,000", "40000"),
        "physics_score": ("25,000", "25000"),
        "combined_score": ("15,000", "15000"),
    }
    for field_name, values in expected.items():
        evidence = getattr(submission, field_name)
        assert evidence.state is FieldState.OBSERVED
        assert (evidence.raw_value, evidence.normalized_value) == values
        assert evidence.unit == "marks"
        assert evidence.source_identifier == "source:atlas-fixture"
        assert evidence.native_submission_identifier == "fire-strike-submission-v1"
        assert evidence.capture_sha256 == capture_sha256
        assert evidence.field_locator == f"/scores/{field_name}"


def test_submission_is_immutable_and_serializes_deterministically() -> None:
    payload = _fixture_bytes()
    digest = sha256_hex(payload)
    first = parse_fire_strike_submission_fixture(payload, digest)
    second = parse_fire_strike_submission_fixture(payload, digest)

    assert first == second
    assert first.to_bytes() == second.to_bytes()
    assert first.to_json() == canonical_json(first.to_dict())
    assert first.canonical_sha256 == second.canonical_sha256
    assert first.to_json().startswith('{"benchmark_id":')
    assert "\n" not in first.to_json()
    with pytest.raises(FrozenInstanceError):
        first.source_identifier = "source:changed"  # type: ignore[misc]


@pytest.mark.parametrize("state", ["missing", "unavailable", "not_applicable"])
def test_non_observed_score_states_are_explicit(state: str) -> None:
    fixture = _fixture_mapping()
    scores = fixture["scores"]
    assert isinstance(scores, dict)
    scores["combined_score"] = {
        "field_locator": "/scores/combined_score",
        "state": state,
        "unit": "marks",
    }

    submission = _parse_mapping(fixture)

    assert submission.combined_score.state.value == state
    assert submission.combined_score.raw_value is None
    assert submission.combined_score.normalized_value is None
    assert submission.combined_score.alternatives == ()


def test_zero_is_a_valid_observed_score_and_is_not_missing() -> None:
    fixture = _fixture_mapping()
    scores = fixture["scores"]
    assert isinstance(scores, dict)
    score = scores["combined_score"]
    assert isinstance(score, dict)
    score["raw_value"] = "0.000"
    score["normalized_value"] = "-0.0"

    submission = _parse_mapping(fixture)

    assert submission.combined_score.state is FieldState.OBSERVED
    assert submission.combined_score.raw_value == "0.000"
    assert submission.combined_score.normalized_value == "0"


def test_conflicting_score_preserves_and_orders_each_direct_observation() -> None:
    fixture = _fixture_mapping()
    scores = fixture["scores"]
    assert isinstance(scores, dict)
    scores["graphics_score"] = {
        "alternatives": [
            {
                "field_locator": "/scores/graphics_score/second",
                "normalized_value": "42000",
                "raw_value": "42,000",
                "state": "observed",
                "unit": "marks",
            },
            {
                "field_locator": "/scores/graphics_score/first",
                "normalized_value": "41000",
                "raw_value": "41,000",
                "state": "observed",
                "unit": "marks",
            },
        ],
        "field_locator": "/scores/graphics_score",
        "state": "conflicting",
        "unit": "marks",
    }

    submission = _parse_mapping(fixture)

    assert submission.graphics_score.state is FieldState.CONFLICTING
    assert [
        item.normalized_value for item in submission.graphics_score.alternatives
    ] == ["41000", "42000"]
    assert all(
        item.capture_sha256 == submission.graphics_score.capture_sha256
        for item in submission.graphics_score.alternatives
    )


def test_conflicting_score_canonical_output_and_identity_are_stable() -> None:
    fixture = _fixture_mapping()
    scores = fixture["scores"]
    assert isinstance(scores, dict)
    scores["graphics_score"] = {
        "alternatives": [
            {
                "field_locator": "/scores/graphics_score/second",
                "normalized_value": "42000",
                "raw_value": "42,000",
                "state": "observed",
                "unit": "marks",
            },
            {
                "field_locator": "/scores/graphics_score/first",
                "normalized_value": "41000",
                "raw_value": "41,000",
                "state": "observed",
                "unit": "marks",
            },
        ],
        "field_locator": "/scores/graphics_score",
        "state": "conflicting",
        "unit": "marks",
    }

    first = _parse_mapping(fixture)
    evidence = first.graphics_score
    reordered_evidence = FieldEvidenceV1(
        state=evidence.state,
        source_identifier=evidence.source_identifier,
        native_submission_identifier=evidence.native_submission_identifier,
        capture_sha256=evidence.capture_sha256,
        field_locator=evidence.field_locator,
        raw_value=evidence.raw_value,
        normalized_value=evidence.normalized_value,
        unit=evidence.unit,
        alternatives=tuple(reversed(evidence.alternatives)),
    )
    second = replace(first, graphics_score=reordered_evidence)

    assert first == second
    assert first.to_bytes() == second.to_bytes()
    assert first.canonical_sha256 == second.canonical_sha256
    assert first.submission_id == second.submission_id


def test_reordered_fixture_fields_preserve_source_identity_and_scores() -> None:
    fixture = _fixture_mapping()
    reordered = dict(reversed(tuple(fixture.items())))
    scores = reordered['scores']
    assert isinstance(scores, dict)
    reordered['scores'] = dict(reversed(tuple(scores.items())))
    first = _parse_mapping(fixture, sort_keys=True)
    second = _parse_mapping(reordered, sort_keys=False)

    assert first.submission_id == second.submission_id
    assert first.benchmark_id == second.benchmark_id
    assert first.overall_score.normalized_value == second.overall_score.normalized_value
    assert first.graphics_score.normalized_value == second.graphics_score.normalized_value
    assert first.overall_score.capture_sha256 != second.overall_score.capture_sha256


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", "0"),
        ("-0.000", "0"),
        ("10.5000", "10.5"),
        ("-42.250", "-42.25"),
    ],
)
def test_decimal_normalization_is_exact(value: str, expected: str) -> None:
    assert normalize_decimal(value) == expected


def test_canonical_json_normalizes_unicode_to_nfc() -> None:
    assert canonical_json({"label": "Fire Strik\u0065\u0301"}) == (
        '{"label":"Fire Strik\u00e9"}'
    )
