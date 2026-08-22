from __future__ import annotations

import builtins
from pathlib import Path
import re
import socket

import pytest

from moughorai.domains.benchmark import (
    FIRE_STRIKE_STANDARD_BENCHMARK_ID,
    CapturedSourceV1,
    FieldState,
    UL3DMarkFireStrikeParseError,
    parse_ul_3dmark_fire_strike_submission,
)


FIXTURE = Path(__file__).parent / "fixtures" / "benchmark_intelligence" / "ul_3dmark_fire_strike_result_v1.html"
SOURCE = "source:ul-3dmark-results"
NATIVE_ID = "90000001"
SCORES = {
    "overall": ("Overall Score", "12 345", "12345"),
    "graphics": ("Graphics Score", "13 579", "13579"),
    "physics": ("Physics Score", "24 680", "24680"),
    "combined": ("Combined Score", "6 789", "6789"),
}


def _html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _capture(
    payload: str | bytes,
    *,
    source_identifier: str | None = SOURCE,
    media_type: str | None = "text/html",
) -> CapturedSourceV1:
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return CapturedSourceV1(data, source_identifier=source_identifier, media_type=media_type)


def _parse(payload: str, **metadata: str | None):
    return parse_ul_3dmark_fire_strike_submission(_capture(payload, **metadata))


def _replace(payload: str, old: str, new: str) -> str:
    assert payload.count(old) == 1, old
    return payload.replace(old, new, 1)


def _field(submission, name: str):
    return getattr(submission, f"{name}_score")


def _set_score(payload: str, name: str, value: str) -> str:
    _, raw, _ = SCORES[name]
    if name == "overall":
        return _replace(payload, f"<span>{raw}</span>", f"<span>{value}</span>")
    return _replace(payload, f">{raw} <span>", f">{value} <span>")


def _component_pattern(label: str) -> re.Pattern[str]:
    return re.compile(
        r'\s*<div class="column3"><div class="dataBox '
        r'result-header-details-additional-score clearfix"><dl>\s*'
        rf"<dt>{re.escape(label)}</dt><dd>.*?</dd>\s*</dl></div></div>",
        re.DOTALL,
    )


def _component(label: str, value: str, extra: str = "") -> str:
    classes = "dataBox result-header-details-additional-score clearfix"
    if extra == ' class="hide"':
        classes += " hide"
        extra = ""
    return (
        f'<div class="column3"><div class="{classes}"{extra}><dl>'
        f"<dt>{label}</dt><dd>{value}<span></span></dd>"
        "</dl></div></div>"
    )


def _drop_score(payload: str, name: str) -> str:
    label, raw, _ = SCORES[name]
    if name == "overall":
        pair = f'<span class="result-header-score">Score</span><span>{raw}</span>'
        return _replace(payload, pair, "")
    result, count = _component_pattern(label).subn("", payload, count=1)
    assert count == 1
    return result


def _duplicate_score(payload: str, name: str, value: str) -> str:
    label, raw, _ = SCORES[name]
    if name == "overall":
        pair = f'<span class="result-header-score">Score</span><span>{raw}</span>'
        duplicate = f'<span class="result-header-score">Score</span><span>{value}</span>'
        return _replace(payload, pair, pair + duplicate)
    pattern = _component_pattern(label)
    match = pattern.search(payload)
    assert match is not None
    return payload[: match.end()] + _component(label, value) + payload[match.end() :]


def test_valid_standard_fixture_populates_existing_submission_model() -> None:
    capture = _capture(FIXTURE.read_bytes())
    result = parse_ul_3dmark_fire_strike_submission(capture)

    assert result.benchmark_id == FIRE_STRIKE_STANDARD_BENCHMARK_ID
    assert result.source_identifier == SOURCE
    assert result.native_submission_identifier == NATIVE_ID
    assert result.submission_id == f"submission:{SOURCE}:{NATIVE_ID}"
    assert {
        name: (_field(result, name).raw_value, _field(result, name).normalized_value)
        for name in SCORES
    } == {name: (raw, normalized) for name, (_, raw, normalized) in SCORES.items()}
    assert all(_field(result, name).unit == "marks" for name in SCORES)


def test_repeated_parsing_and_canonical_output_are_stable() -> None:
    capture = _capture(FIXTURE.read_bytes())
    first = parse_ul_3dmark_fire_strike_submission(capture)
    second = parse_ul_3dmark_fire_strike_submission(capture)

    assert first == second
    assert first.to_bytes() == second.to_bytes()
    assert first.canonical_sha256 == second.canonical_sha256


def test_every_score_and_conflict_alternative_retains_capture_sha256() -> None:
    capture = _capture(_duplicate_score(_html(), "graphics", "13 580"))
    result = parse_ul_3dmark_fire_strike_submission(capture)
    fields = tuple(_field(result, name) for name in SCORES)
    alternatives = tuple(item for field in fields for item in field.alternatives)

    assert all(item.capture_sha256 == capture.sha256 for item in (*fields, *alternatives))
    assert all(item.source_identifier == SOURCE for item in (*fields, *alternatives))
    assert all(item.native_submission_identifier == NATIVE_ID for item in (*fields, *alternatives))


@pytest.mark.parametrize("source_identifier", [None, "source:hwbot", "source:ul-3dmark"])
def test_missing_or_wrong_source_is_rejected(source_identifier: str | None) -> None:
    with pytest.raises(UL3DMarkFireStrikeParseError, match="source identifier"):
        _parse(_html(), source_identifier=source_identifier)


@pytest.mark.parametrize("media_type", [None, "application/xhtml+xml", "application/json"])
def test_missing_or_wrong_media_type_is_rejected(media_type: str | None) -> None:
    with pytest.raises(UL3DMarkFireStrikeParseError, match="media type"):
        _parse(_html(), media_type=media_type)


def test_invalid_utf8_is_rejected_before_html_interpretation() -> None:
    with pytest.raises(UL3DMarkFireStrikeParseError, match="valid UTF-8"):
        parse_ul_3dmark_fire_strike_submission(_capture(b"\xff\xfe"))


def test_canonical_body_and_optional_compare_identifiers_agree() -> None:
    result = _parse(_html())
    assert result.native_submission_identifier == NATIVE_ID


def test_optional_compare_structure_may_be_absent() -> None:
    payload = _replace(_html(), ' data-compare-url="/fs/90000001"', "")
    assert _parse(payload).native_submission_identifier == NATIVE_ID


def test_browser_run_locator_is_never_native_identity() -> None:
    payload = _replace(
        _html(),
        "<head>",
        "<head><!-- saved from url=(0036)https://www.3dmark.com/3dm/161404206 -->",
    )
    payload = _replace(payload, "<body>", '<body><script>const run="/3dm/161404206";</script>')

    assert _parse(payload).native_submission_identifier == NATIVE_ID


def test_equivalent_duplicate_canonical_and_body_ids_corroborate() -> None:
    payload = _replace(
        _html(),
        '<link rel="canonical" href="https://www.3dmark.com/fs/90000001">',
        '<link rel="canonical" href="https://www.3dmark.com/fs/90000001">'
        '<link rel="canonical" href="http://www.3dmark.com/fs/90000001">',
    )
    payload = _replace(payload, "<dt>ID</dt><dd>90000001</dd>", "<dt>ID</dt><dd>90000001</dd><dt>ID</dt><dd>90000001</dd>")

    assert _parse(payload).native_submission_identifier == NATIVE_ID


def test_missing_canonical_identity_is_rejected() -> None:
    payload = _replace(_html(), '<link rel="canonical" href="https://www.3dmark.com/fs/90000001">', "")
    with pytest.raises(UL3DMarkFireStrikeParseError, match="canonical.*missing"):
        _parse(payload)


@pytest.mark.parametrize(
    "href",
    [
        "/fs/90000001",
        "https://www.3dmark.com/fs/result",
        "https://www.3dmark.com/3dm/161404206",
        "https://example.com/fs/90000001",
        "https://www.3dmark.com/fs/090000001",
        "https://www.3dmark.com/fs/0",
        "https://www.3dmark.com/fs/90000001?score=99999",
    ],
)
def test_malformed_canonical_identity_is_rejected(href: str) -> None:
    payload = _replace(_html(), "https://www.3dmark.com/fs/90000001", href)
    with pytest.raises(UL3DMarkFireStrikeParseError, match="canonical.*malformed"):
        _parse(payload)


def test_missing_body_identity_is_rejected() -> None:
    payload = _replace(_html(), "<dt>ID</dt><dd>90000001</dd>", "")
    with pytest.raises(UL3DMarkFireStrikeParseError, match="native result ID is missing"):
        _parse(payload)


@pytest.mark.parametrize("identifier", ["result", "٩٠٠٠٠٠٠١", "090000001", "0", "+90000001"])
def test_malformed_or_noncanonical_body_identity_is_rejected(identifier: str) -> None:
    payload = _replace(_html(), "<dd>90000001</dd>", f"<dd>{identifier}</dd>")
    with pytest.raises(UL3DMarkFireStrikeParseError, match="positive canonical ASCII decimal"):
        _parse(payload)


def test_conflicting_canonical_and_body_ids_are_rejected() -> None:
    payload = _replace(_html(), "<dt>ID</dt><dd>90000001</dd>", "<dt>ID</dt><dd>90000002</dd>")
    with pytest.raises(UL3DMarkFireStrikeParseError, match="canonical and body"):
        _parse(payload)


def test_conflicting_body_ids_are_rejected() -> None:
    payload = _replace(_html(), "<dt>ID</dt><dd>90000001</dd>", "<dt>ID</dt><dd>90000001</dd><dt>ID</dt><dd>90000002</dd>")
    with pytest.raises(UL3DMarkFireStrikeParseError, match="native result IDs conflict"):
        _parse(payload)


def test_conflicting_canonical_links_are_rejected() -> None:
    payload = _replace(
        _html(),
        '<link rel="canonical" href="https://www.3dmark.com/fs/90000001">',
        '<link rel="canonical" href="https://www.3dmark.com/fs/90000001">'
        '<link rel="canonical" href="https://www.3dmark.com/fs/90000002">',
    )
    with pytest.raises(UL3DMarkFireStrikeParseError, match="canonical.*conflict"):
        _parse(payload)


def test_conflicting_optional_compare_identity_is_rejected() -> None:
    payload = _replace(_html(), 'data-compare-url="/fs/90000001"', 'data-compare-url="/fs/90000002"')
    with pytest.raises(UL3DMarkFireStrikeParseError, match="compare.*conflict"):
        _parse(payload)


def test_malformed_optional_compare_identity_is_rejected() -> None:
    payload = _replace(_html(), 'data-compare-url="/fs/90000001"', 'data-compare-url="/3dm/161404206"')
    with pytest.raises(UL3DMarkFireStrikeParseError, match="compare.*malformed"):
        _parse(payload)


@pytest.mark.parametrize("token", ["X", "R", "C", "PST", "Z"])
def test_nonstandard_or_unknown_preset_is_rejected(token: str) -> None:
    payload = _html().replace("scoresLinkfs-P", f"scoresLinkfs-{token}").replace("scoresfs-P", f"scoresfs-{token}")
    with pytest.raises(UL3DMarkFireStrikeParseError, match="Standard preset"):
        _parse(payload)


def test_missing_standard_preset_is_rejected() -> None:
    payload = _html().replace("scoresLinkfs-P", "details-link").replace("scoresfs-P", "details-target")
    with pytest.raises(UL3DMarkFireStrikeParseError, match="Standard preset"):
        _parse(payload)


@pytest.mark.parametrize("structural_id", ["scoresLinkfs-P", "scoresfs-P"])
def test_duplicated_standard_structure_is_rejected(structural_id: str) -> None:
    if structural_id == "scoresLinkfs-P":
        original = '<a id="scoresLinkfs-P" href="javascript:;">Detailed scores</a>'
        duplicate = '<a id="scoresLinkfs-P" href="javascript:;">Duplicate</a>'
    else:
        original = '<div id="scoresfs-P"></div>'
        duplicate = '<div id="scoresfs-P"></div>'
    payload = _replace(_html(), original, original + duplicate)
    with pytest.raises(UL3DMarkFireStrikeParseError, match="duplicate structural HTML id"):
        _parse(payload)


def test_ambiguous_standard_and_extreme_presets_are_rejected() -> None:
    payload = _replace(
        _html(),
        '<a id="scoresLinkfs-P" href="javascript:;">',
        '<a id="scoresLinkfs-X" href="javascript:;"></a><a id="scoresLinkfs-P" href="javascript:;">',
    )
    with pytest.raises(UL3DMarkFireStrikeParseError, match="Standard preset"):
        _parse(payload)


def test_standard_link_and_target_must_belong_to_the_same_structure() -> None:
    payload = _replace(
        _html(),
        '<div id="scoresfs-P"></div>',
        '</div><div class="dataBox"><div id="scoresfs-P"></div>',
    )
    with pytest.raises(UL3DMarkFireStrikeParseError, match="Standard preset"):
        _parse(payload)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('<h3 class="result-badge-header">Fire Strike</h3>', '<h3 class="result-badge-header">Fire Strike Extreme</h3>'),
        ('class="result-badge test-fs"', 'class="result-badge test-fse"'),
        ('<div class="benchmarklogo"><h3>Fire Strike</h3>', '<div class="benchmarklogo"><h3>Fire Strike Ultra</h3>'),
    ],
)
def test_contradictory_benchmark_evidence_is_rejected(old: str, new: str) -> None:
    with pytest.raises(UL3DMarkFireStrikeParseError, match="identity conflicts"):
        _parse(_replace(_html(), old, new))


@pytest.mark.parametrize("name", tuple(SCORES))
def test_each_score_is_observed_only_from_its_authority(name: str) -> None:
    result = _parse(_html())
    _, raw, normalized = SCORES[name]
    evidence = _field(result, name)

    assert evidence.state is FieldState.OBSERVED
    assert evidence.raw_value == raw
    assert evidence.normalized_value == normalized
    assert evidence.field_locator.startswith("//")


@pytest.mark.parametrize("name", tuple(SCORES))
def test_each_score_is_independently_missing(name: str) -> None:
    result = _parse(_drop_score(_html(), name))
    evidence = _field(result, name)

    assert evidence.state is FieldState.MISSING
    assert evidence.raw_value is None
    assert evidence.normalized_value is None
    assert all(_field(result, other).state is FieldState.OBSERVED for other in SCORES if other != name)


@pytest.mark.parametrize("name", tuple(SCORES))
def test_zero_is_valid_for_every_score(name: str) -> None:
    evidence = _field(_parse(_set_score(_html(), name, "0")), name)
    assert evidence.state is FieldState.OBSERVED
    assert evidence.normalized_value == "0"


@pytest.mark.parametrize("name", tuple(SCORES))
@pytest.mark.parametrize("value", ["01", "+123", "-1", "1e3", "NaN", "12,345", "12.345", "12\u00a0345", "12\u202f345"])
def test_malformed_or_unapproved_localized_scores_are_rejected(name: str, value: str) -> None:
    with pytest.raises(UL3DMarkFireStrikeParseError, match="malformed"):
        _parse(_set_score(_html(), name, value))


@pytest.mark.parametrize("name", tuple(SCORES))
def test_equivalent_authoritative_scores_collapse(name: str) -> None:
    _, raw, normalized = SCORES[name]
    duplicate = raw.replace(" ", "")
    field = _field(_parse(_duplicate_score(_html(), name, duplicate)), name)

    assert field.state is FieldState.OBSERVED
    assert field.normalized_value == normalized
    assert field.alternatives == ()


@pytest.mark.parametrize("name", tuple(SCORES))
def test_conflicting_authoritative_scores_are_deterministic(name: str) -> None:
    field = _field(_parse(_duplicate_score(_html(), name, "99 999")), name)

    assert field.state is FieldState.CONFLICTING
    assert field.raw_value is None
    assert field.normalized_value is None
    assert [item.normalized_value for item in field.alternatives] == sorted(
        {SCORES[name][2], "99999"}
    )
    assert len({item.field_locator for item in field.alternatives}) == 2


DECOYS = (
    '<meta property="og:title" content="I scored 99 999 in Fire Strike">',
    '<meta property="og:message" content="Just ran Fire Strike and scored 99 999">',
    '<script>const overallScore=99999; share(99999);</script>',
    '<script>fetch("/histogram/P?score=99999")</script>',
    '<div class="result-context-row"><span class="result-context-bar-score">99999</span></div>',
    '<div id="your-score-row"><span class="result-context-bar-score">99999</span></div>',
    '<div id="compare-widget"><a class="compare-score">99 999</a></div>',
    '<div id="scoresfs-P-decoy"><dt>Graphics Score</dt><dd>99 999</dd></div>',
    '<dl><dt>GPU Clock frequency</dt><dd>99 999 MHz</dd></dl>',
    '<dl><dt>Memory clock frequency</dt><dd>99 999 MHz</dd></dl>',
    '<dl><dt>CPU Clock frequency</dt><dd>99 999 MHz</dd></dl>',
    '<dl><dt>Memory</dt><dd>99 999 MB</dd></dl>',
    '<dl><dt>Date</dt><dd>99 999</dd><dt>Test Version</dt><dd>99 999</dd></dl>',
    '<dl><dt>ID</dt><dd>99999</dd></dl>',
    '<!-- saved from url=https://www.3dmark.com/3dm/99999 -->',
)


@pytest.mark.parametrize("decoy", DECOYS)
def test_real_page_numeric_decoys_never_become_score_evidence(decoy: str) -> None:
    payload = _replace(_html(), "<body>", f"<body>{decoy}")
    result = _parse(payload)

    assert {name: _field(result, name).normalized_value for name in SCORES} == {
        name: expected for name, (_, _, expected) in SCORES.items()
    }


def test_lazy_detailed_score_decoy_inside_standard_target_is_ignored() -> None:
    payload = _replace(
        _html(),
        '<div id="scoresfs-P"></div>',
        '<div id="scoresfs-P"><div class="result-header-details-additional-score">'
        '<dl><dt>Graphics Score</dt><dd>99 999</dd></dl></div></div>',
    )
    assert _parse(payload).graphics_score.normalized_value == "13579"


def test_repeated_generic_result_table_id_outside_standard_scope_is_ignored() -> None:
    decoy = '<div class="result-details"><div id="result-table"><span>99 999</span></div></div>'
    payload = _replace(_html(), "</body>", decoy + "</body>")
    assert _parse(payload).overall_score.normalized_value == "12345"


@pytest.mark.parametrize(
    "extra",
    [
        " hidden",
        ' aria-hidden="true"',
        ' style="display:none"',
        ' style="visibility:hidden"',
        ' style="opacity:0"',
        ' class="hide"',
    ],
)
def test_hidden_component_candidate_is_excluded_before_conflict(extra: str) -> None:
    label = "Graphics Score"
    pattern = _component_pattern(label)
    match = pattern.search(_html())
    assert match is not None
    payload = _html()[: match.start()] + _component(label, "99 999", extra) + _html()[match.start() :]

    assert _parse(payload).graphics_score.normalized_value == "13579"


@pytest.mark.parametrize(
    "attributes",
    ["hidden", 'aria-hidden="true"', 'style="display:none"', 'style="visibility:hidden"', 'style="opacity:0"'],
)
def test_hidden_overall_candidate_is_excluded(attributes: str) -> None:
    real = '<span class="result-header-score">Score</span><span>12 345</span>'
    decoy = f'<span class="result-header-score" {attributes}>Score</span><span {attributes}>99 999</span>'
    result = _parse(_replace(_html(), real, decoy + real))
    assert result.overall_score.normalized_value == "12345"


def test_nested_hidden_score_decoy_is_not_authoritative() -> None:
    marker = '<div class="result-header-details-items clearfix">'
    decoy = '<section hidden>' + _component("Graphics Score", "99 999") + "</section>"
    result = _parse(_replace(_html(), marker, marker + decoy))
    assert result.graphics_score.normalized_value == "13579"


def test_observed_root_animation_hidden_class_with_opacity_one_is_authoritative() -> None:
    assert _parse(_html()).overall_score.normalized_value == "12345"


def test_root_with_effective_opacity_zero_has_missing_scores() -> None:
    payload = _replace(_html(), 'style="opacity: 1; left: 0px;"', 'style="opacity: 0; left: 0px;"')
    result = _parse(payload)
    assert all(_field(result, name).state is FieldState.MISSING for name in SCORES)


def test_invalidity_notice_does_not_reject_presented_scores() -> None:
    notice = '<div class="notice">Result invalid: tessellation settings modified.</div>'
    result = _parse(_replace(_html(), '<div class="result-header-details column3-2">', '<div class="result-header-details column3-2">' + notice))
    assert result.overall_score.normalized_value == "12345"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("<span>12 345</span>", "<div>12 345</div>"),
        ("<dt>Graphics Score</dt><dd>", "<dt>Graphics Score</dt><span>"),
    ],
)
def test_wrong_authoritative_value_element_is_rejected(old: str, new: str) -> None:
    with pytest.raises(UL3DMarkFireStrikeParseError, match="structure is malformed"):
        _parse(_replace(_html(), old, new))


def test_extra_wrapper_prevents_component_authority() -> None:
    pattern = _component_pattern("Graphics Score")
    match = pattern.search(_html())
    assert match is not None
    wrapped = match.group().replace('<div class="column3">', '<div class="column3"><section>', 1)
    wrapped = wrapped.rsplit("</div></div>", 1)[0] + "</div></section></div>"
    payload = _html()[: match.start()] + wrapped + _html()[match.end() :]
    assert _parse(payload).graphics_score.state is FieldState.MISSING


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('<div class="result-header-details column3-2">', '<br><div class="result-header-details column3-2">'),
        ('<div class="result-header-details-items clearfix">', '<input><div class="result-header-details-items clearfix">'),
        ('<div class="column3"><div class="dataBox result-header-details-additional-score clearfix"><dl>\n            <dt>Graphics Score</dt>', '<hr><div class="column3"><div class="dataBox result-header-details-additional-score clearfix"><dl>\n            <dt>Graphics Score</dt>'),
        ('<dt>Graphics Score</dt><dd>', '<meta name="decoy"><dt>Graphics Score</dt><dd>'),
    ],
)
def test_void_siblings_do_not_change_direct_parentage(old: str, new: str) -> None:
    assert _parse(_replace(_html(), old, new)).graphics_score.normalized_value == "13579"


def test_reordered_irrelevant_markup_preserves_canonical_result() -> None:
    decoy = '<aside><span>99 999</span><script>const score=88888;</script></aside>'
    baseline = _parse(_html())
    before = _parse(_replace(_html(), '<div class="result-header clearfix', decoy + '<div class="result-header clearfix'))
    after = _parse(_replace(_html(), "</body>", decoy + "</body>"))

    def summary(result):
        return (
            result.benchmark_id,
            result.native_submission_identifier,
            tuple((_field(result, name).state, _field(result, name).raw_value,
                   _field(result, name).normalized_value, _field(result, name).field_locator)
                  for name in SCORES),
        )

    assert summary(baseline) == summary(before) == summary(after)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('rel="canonical"', 'rel="canonical" REL="canonical"'),
        ('href="https://www.3dmark.com/fs/90000001"', 'href="https://www.3dmark.com/fs/90000001" HREF="https://www.3dmark.com/fs/90000001"'),
        ('id="scoresLinkfs-P"', 'id="scoresLinkfs-P" ID="scoresLinkfs-P"'),
        ('class="result-header clearfix mb0 hidden"', 'class="result-header clearfix mb0 hidden" CLASS="result-header clearfix mb0 hidden"'),
        ('style="opacity: 1; left: 0px;"', 'style="opacity: 1; left: 0px;" STYLE="opacity: 1; left: 0px;"'),
        ('<dt>Graphics Score</dt>', '<dt aria-hidden="false" ARIA-HIDDEN="false">Graphics Score</dt>'),
        ('data-compare-url="/fs/90000001"', 'data-compare-url="/fs/90000001" DATA-COMPARE-URL="/fs/90000001"'),
        ('rel="canonical"', 'REL="alternate" rel="canonical"'),
        ('href="https://www.3dmark.com/fs/90000001"', 'HREF="https://www.3dmark.com/fs/90000002" href="https://www.3dmark.com/fs/90000001"'),
        ('id="scoresLinkfs-P"', 'ID="scoresLinkfs-X" id="scoresLinkfs-P"'),
        ('class="result-header clearfix mb0 hidden"', 'CLASS="decoy" class="result-header clearfix mb0 hidden"'),
        ('style="opacity: 1; left: 0px;"', 'STYLE="opacity:0" style="opacity: 1; left: 0px;"'),
        ('<dt>Graphics Score</dt>', '<dt ARIA-HIDDEN="true" aria-hidden="false">Graphics Score</dt>'),
        ('data-compare-url="/fs/90000001"', 'DATA-COMPARE-URL="/fs/90000002" data-compare-url="/fs/90000001"'),
    ],
)
def test_duplicate_structural_attributes_are_rejected_regardless_of_values_or_order(old: str, new: str) -> None:
    with pytest.raises(UL3DMarkFireStrikeParseError, match="duplicate HTML attribute"):
        _parse(_replace(_html(), old, new))


def test_unclosed_authoritative_structure_is_rejected() -> None:
    payload = _replace(_html(), "</h1>", "")
    with pytest.raises(UL3DMarkFireStrikeParseError, match="required HTML structure"):
        _parse(payload)


def test_unicode_in_irrelevant_text_is_supported() -> None:
    payload = _replace(_html(), "<body>", "<body><p>Unicode decoy: 火🔥é</p>")
    assert _parse(payload).overall_score.normalized_value == "12345"


def test_parser_performs_no_filesystem_or_network_acquisition(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = _capture(FIXTURE.read_bytes())

    def forbidden(*_args, **_kwargs):
        raise AssertionError("parser attempted external acquisition")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)

    result = parse_ul_3dmark_fire_strike_submission(capture)
    assert result.native_submission_identifier == NATIVE_ID


def test_six_blocker_authoritative_head_canonical_is_accepted() -> None:
    assert _parse(_html()).native_submission_identifier == NATIVE_ID


def test_six_blocker_body_only_canonical_is_rejected() -> None:
    canonical = '<link rel="canonical" href="https://www.3dmark.com/fs/90000001">'
    payload = _replace(_html(), canonical, "")
    payload = _replace(payload, "<body>", f"<body>{canonical}")
    with pytest.raises(UL3DMarkFireStrikeParseError, match="canonical.*missing"):
        _parse(payload)


@pytest.mark.parametrize("body_id", ["90000001", "90000002"])
def test_six_blocker_body_canonical_decoy_never_overrides_head(body_id: str) -> None:
    decoy = f'<link rel="canonical" href="https://www.3dmark.com/fs/{body_id}">'
    payload = _replace(_html(), "<body>", f"<body>{decoy}")
    assert _parse(payload).native_submission_identifier == NATIVE_ID


def test_six_blocker_duplicate_identical_head_canonicals_corroborate() -> None:
    canonical = '<link rel="canonical" href="https://www.3dmark.com/fs/90000001">'
    payload = _replace(_html(), canonical, canonical + canonical)
    assert _parse(payload).native_submission_identifier == NATIVE_ID


def test_six_blocker_conflicting_head_canonicals_fail() -> None:
    canonical = '<link rel="canonical" href="https://www.3dmark.com/fs/90000001">'
    conflict = '<link rel="canonical" href="https://www.3dmark.com/fs/90000002">'
    payload = _replace(_html(), canonical, canonical + conflict)
    with pytest.raises(UL3DMarkFireStrikeParseError, match="canonical.*conflict"):
        _parse(payload)


def test_six_blocker_exact_body_id_and_split_data_callbacks_are_accepted() -> None:
    split = _replace(_html(), "<dd>90000001</dd>", "<dd>9000<!-- split -->0001</dd>")
    assert _parse(_html()).native_submission_identifier == NATIVE_ID
    assert _parse(split).native_submission_identifier == NATIVE_ID


@pytest.mark.parametrize(
    "identifier",
    [
        " 90000001",
        "90000001 ",
        "90 000 001",
        "\t90000001",
        "90000001\n",
        "+90000001",
        "-90000001",
        "090000001",
        "٠١٢٣",
        "９００００００１",
    ],
)
def test_six_blocker_noncanonical_body_id_lexical_forms_fail(identifier: str) -> None:
    payload = _replace(_html(), "<dd>90000001</dd>", f"<dd>{identifier}</dd>")
    with pytest.raises(UL3DMarkFireStrikeParseError, match="positive canonical ASCII decimal"):
        _parse(payload)


@pytest.mark.parametrize(
    ("name", "old", "new"),
    [
        (
            "overall",
            '<span class="result-header-score">Score</span>',
            '<span class="result-header-score" hidden>Score</span>',
        ),
        ("graphics", "<dt>Graphics Score</dt>", "<dt hidden>Graphics Score</dt>"),
        ("physics", "<dt>Physics Score</dt>", '<dt style="display:none">Physics Score</dt>'),
        ("combined", "<dt>Combined Score</dt>", '<dt style="opacity:0">Combined Score</dt>'),
    ],
)
def test_six_blocker_hidden_label_cannot_authorize_visible_value(
    name: str,
    old: str,
    new: str,
) -> None:
    field = _field(_parse(_replace(_html(), old, new)), name)
    assert field.state is FieldState.MISSING
    assert field.alternatives == ()


@pytest.mark.parametrize("name", tuple(SCORES))
def test_six_blocker_hidden_label_never_adds_a_conflict_alternative(name: str) -> None:
    label, raw, normalized = SCORES[name]
    if name == "overall":
        real = f'<span class="result-header-score">Score</span><span>{raw}</span>'
        hidden = '<span class="result-header-score" hidden>Score</span><span>99 999</span>'
        payload = _replace(_html(), real, hidden + real)
    else:
        pattern = _component_pattern(label)
        match = pattern.search(_html())
        assert match is not None
        hidden = _component(label, "99 999").replace(f"<dt>{label}</dt>", f"<dt hidden>{label}</dt>")
        payload = _html()[: match.start()] + hidden + _html()[match.start() :]
    field = _field(_parse(payload), name)
    assert field.state is FieldState.OBSERVED
    assert field.normalized_value == normalized
    assert field.alternatives == ()


def test_six_blocker_root_animation_exception_remains_authoritative() -> None:
    assert _parse(_html()).overall_score.normalized_value == "12345"


def test_six_blocker_nested_hidden_opacity_one_overall_is_excluded() -> None:
    payload = _replace(
        _html(),
        "<span>12 345</span>",
        '<span class="hidden" style="opacity:1">12 345</span>',
    )
    assert _parse(payload).overall_score.state is FieldState.MISSING


@pytest.mark.parametrize("target", ["label", "value"])
def test_six_blocker_nested_hidden_opacity_one_component_is_excluded(target: str) -> None:
    if target == "label":
        payload = _replace(
            _html(),
            "<dt>Graphics Score</dt>",
            '<dt class="hidden" style="opacity:1">Graphics Score</dt>',
        )
    else:
        payload = _replace(
            _html(),
            "<dd>13 579 <span></span></dd>",
            '<dd class="hidden" style="opacity:1">13 579 <span></span></dd>',
        )
    assert _parse(payload).graphics_score.state is FieldState.MISSING


@pytest.mark.parametrize(
    ("style", "state"),
    [
        ("display:none!important; display:inline", FieldState.MISSING),
        ("display:inline!important; display:none", FieldState.OBSERVED),
        ("display:none!important; display:inline!important", FieldState.OBSERVED),
        ("display:inline!important; display:none!important", FieldState.MISSING),
        ("visibility:hidden!important; visibility:visible", FieldState.MISSING),
        ("visibility:visible!important; visibility:hidden", FieldState.OBSERVED),
        ("visibility:hidden!important; visibility:visible!important", FieldState.OBSERVED),
        ("visibility:visible!important; visibility:hidden!important", FieldState.MISSING),
        ("opacity:0!important; opacity:1", FieldState.MISSING),
        ("opacity:1!important; opacity:0", FieldState.OBSERVED),
        ("opacity:0!important; opacity:1!important", FieldState.OBSERVED),
        ("opacity:1!important; opacity:0!important", FieldState.MISSING),
    ],
)
def test_six_blocker_inline_visibility_important_precedence(
    style: str,
    state: FieldState,
) -> None:
    payload = _replace(_html(), "<span>12 345</span>", f'<span style="{style}">12 345</span>')
    field = _parse(payload).overall_score
    assert field.state is state
    assert field.normalized_value == ("12345" if state is FieldState.OBSERVED else None)


def test_six_blocker_malformed_important_visibility_fails() -> None:
    payload = _replace(
        _html(),
        "<span>12 345</span>",
        '<span style="display:none!urgent">12 345</span>',
    )
    with pytest.raises(UL3DMarkFireStrikeParseError, match="visibility style is malformed"):
        _parse(payload)


@pytest.mark.parametrize("name", tuple(SCORES))
@pytest.mark.parametrize("raw", ["0", "12345", "12 345"])
def test_six_blocker_supported_score_lexical_forms_preserve_raw(name: str, raw: str) -> None:
    field = _field(_parse(_set_score(_html(), name, raw)), name)
    assert field.state is FieldState.OBSERVED
    assert field.raw_value == raw
    assert field.normalized_value == raw.replace(" ", "")


@pytest.mark.parametrize("name", tuple(SCORES))
@pytest.mark.parametrize(
    "raw",
    [
        " 12 345",
        "12 345 ",
        "12   345",
        "12\t345",
        "12\n345",
        "12\u00a0345",
        "12\u202f345",
        "12,345",
        "12.345",
        "+12345",
        "-12345",
        "12345.0",
        "1e4",
        "１２３４５",
    ],
)
def test_six_blocker_malformed_score_lexical_forms_fail(name: str, raw: str) -> None:
    with pytest.raises(UL3DMarkFireStrikeParseError, match="malformed"):
        _parse(_set_score(_html(), name, raw))
