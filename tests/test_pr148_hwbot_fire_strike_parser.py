from __future__ import annotations

import builtins
from pathlib import Path
import socket

import pytest

from moughorai.domains.benchmark import (
    FIRE_STRIKE_STANDARD_BENCHMARK_ID,
    CapturedSourceV1,
    FieldState,
    HWBOTFireStrikeParseError,
    parse_hwbot_fire_strike_submission,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "benchmark_intelligence"
    / "hwbot_fire_strike_submission_v1.html"
)
STANDARD_PATH = "/benchmarks/3dmark_-_fire_strike"
USER_PATH = "/users/atlas-fixture-user"


def _html(
    *,
    benchmark_links: tuple[tuple[str, str], ...] = (
        (STANDARD_PATH, "3DMark - Fire Strike"),
    ),
    scores: tuple[str, ...] = ("12,345",),
    ranking_ids: tuple[str, ...] = ("1480001",),
    ranking_score: str = "12,345",
    header_user: str = USER_PATH,
    ranking_user: str = USER_PATH,
    before: str = "",
    after: str = "",
    score_scope_before: str = "",
    score_scope_after: str = "",
    wrapper_before: str = "",
    wrapper_after: str = "",
    score_before: str = "",
    score_after: str = "",
) -> str:
    benchmark_markup = "".join(
        f'<a href="{path}">{label}</a>' for path, label in benchmark_links
    )
    score_markup = "".join(
        f'<div class="value"><span class="score-item">{score}</span> marks</div>'
        for score in scores
    )
    score_markup = f"{score_before}{score_markup}{score_after}"
    ranking_markup = "".join(
        (
            '<div class="wr-ranking-grid">'
            f'<a href="{ranking_user}">Atlas Fixture User</a>'
            f'<a href="{STANDARD_PATH}/submissions/{identifier}">'
            f"{ranking_score} marks</a></div>"
        )
        for identifier in ranking_ids
    )
    return (
        "<!doctype html><html><head><title>99,999 marks</title></head><body>"
        f"{before}<div id=\"submission-data-wrapper\">"
        f"{score_scope_before}"
        '<div id="submission-score-wrapper">'
        f'<div class="user"><a href="{header_user}">Atlas Fixture User</a>'
        f"{benchmark_markup}</div>"
        f'{wrapper_before}<div class="score-wrapper">{score_markup}</div>'
        f"{wrapper_after}</div>"
        f"{score_scope_after}{ranking_markup}</div>{after}</body></html>"
    )


def _capture(
    payload: str | bytes,
    *,
    source_identifier: str | None = "source:hwbot",
    media_type: str | None = "text/html",
) -> CapturedSourceV1:
    encoded = payload.encode("utf-8") if isinstance(payload, str) else payload
    return CapturedSourceV1(
        encoded,
        source_identifier=source_identifier,
        media_type=media_type,
    )


def _parse(payload: str, **metadata: str | None):
    return parse_hwbot_fire_strike_submission(_capture(payload, **metadata))


def test_valid_standard_fixture_produces_existing_submission_model() -> None:
    capture = _capture(FIXTURE.read_bytes())
    submission = parse_hwbot_fire_strike_submission(capture)

    assert submission.benchmark_id == FIRE_STRIKE_STANDARD_BENCHMARK_ID
    assert submission.source_identifier == "source:hwbot"
    assert submission.native_submission_identifier == "1480001"
    assert submission.submission_id == "submission:source:hwbot:1480001"
    assert submission.overall_score.state is FieldState.OBSERVED
    assert submission.overall_score.raw_value == "12,345"
    assert submission.overall_score.normalized_value == "12345"
    assert submission.overall_score.unit == "marks"


def test_repeated_parsing_and_canonical_output_are_stable() -> None:
    capture = _capture(FIXTURE.read_bytes())

    first = parse_hwbot_fire_strike_submission(capture)
    second = parse_hwbot_fire_strike_submission(capture)

    assert first == second
    assert first.to_bytes() == second.to_bytes()
    assert first.canonical_sha256 == second.canonical_sha256
    assert first.overall_score == second.overall_score


def test_every_score_field_retains_exact_capture_sha256() -> None:
    capture = _capture(_html(scores=("12,345", "12,346")))
    submission = parse_hwbot_fire_strike_submission(capture)

    fields = (
        submission.overall_score,
        submission.graphics_score,
        submission.physics_score,
        submission.combined_score,
        *submission.overall_score.alternatives,
    )
    assert all(field.capture_sha256 == capture.sha256 for field in fields)


@pytest.mark.parametrize(
    ("source_identifier", "message"),
    [(None, "source identifier"), ("source:ul-3dmark", "source identifier")],
)
def test_missing_or_wrong_source_identifier_is_rejected(
    source_identifier: str | None,
    message: str,
) -> None:
    with pytest.raises(HWBOTFireStrikeParseError, match=message):
        _parse(_html(), source_identifier=source_identifier)


@pytest.mark.parametrize(
    "media_type",
    [None, "application/xhtml+xml", "application/octet-stream"],
)
def test_missing_or_wrong_media_type_is_rejected(media_type: str | None) -> None:
    with pytest.raises(HWBOTFireStrikeParseError, match="media type"):
        _parse(_html(), media_type=media_type)


def test_invalid_utf8_is_rejected_before_html_interpretation() -> None:
    with pytest.raises(HWBOTFireStrikeParseError, match="valid UTF-8"):
        parse_hwbot_fire_strike_submission(_capture(b"\xff\xfe"))


def test_missing_required_score_wrapper_is_rejected() -> None:
    payload = _html().replace('id="submission-score-wrapper"', 'id="other"')

    with pytest.raises(HWBOTFireStrikeParseError, match="wrapper"):
        _parse(payload)


def test_duplicate_score_wrapper_is_rejected() -> None:
    payload = _html().replace(
        '<div id="submission-score-wrapper">',
        '<div id="submission-score-wrapper"><div id="submission-score-wrapper">',
    )

    with pytest.raises(HWBOTFireStrikeParseError, match="duplicated"):
        _parse(payload)


def test_missing_benchmark_path_is_rejected() -> None:
    with pytest.raises(HWBOTFireStrikeParseError, match="benchmark path is missing"):
        _parse(_html(benchmark_links=()))


def test_exact_standard_path_and_cosmetic_standard_label_are_accepted() -> None:
    submission = _parse(
        _html(benchmark_links=((STANDARD_PATH, "  3dmark   fire   strike standard  "),))
    )

    assert submission.benchmark_id == FIRE_STRIKE_STANDARD_BENCHMARK_ID


@pytest.mark.parametrize(
    ("path", "label"),
    [
        ("/benchmarks/3dmark_-_fire_strike_extreme", "3DMark - Fire Strike Extreme"),
        ("/benchmarks/3dmark_-_fire_strike_ultra", "3DMark - Fire Strike Ultra"),
        ("/benchmarks/3dmark_-_fire_strike_%28gpu%29", "3DMark - Fire Strike (GPU)"),
        ("/benchmarks/3dmark_-_fire_strike_custom", "3DMark - Fire Strike Custom"),
    ],
)
def test_unsupported_fire_strike_variants_are_rejected(
    path: str,
    label: str,
) -> None:
    with pytest.raises(HWBOTFireStrikeParseError, match="unsupported HWBOT benchmark"):
        _parse(_html(benchmark_links=((path, label),)))


def test_conflicting_benchmark_paths_are_rejected() -> None:
    links = (
        (STANDARD_PATH, "3DMark - Fire Strike"),
        ("/benchmarks/3dmark_-_fire_strike_extreme", "Fire Strike Extreme"),
    )

    with pytest.raises(HWBOTFireStrikeParseError, match="conflicting benchmark paths"):
        _parse(_html(benchmark_links=links))


@pytest.mark.parametrize(
    "label",
    ["3DMark - Time Spy", "3DMark - Fire Strike Extreme", "Fire Strike Ultimate"],
)
def test_explicit_contradictory_visible_label_is_rejected(label: str) -> None:
    with pytest.raises(HWBOTFireStrikeParseError, match="visible benchmark label"):
        _parse(_html(benchmark_links=((STANDARD_PATH, label),)))


def test_missing_native_submission_identifier_is_rejected() -> None:
    with pytest.raises(HWBOTFireStrikeParseError, match="identifier is missing"):
        _parse(_html(ranking_ids=()))


@pytest.mark.parametrize("identifier", ["submission", "12a", "١٤٨٠٠٠١", "0"])
def test_malformed_or_nonpositive_native_identifier_is_rejected(
    identifier: str,
) -> None:
    with pytest.raises(HWBOTFireStrikeParseError, match="positive decimal"):
        _parse(_html(ranking_ids=(identifier,)))


def test_leading_zero_native_identifier_is_rejected() -> None:
    with pytest.raises(HWBOTFireStrikeParseError, match="without leading zeros"):
        _parse(_html(ranking_ids=("01480001",)))


def test_multiple_distinct_matching_native_identifiers_are_rejected() -> None:
    with pytest.raises(HWBOTFireStrikeParseError, match="identifier is ambiguous"):
        _parse(_html(ranking_ids=("1480001", "1480002")))


def test_repeated_matching_native_identifier_is_deduplicated() -> None:
    submission = _parse(_html(ranking_ids=("1480001", "1480001")))

    assert submission.native_submission_identifier == "1480001"


def test_unrelated_ranking_row_does_not_supply_native_identifier() -> None:
    with pytest.raises(HWBOTFireStrikeParseError, match="identifier is missing"):
        _parse(_html(ranking_user="/users/another-user"))


def test_missing_overall_score_is_rejected() -> None:
    with pytest.raises(HWBOTFireStrikeParseError, match="overall score is missing"):
        _parse(_html(scores=()))


@pytest.mark.parametrize(
    "score",
    ["", "12,34", "01", "+123", "1e3", "NaN", "-1", "12 marks"],
)
def test_malformed_overall_score_is_rejected(score: str) -> None:
    with pytest.raises(HWBOTFireStrikeParseError, match="overall score is malformed"):
        _parse(_html(scores=(score,), ranking_score=score))


def test_zero_is_a_valid_observed_score() -> None:
    submission = _parse(_html(scores=("0",), ranking_score="0"))

    assert submission.overall_score.state is FieldState.OBSERVED
    assert submission.overall_score.normalized_value == "0"


def test_duplicate_identical_score_collapses_to_one_observation() -> None:
    submission = _parse(_html(scores=("12,345", "12,345")))

    assert submission.overall_score.state is FieldState.OBSERVED
    assert submission.overall_score.raw_value == "12,345"
    assert submission.overall_score.alternatives == ()


def test_lexical_duplicates_normalizing_to_same_score_collapse() -> None:
    submission = _parse(_html(scores=("12,345", "12345.0")))

    assert submission.overall_score.state is FieldState.OBSERVED
    assert submission.overall_score.normalized_value == "12345"
    assert submission.overall_score.alternatives == ()


def test_distinct_authoritative_scores_produce_evidence_backed_conflict() -> None:
    submission = _parse(_html(scores=("12,346", "12,345")))

    field = submission.overall_score
    assert field.state is FieldState.CONFLICTING
    assert field.raw_value is None
    assert field.normalized_value is None
    assert [item.normalized_value for item in field.alternatives] == ["12345", "12346"]
    assert {item.field_locator for item in field.alternatives} == {
        "//*[@id='submission-score-wrapper']//span[@class='score-item'][1]",
        "//*[@id='submission-score-wrapper']//span[@class='score-item'][2]",
    }


def test_irrelevant_scores_outside_authoritative_wrapper_are_ignored() -> None:
    payload = _html(
        before='<aside><span class="score-item">99,999</span></aside>',
        after='<div class="wr-ranking-grid"><a href="/users/other">Other</a>'
        f'<a href="{STANDARD_PATH}/submissions/9999999">99,999 marks</a></div>',
    )

    submission = _parse(payload)

    assert submission.overall_score.normalized_value == "12345"
    assert submission.native_submission_identifier == "1480001"


@pytest.mark.parametrize(
    "parts",
    [
        {"score_before": '<div hidden><span class="score-item">99,999</span></div>'},
        {"score_after": '<aside class="suggestion"><span class="score-item">99,999</span></aside>'},
        {"wrapper_before": '<div class="wr-ranking-grid"><span class="score-item">99,999</span></div>'},
        {"score_before": '<section><div><aside><span class="score-item">99,999</span></aside></div></section>'},
        {"wrapper_before": '<aside><span class="score-item">99,999</span></aside>'},
        {"wrapper_after": '<aside><span class="score-item">99,999</span></aside>'},
    ],
    ids=("hidden", "suggestion", "ranking", "deeply-nested", "before", "after"),
)
def test_non_authoritative_score_descendants_are_ignored(parts: dict[str, str]) -> None:
    submission = _parse(_html(**parts))

    assert submission.overall_score.state is FieldState.OBSERVED
    assert submission.overall_score.normalized_value == "12345"
    assert submission.overall_score.alternatives == ()


@pytest.mark.parametrize(
    "payload",
    [
        _html(
            score_scope_before="<section hidden>",
            score_scope_after="</section>",
        ),
        _html().replace(
            'id="submission-score-wrapper"',
            'id="submission-score-wrapper" hidden',
            1,
        ),
        _html().replace(
            '<div class="score-wrapper">',
            '<div class="score-wrapper" hidden>',
            1,
        ),
        _html().replace(
            '<div class="value">',
            '<div class="value" hidden>',
            1,
        ),
        _html().replace(
            '<span class="score-item">',
            '<span class="score-item" hidden>',
            1,
        ),
        _html(
            score_scope_before='<section class="suggestion">',
            score_scope_after="</section>",
        ),
        _html(
            score_scope_before='<section class="wr-ranking-grid">',
            score_scope_after="</section>",
        ),
        _html(
            scores=(),
            ranking_score="99,999",
            wrapper_before=(
                '<div class="score-wrapper"><section><div class="value">'
                '<span class="score-item">99,999</span> marks'
                "</div></section></div>"
            ),
        ),
        _html(
            scores=(),
            ranking_score="99,999",
            wrapper_before=(
                '<div class="score-wrapper"><div class="value"><section>'
                '<span class="score-item">99,999</span></section> marks'
                "</div></div>"
            ),
        ),
    ],
    ids=(
        "hidden-ancestor",
        "hidden-root",
        "hidden-score-wrapper",
        "hidden-value",
        "hidden-score-item",
        "suggestion-ancestor",
        "ranking-ancestor",
        "wrapper-between-score-wrapper-and-value",
        "wrapper-between-value-and-score-item",
    ),
)
def test_non_authoritative_exact_score_paths_are_missing(payload: str) -> None:
    with pytest.raises(
        HWBOTFireStrikeParseError,
        match="authoritative overall score is missing",
    ):
        _parse(payload)


@pytest.mark.parametrize(
    "parts",
    [
        {
            "score_before": (
                '<div class="value wr-ranking-grid">'
                '<span class="score-item">99,999</span> marks</div>'
            )
        },
        {
            "wrapper_before": (
                '<div class="score-wrapper hidden"><div class="value">'
                '<span class="score-item">99,999</span> marks</div></div>'
            )
        },
        {
            "wrapper_before": (
                '<div class="score-wrapper suggestion"><div class="value">'
                '<span class="score-item">99,999</span> marks</div></div>'
            )
        },
        {
            "wrapper_before": (
                '<div class="score-wrapper wr-ranking-grid"><div class="value">'
                '<span class="score-item">99,999</span> marks</div></div>'
            )
        },
        {
            "wrapper_after": (
                '<div class="score-wrapper suggestion"><div class="value">'
                '<span class="score-item">99,999</span> marks</div></div>'
            )
        },
        {
            "score_before": (
                '<!-- <div class="value"><span class="score-item">'
                "99,999</span> marks</div> -->"
            )
        },
    ],
    ids=(
        "ranking-value",
        "hidden-wrapper-before",
        "suggestion-wrapper-before",
        "ranking-wrapper-before",
        "suggestion-wrapper-after",
        "commented-path",
    ),
)
def test_non_authoritative_exact_score_decoys_are_ignored(
    parts: dict[str, str],
) -> None:
    submission = _parse(_html(**parts))

    assert submission.overall_score.state is FieldState.OBSERVED
    assert submission.overall_score.raw_value == "12,345"
    assert submission.overall_score.normalized_value == "12345"
    assert submission.overall_score.alternatives == ()


def test_unrelated_hidden_void_element_does_not_open_score_exclusion_scope() -> None:
    submission = _parse(_html(before="<input hidden>"))

    assert submission.overall_score.state is FieldState.OBSERVED
    assert submission.overall_score.normalized_value == "12345"


@pytest.mark.parametrize(
    "payload",
    [
        _html(wrapper_before="<input hidden>"),
        _html(score_before="<br>"),
        _html().replace(
            '<span class="score-item">12,345</span>',
            '<br><span class="score-item">12,345</span>',
            1,
        ),
    ],
    ids=("before-score-wrapper", "before-value", "before-score-item"),
)
def test_void_siblings_do_not_change_direct_score_parentage(payload: str) -> None:
    submission = _parse(payload)

    assert submission.overall_score.state is FieldState.OBSERVED
    assert submission.overall_score.normalized_value == "12345"


@pytest.mark.parametrize("marker", ["hidden", "suggestion", "wr-ranking-grid"])
def test_non_authoritative_wrong_element_score_decoys_are_ignored(
    marker: str,
) -> None:
    payload = _html().replace(
        '<span class="score-item">12,345</span>',
        (
            f'<div class="score-item {marker}">99,999</div>'
            '<span class="score-item">12,345</span>'
        ),
        1,
    )

    submission = _parse(payload)

    assert submission.overall_score.state is FieldState.OBSERVED
    assert submission.overall_score.normalized_value == "12345"
    assert submission.overall_score.alternatives == ()


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        (
            f'<a href="{STANDARD_PATH}">3DMark - Fire Strike</a>',
            f'<a href="{STANDARD_PATH}" href="{STANDARD_PATH}">3DMark - Fire Strike</a>',
        ),
        (
            f'<a href="{STANDARD_PATH}">3DMark - Fire Strike</a>',
            f'<a href="{STANDARD_PATH}" href="{STANDARD_PATH}_extreme">3DMark - Fire Strike</a>',
        ),
        (
            f'<a href="{STANDARD_PATH}">3DMark - Fire Strike</a>',
            f'<a href="{STANDARD_PATH}_extreme" href="{STANDARD_PATH}">3DMark - Fire Strike</a>',
        ),
        (
            f'<a href="{STANDARD_PATH}">3DMark - Fire Strike</a>',
            f'<a href="{STANDARD_PATH}" HREF="{STANDARD_PATH}_ultra">3DMark - Fire Strike</a>',
        ),
        (
            'id="submission-score-wrapper"',
            'id="submission-score-wrapper" ID="submission-score-wrapper"',
        ),
        (
            'class="score-wrapper"',
            'class="score-wrapper" CLASS="score-wrapper"',
        ),
    ],
    ids=("identical-href", "standard-extreme", "extreme-standard", "standard-ultra-case", "id", "class"),
)
def test_duplicate_structural_attributes_are_rejected(original: str, replacement: str) -> None:
    payload = _html().replace(original, replacement, 1)

    with pytest.raises(HWBOTFireStrikeParseError, match="duplicate HTML attribute"):
        _parse(payload)


def test_reordered_irrelevant_markup_preserves_parsed_semantics() -> None:
    first = _parse(_html(before="<aside>alpha</aside>", after="<footer>beta</footer>"))
    second = _parse(_html(before="<footer>beta</footer>", after="<aside>alpha</aside>"))

    assert first.submission_id == second.submission_id
    assert first.benchmark_id == second.benchmark_id
    assert first.overall_score.normalized_value == second.overall_score.normalized_value
    assert first.overall_score.field_locator == second.overall_score.field_locator
    assert first.overall_score.capture_sha256 != second.overall_score.capture_sha256


def test_malformed_required_html_structure_is_rejected() -> None:
    payload = _html().replace("</span>", "</div>", 1)

    with pytest.raises(HWBOTFireStrikeParseError, match="structure is malformed"):
        _parse(payload)


def test_score_item_on_wrong_element_is_rejected() -> None:
    payload = _html().replace(
        '<span class="score-item">12,345</span>',
        '<div class="score-item">12,345</div>',
    )

    with pytest.raises(HWBOTFireStrikeParseError, match="score structure"):
        _parse(payload)


def test_unicode_in_irrelevant_source_text_is_supported() -> None:
    submission = _parse(_html(after="<footer>Température — vérifiée ✓</footer>"))

    assert submission.overall_score.normalized_value == "12345"


def test_component_scores_are_explicitly_missing_with_source_scope() -> None:
    capture = _capture(_html())
    submission = parse_hwbot_fire_strike_submission(capture)

    for field in (
        submission.graphics_score,
        submission.physics_score,
        submission.combined_score,
    ):
        assert field.state is FieldState.MISSING
        assert field.raw_value is None
        assert field.normalized_value is None
        assert field.field_locator == "//*[@id='submission-score-wrapper']"
        assert field.native_submission_identifier == "1480001"
        assert field.capture_sha256 == capture.sha256


def test_parser_performs_no_filesystem_or_network_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture = _capture(FIXTURE.read_bytes())

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("acquisition attempted")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)

    submission = parse_hwbot_fire_strike_submission(capture)

    assert submission.native_submission_identifier == "1480001"
