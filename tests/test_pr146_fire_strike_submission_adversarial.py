from __future__ import annotations

import ast
import json
from pathlib import Path
import sys

import pytest

from moughorai.domains.benchmark import (
    FieldEvidenceV1,
    FieldState,
    FixtureParseError,
    canonical_json,
    normalize_decimal,
    parse_fire_strike_submission_fixture,
    sha256_hex,
)


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "moughorai" / "domains" / "benchmark"
FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "benchmark_intelligence"
    / "fire_strike_submission_v1.json"
)


def _fixture_mapping() -> dict[str, object]:
    return json.loads(FIXTURE.read_bytes())


def _payload(value: dict[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _parse(value: dict[str, object]):
    payload = _payload(value)
    return parse_fire_strike_submission_fixture(payload, sha256_hex(payload))


def _scores(value: dict[str, object]) -> dict[str, object]:
    scores = value["scores"]
    assert isinstance(scores, dict)
    return scores


def test_capture_digest_is_verified_before_parsing() -> None:
    payload = FIXTURE.read_bytes()
    with pytest.raises(FixtureParseError, match="does not match"):
        parse_fire_strike_submission_fixture(payload, "0" * 64)
    with pytest.raises(FixtureParseError, match="64 lowercase"):
        parse_fire_strike_submission_fixture(payload, "invalid")


@pytest.mark.parametrize("payload", [b"{", b"\xff", b'{"value":NaN}'])
def test_malformed_utf8_json_and_non_finite_constants_are_rejected(payload: bytes) -> None:
    with pytest.raises(FixtureParseError):
        parse_fire_strike_submission_fixture(payload, sha256_hex(payload))


@pytest.mark.parametrize("surrogate", ["\ud800", "\udc00"])
def test_escaped_unpaired_surrogates_are_rejected_deterministically(
    surrogate: str,
) -> None:
    fixture = _fixture_mapping()
    score = _scores(fixture)["overall_score"]
    assert isinstance(score, dict)
    score["raw_value"] = surrogate
    payload = json.dumps(fixture, ensure_ascii=True, separators=(",", ":")).encode(
        "ascii"
    )
    digest = sha256_hex(payload)

    with pytest.raises(ValueError, match="Unicode scalar"):
        canonical_json({"value": surrogate})

    errors: list[str] = []
    for _ in range(2):
        with pytest.raises(FixtureParseError) as captured:
            parse_fire_strike_submission_fixture(payload, digest)
        errors.append(str(captured.value))

    assert errors == [
        "invalid overall score: canonical text must contain only Unicode scalar values"
    ] * 2


@pytest.mark.parametrize("version", [0, 2, True, "1", None])
def test_unsupported_schema_versions_are_rejected(version: object) -> None:
    fixture = _fixture_mapping()
    fixture["schema_version"] = version
    with pytest.raises(FixtureParseError, match="unsupported fixture schema"):
        _parse(fixture)


def test_another_fire_strike_variant_is_never_inferred() -> None:
    fixture = _fixture_mapping()
    fixture["benchmark_id"] = "benchmark:ul:3dmark:fire-strike-extreme"
    with pytest.raises(FixtureParseError, match="Fire Strike Standard"):
        _parse(fixture)


@pytest.mark.parametrize("level", ["root", "scores", "field"])
def test_unknown_fields_are_rejected_at_every_fixture_level(level: str) -> None:
    fixture = _fixture_mapping()
    if level == "root":
        target = fixture
    elif level == "scores":
        target = _scores(fixture)
    else:
        target = _scores(fixture)["overall_score"]
        assert isinstance(target, dict)
    target["unexpected"] = "value"
    with pytest.raises(FixtureParseError, match="unknown fields"):
        _parse(fixture)


def test_missing_required_fields_are_rejected() -> None:
    fixture = _fixture_mapping()
    del _scores(fixture)["physics_score"]
    with pytest.raises(FixtureParseError, match="missing fields"):
        _parse(fixture)


def test_duplicate_json_fields_are_rejected() -> None:
    text = json.dumps(_fixture_mapping(), ensure_ascii=False)
    duplicate = text.replace(
        '"schema_version": 1',
        '"schema_version": 1, "schema_version": 1',
        1,
    ).encode("utf-8")
    with pytest.raises(FixtureParseError, match="duplicate JSON field"):
        parse_fire_strike_submission_fixture(duplicate, sha256_hex(duplicate))


@pytest.mark.parametrize("field", ["raw_value", "normalized_value"])
def test_null_is_not_accepted_as_an_observed_value(field: str) -> None:
    fixture = _fixture_mapping()
    score = _scores(fixture)["overall_score"]
    assert isinstance(score, dict)
    score[field] = None
    with pytest.raises(FixtureParseError, match="must be a string"):
        _parse(fixture)


@pytest.mark.parametrize(
    "value",
    ["NaN", "Infinity", "-Infinity", "1e3", "+1", "01", ".5", "1.", ""],
)
def test_invalid_decimal_values_are_rejected(value: str) -> None:
    fixture = _fixture_mapping()
    score = _scores(fixture)["overall_score"]
    assert isinstance(score, dict)
    score["normalized_value"] = value
    with pytest.raises(FixtureParseError, match="strict finite decimal"):
        _parse(fixture)
    with pytest.raises(ValueError, match="strict finite decimal"):
        normalize_decimal(value)


def test_missing_state_cannot_smuggle_null_value_fields() -> None:
    fixture = _fixture_mapping()
    _scores(fixture)["combined_score"] = {
        "field_locator": "/scores/combined_score",
        "normalized_value": None,
        "raw_value": None,
        "state": "missing",
        "unit": "marks",
    }
    with pytest.raises(FixtureParseError, match="unknown fields"):
        _parse(fixture)


def test_conflict_requires_distinct_observed_alternatives() -> None:
    fixture = _fixture_mapping()
    observed = {
        "field_locator": "/scores/overall_score/first",
        "normalized_value": "30000",
        "raw_value": "30,000",
        "state": "observed",
        "unit": "marks",
    }
    _scores(fixture)["overall_score"] = {
        "alternatives": [observed, {**observed, "field_locator": "/scores/overall_score/second"}],
        "field_locator": "/scores/overall_score",
        "state": "conflicting",
        "unit": "marks",
    }
    with pytest.raises(FixtureParseError, match="distinct normalized values"):
        _parse(fixture)


@pytest.mark.parametrize(
    ("duplicate_locator", "duplicate_raw", "duplicate_normalized"),
    [
        ("/scores/overall_score/first", "100", "100"),
        ("/scores/overall_score/equivalent", "100.0", "100.0"),
    ],
)
def test_conflict_rejects_exact_and_semantically_equivalent_duplicates(
    duplicate_locator: str,
    duplicate_raw: str,
    duplicate_normalized: str,
) -> None:
    fixture = _fixture_mapping()
    first = {
        "field_locator": "/scores/overall_score/first",
        "normalized_value": "100",
        "raw_value": "100",
        "state": "observed",
        "unit": "marks",
    }
    duplicate = {
        **first,
        "field_locator": duplicate_locator,
        "normalized_value": duplicate_normalized,
        "raw_value": duplicate_raw,
    }
    distinct = {
        **first,
        "field_locator": "/scores/overall_score/distinct",
        "normalized_value": "200",
        "raw_value": "200",
    }
    _scores(fixture)["overall_score"] = {
        "alternatives": [first, duplicate, distinct],
        "field_locator": "/scores/overall_score",
        "state": "conflicting",
        "unit": "marks",
    }

    with pytest.raises(FixtureParseError, match="duplicate normalized values"):
        _parse(fixture)


def test_conflict_requires_at_least_two_alternatives() -> None:
    fixture = _fixture_mapping()
    _scores(fixture)["overall_score"] = {
        "alternatives": [],
        "field_locator": "/scores/overall_score",
        "state": "conflicting",
        "unit": "marks",
    }
    with pytest.raises(FixtureParseError, match="at least two"):
        _parse(fixture)


def test_score_unit_and_submission_provenance_are_enforced() -> None:
    fixture = _fixture_mapping()
    score = _scores(fixture)["physics_score"]
    assert isinstance(score, dict)
    score["unit"] = "frames_per_second"
    with pytest.raises(FixtureParseError, match="marks unit"):
        _parse(fixture)

    with pytest.raises(ValueError, match="source:<slug>"):
        FieldEvidenceV1(
            state=FieldState.MISSING,
            source_identifier="invalid-source",
            native_submission_identifier="fixture",
            capture_sha256="0" * 64,
            field_locator="/score",
            raw_value=None,
            normalized_value=None,
            unit="marks",
        )


def test_package_manifest_and_dependency_direction_remain_narrow() -> None:
    assert sorted(path.name for path in PACKAGE.glob("*.py")) == [
        "__init__.py",
        "canonical.py",
        "evidence.py",
        "fire_strike.py",
        "fixture.py",
    ]

    invalid_imports: list[str] = []
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                modules = (node.module or "",)
            else:
                continue
            for module in modules:
                if module.partition(".")[0] not in sys.stdlib_module_names:
                    invalid_imports.append(f"{path.name}: {module}")
    assert invalid_imports == []

    platform_imports: list[str] = []
    for path in (ROOT / "moughorai" / "platform").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and "benchmark" in (node.module or ""):
                platform_imports.append(f"{path.name}: {node.module}")
            if isinstance(node, ast.Import):
                platform_imports.extend(
                    f"{path.name}: {alias.name}"
                    for alias in node.names
                    if "benchmark" in alias.name
                )
    assert platform_imports == []
