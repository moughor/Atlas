from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from moughorai.benchmark_lab import BenchmarkLabRequestError, BenchmarkLabState
from moughorai.domains.benchmark import (
    FieldEvidenceV1,
    FieldState,
    FireStrikeSubmissionV1,
    FireStrikeSourceComparisonV1,
    ScoreComparisonState,
    ScoreFieldComparisonV1,
    calculate_fire_strike_score,
    compare_fire_strike_sources,
)


FIXTURES = Path(__file__).parent / "fixtures" / "benchmark_intelligence"
HWBOT = FIXTURES / "hwbot_fire_strike_submission_v1.html"
UL = FIXTURES / "ul_3dmark_fire_strike_result_v1.html"


def _calculation_payload(
    *,
    baseline: tuple[str, str, str] = ("22447", "56270", "7668"),
    candidate: tuple[str, str, str] = ("23000", "56270", "7668"),
) -> bytes:
    def score_set(values: tuple[str, str, str]) -> dict[str, str]:
        return {
            "graphics_score": values[0],
            "physics_score": values[1],
            "combined_score": values[2],
        }

    return json.dumps(
        {"baseline": score_set(baseline), "candidate": score_set(candidate)},
        separators=(",", ":"),
    ).encode("utf-8")


def _loaded_state() -> BenchmarkLabState:
    state = BenchmarkLabState()
    state.ingest_hwbot(HWBOT.read_bytes())
    state.ingest_ul(UL.read_bytes())
    return state


def test_empty_lab_state_is_explicit_and_deterministic() -> None:
    state = BenchmarkLabState()

    assert state.to_dict() == {
        "comparison": None,
        "schema_version": 1,
        "sources": {"hwbot": None, "ul_3dmark": None},
    }
    assert state.to_dict() == state.to_dict()


def test_existing_source_parsers_feed_bounded_lab_projection() -> None:
    state = _loaded_state().to_dict()
    hwbot = state["sources"]["hwbot"]
    ul = state["sources"]["ul_3dmark"]

    assert hwbot["source_identifier"] == "source:hwbot"
    assert hwbot["native_submission_identifier"] == "1480001"
    assert hwbot["scores"]["overall_score"]["normalized_value"] == "12345"
    assert ul["source_identifier"] == "source:ul-3dmark-results"
    assert ul["native_submission_identifier"] == "90000001"
    assert ul["scores"]["graphics_score"]["normalized_value"] == "13579"
    assert ul["scores"]["physics_score"]["normalized_value"] == "24680"
    assert ul["scores"]["combined_score"]["normalized_value"] == "6789"


def test_projection_retains_exact_capture_sha_lineage() -> None:
    state = _loaded_state().to_dict()["sources"]

    assert state["hwbot"]["capture_sha256"] == hashlib.sha256(
        HWBOT.read_bytes()
    ).hexdigest()
    assert state["ul_3dmark"]["capture_sha256"] == hashlib.sha256(
        UL.read_bytes()
    ).hexdigest()
    for source in state.values():
        for field in source["scores"].values():
            assert field["capture_sha256"] == source["capture_sha256"]


def test_projection_never_contains_source_bytes_paths_or_filenames() -> None:
    serialized = json.dumps(_loaded_state().to_dict(), sort_keys=True)

    assert "<!doctype" not in serialized
    assert str(FIXTURES) not in serialized
    assert HWBOT.name not in serialized
    assert UL.name not in serialized


def test_open_original_urls_derive_only_from_parser_native_identity() -> None:
    sources = _loaded_state().to_dict()["sources"]

    assert sources["hwbot"]["open_original_url"] == (
        "https://hwbot.org/benchmarks/3dmark_-_fire_strike/submissions/1480001"
    )
    assert sources["ul_3dmark"]["open_original_url"] == (
        "https://www.3dmark.com/fs/90000001"
    )


def test_failed_replacement_upload_is_atomic() -> None:
    state = BenchmarkLabState()
    accepted = state.ingest_ul(UL.read_bytes())

    with pytest.raises(ValueError):
        state.ingest_ul(b"<html>not a supported result</html>")

    assert state.to_dict() == accepted


def test_reset_removes_all_in_memory_parsed_state() -> None:
    state = _loaded_state()

    assert state.reset() == {
        "comparison": None,
        "schema_version": 1,
        "sources": {"hwbot": None, "ul_3dmark": None},
    }


def test_fixture_overall_scores_agree_without_claiming_run_linkage() -> None:
    comparison = _loaded_state().to_dict()["comparison"]

    assert comparison["fields"]["overall_score"] == {
        "hwbot_state": "observed",
        "hwbot_value": "12345",
        "state": "agreement",
        "ul_state": "observed",
        "ul_value": "12345",
        "unit": "marks",
    }
    assert comparison["run_linkage"] == "unknown"
    assert "no explicit" in comparison["run_linkage_reason"]
    assert "run_id" not in comparison


@pytest.mark.parametrize(
    "field",
    ["graphics_score", "physics_score", "combined_score"],
)
def test_hwbot_missing_components_are_missing_not_disagreement(field: str) -> None:
    comparison = _loaded_state().to_dict()["comparison"]["fields"][field]

    assert comparison["state"] == "missing"
    assert comparison["hwbot_state"] == "missing"
    assert comparison["hwbot_value"] is None
    assert comparison["ul_state"] == "observed"


def test_distinct_overall_scores_are_disagreement() -> None:
    state = BenchmarkLabState()
    hwbot = HWBOT.read_bytes().replace(b"12,345", b"12,346")
    state.ingest_hwbot(hwbot)
    state.ingest_ul(UL.read_bytes())

    field = state.to_dict()["comparison"]["fields"]["overall_score"]
    assert field["state"] == "disagreement"
    assert field["hwbot_value"] == "12346"
    assert field["ul_value"] == "12345"


def _conflicting(field: FieldEvidenceV1, other: str) -> FieldEvidenceV1:
    alternative = replace(
        field,
        field_locator=f"{field.field_locator}[2]",
        raw_value=other,
        normalized_value=other,
    )
    return FieldEvidenceV1(
        state=FieldState.CONFLICTING,
        source_identifier=field.source_identifier,
        native_submission_identifier=field.native_submission_identifier,
        capture_sha256=field.capture_sha256,
        field_locator=field.field_locator,
        raw_value=None,
        normalized_value=None,
        unit=field.unit,
        alternatives=(field, alternative),
    )


def test_conflicting_source_evidence_is_not_comparable() -> None:
    loaded = _loaded_state()
    assert loaded._ul is not None
    loaded._ul = replace(
        loaded._ul,
        overall_score=_conflicting(loaded._ul.overall_score, "12346"),
    )

    field = loaded.to_dict()["comparison"]["fields"]["overall_score"]
    assert field["state"] == "not_comparable"
    assert field["ul_state"] == "conflicting"
    assert field["ul_value"] is None


def _observed(
    *,
    source: str,
    native: str,
    value: str,
    locator: str,
) -> FieldEvidenceV1:
    return FieldEvidenceV1(
        state=FieldState.OBSERVED,
        source_identifier=source,
        native_submission_identifier=native,
        capture_sha256="a" * 64,
        field_locator=locator,
        raw_value=value,
        normalized_value=value,
        unit="marks",
    )


def _submission(source: str, native: str, value: str) -> FireStrikeSubmissionV1:
    field = _observed(
        source=source,
        native=native,
        value=value,
        locator="/score",
    )
    return FireStrikeSubmissionV1(
        source_identifier=source,
        native_submission_identifier=native,
        overall_score=field,
        graphics_score=field,
        physics_score=field,
        combined_score=field,
    )


def test_observed_zero_is_comparable_and_equal() -> None:
    comparison = compare_fire_strike_sources(
        _submission("source:hwbot", "1", "0"),
        _submission("source:ul-3dmark-results", "2", "0"),
    )

    assert comparison.overall_score.state is ScoreComparisonState.AGREEMENT
    assert comparison.overall_score.hwbot_value == "0"
    assert comparison.overall_score.ul_value == "0"


def test_source_roles_are_enforced_and_not_order_inferred() -> None:
    hwbot = _submission("source:hwbot", "1", "10")
    ul = _submission("source:ul-3dmark-results", "2", "10")

    with pytest.raises(ValueError, match="left comparison"):
        compare_fire_strike_sources(ul, ul)
    with pytest.raises(ValueError, match="right comparison"):
        compare_fire_strike_sources(hwbot, hwbot)
    with pytest.raises(ValueError, match="left comparison"):
        compare_fire_strike_sources(ul, hwbot)


def test_comparison_serialization_is_canonical_and_repeatable() -> None:
    first = _loaded_state().to_dict()["comparison"]
    second = _loaded_state().to_dict()["comparison"]

    assert first == second
    assert list(first["fields"]) == [
        "combined_score",
        "graphics_score",
        "overall_score",
        "physics_score",
    ]


def test_calculator_reproduces_authorized_vector_and_records_method() -> None:
    value = BenchmarkLabState().calculate(_calculation_payload())

    assert value["baseline"]["overall_score"] == "20358"
    assert value["baseline"]["method_id"].endswith("integral-components-v1")
    assert value["baseline"]["rounding_policy"] == "floor-weighted-harmonic-mean"
    assert value["schema_version"] == 1


def test_what_if_delta_and_percentage_are_server_derived() -> None:
    value = BenchmarkLabState().calculate(_calculation_payload())
    expected = calculate_fire_strike_score(23000, 56270, 7668).overall_score

    assert value["candidate"]["overall_score"] == str(expected)
    assert value["delta_score"] == str(expected - 20358)
    assert value["percentage_delta"] == "1.67"
    assert value["percentage_rounding"] == "nearest-hundredth-half-up"


def test_negative_what_if_percentage_uses_symmetric_half_up_rounding() -> None:
    value = BenchmarkLabState().calculate(
        _calculation_payload(
            baseline=("23000", "56270", "7668"),
            candidate=("22447", "56270", "7668"),
        )
    )

    assert value["delta_score"].startswith("-")
    assert value["percentage_delta"].startswith("-")


@pytest.mark.parametrize(
    "payload",
    [
        b"[]",
        b"{}",
        b'{"baseline":{},"candidate":{},"extra":{}}',
        b'{"baseline":{},"baseline":{},"candidate":{}}',
        b"\xff",
    ],
)
def test_calculation_json_shape_is_strict(payload: bytes) -> None:
    with pytest.raises(BenchmarkLabRequestError):
        BenchmarkLabState().calculate(payload)


def test_calculation_rejects_non_string_and_unknown_component_values() -> None:
    decoded = json.loads(_calculation_payload())
    decoded["baseline"]["graphics_score"] = 22447
    with pytest.raises(BenchmarkLabRequestError, match="must be a string"):
        BenchmarkLabState().calculate(json.dumps(decoded).encode())

    decoded = json.loads(_calculation_payload())
    decoded["baseline"]["unknown"] = "1"
    with pytest.raises(BenchmarkLabRequestError, match="exactly"):
        BenchmarkLabState().calculate(json.dumps(decoded).encode())


def test_calculation_never_labels_derived_values_as_observed() -> None:
    serialized = json.dumps(BenchmarkLabState().calculate(_calculation_payload()))

    assert '"state": "observed"' not in serialized
    assert "capture_sha256" not in serialized
    assert "field_locator" not in serialized


def test_score_field_comparison_rejects_inconsistent_direct_construction() -> None:
    with pytest.raises(ValueError, match="does not match"):
        ScoreFieldComparisonV1(
            state=ScoreComparisonState.AGREEMENT,
            hwbot_state=FieldState.OBSERVED,
            ul_state=FieldState.OBSERVED,
            hwbot_value="1",
            ul_value="2",
            unit="marks",
        )


@pytest.mark.parametrize("value", ["", "not-a-score", "01", "1.0", " 1", "1 "])
def test_score_field_comparison_rejects_noncanonical_direct_values(value: str) -> None:
    with pytest.raises(ValueError, match="canonical normalized decimal"):
        ScoreFieldComparisonV1(
            state=ScoreComparisonState.AGREEMENT,
            hwbot_state=FieldState.OBSERVED,
            ul_state=FieldState.OBSERVED,
            hwbot_value=value,
            ul_value=value,
            unit="marks",
        )


@pytest.mark.parametrize(
    "identity",
    [
        "submission:source:hwbot:",
        "submission:source:hwbot:x:forged",
        "submission:source:hwbot:x\n",
        "submission:source:hwbot:UPPER",
    ],
)
def test_source_comparison_rejects_malformed_direct_identities(identity: str) -> None:
    comparison = compare_fire_strike_sources(
        _submission("source:hwbot", "1", "10"),
        _submission("source:ul-3dmark-results", "2", "10"),
    )

    with pytest.raises(ValueError, match="HWBOT submission identity is invalid"):
        FireStrikeSourceComparisonV1(
            overall_score=comparison.overall_score,
            graphics_score=comparison.graphics_score,
            physics_score=comparison.physics_score,
            combined_score=comparison.combined_score,
            hwbot_submission_id=identity,
            ul_submission_id=comparison.ul_submission_id,
        )
