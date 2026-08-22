"""Deterministic parser for one offline UL 3DMark Fire Strike result page."""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from .canonical import normalize_decimal
from .capture import CapturedSourceV1
from .evidence import FieldEvidenceV1, FieldState
from .fire_strike import FireStrikeSubmissionV1


_SOURCE = "source:ul-3dmark-results"
_MEDIA_TYPE = "text/html"
_ID = re.compile(r"^[1-9][0-9]*$")
_FS_PATH = re.compile(r"^/fs/([1-9][0-9]*)$")
_SCORE_PATTERN = r"(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?: [0-9]{3})+)"
_SCORE = re.compile(rf"^{_SCORE_PATTERN}$")
_FORMATTED_COMPONENT_SCORE = re.compile(
    rf"^(?:\r?\n[ \t]*\t[ \t]*)?(?P<score>{_SCORE_PATTERN}) "
    rf"(?:\r?\n[ \t]*\t[ \t]*)?$"
)
_VISIBILITY_PROPERTIES = frozenset({"display", "visibility", "opacity"})
_VISIBLE_DISPLAY_VALUES = frozenset(
    {
        "block",
        "contents",
        "flex",
        "flow-root",
        "grid",
        "inline",
        "inline-block",
        "inline-flex",
        "inline-grid",
        "list-item",
        "table",
        "table-cell",
        "table-row",
    }
)
_OPACITY_VALUE = re.compile(r"(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")
_OPACITY_ZERO = re.compile(r"(?:0+(?:\.0*)?|\.0+)")
_LABELS = ("Overall Score", "Graphics Score", "Physics Score", "Combined Score")
_COMPONENT_LOCATOR = (
    "//div[@class~='result-header-details-items']/div[@class~='column3']"
    "/div[@class~='result-header-details-additional-score']/dl"
)
_LOCATORS = {
    "Overall Score": "//div[@class~='result-header']/div[@class~='result-header-details']/div[@class~='result-header-details-header']/h1/span[@class~='result-header-score']/following-sibling::span[1]",
    "Graphics Score": f"{_COMPONENT_LOCATOR}[dt='Graphics Score']/dd",
    "Physics Score": f"{_COMPONENT_LOCATOR}[dt='Physics Score']/dd",
    "Combined Score": f"{_COMPONENT_LOCATOR}[dt='Combined Score']/dd",
}
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})


class UL3DMarkFireStrikeParseError(ValueError):
    """The capture does not satisfy the supported UL result-page contract."""


@dataclass(slots=True)
class _ResultRoot:
    labels: list[str] = field(default_factory=list)
    badges: int = 0
    compare_paths: list[str] = field(default_factory=list)
    scores: dict[str, list[str]] = field(
        default_factory=lambda: {label: [] for label in _LABELS}
    )


@dataclass(slots=True)
class _SideBox:
    headings: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _Frame:
    tag: str
    attrs: dict[str, str]
    classes: frozenset[str]
    role: str | None
    hidden: bool
    root: _ResultRoot | None
    sidebox: _SideBox | None
    text: list[str] = field(default_factory=list)
    pending: tuple[str, bool] | None = None
    value_label: str | None = None
    score_suffix_span: bool = False


def _attributes(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for name, value in attrs:
        key = name.lower()
        if key in values: raise UL3DMarkFireStrikeParseError(f"duplicate HTML attribute: {key}")
        values[key] = value or ""
    return values


def _text(value: str) -> str:
    return " ".join(value.split())


def _score_text(value: str, label: str) -> tuple[str, str] | None:
    if not value:
        return None
    if _SCORE.fullmatch(value) is None:
        raise UL3DMarkFireStrikeParseError(f"{label.lower()} is malformed")
    try:
        return value, normalize_decimal(value.replace(" ", ""))
    except ValueError as error:
        raise UL3DMarkFireStrikeParseError(f"{label.lower()} is malformed") from error


def _component_score_text(
    value: str,
    label: str,
    *,
    has_suffix_span: bool,
) -> tuple[str, str] | None:
    if not value or (has_suffix_span and not value.strip(" \t\r\n\f")):
        return None
    if _SCORE.fullmatch(value) is not None:
        return _score_text(value, label)
    if has_suffix_span:
        match = _FORMATTED_COMPONENT_SCORE.fullmatch(value)
        if match is not None:
            return _score_text(match.group("score"), label)
    raise UL3DMarkFireStrikeParseError(f"{label.lower()} is malformed")


def _visibility_styles(value: str) -> dict[str, tuple[str, bool, int]]:
    result: dict[str, tuple[str, bool, int]] = {}
    for order, declaration in enumerate(value.split(";")):
        stripped = declaration.strip()
        if not stripped:
            continue
        if ":" not in stripped:
            first = stripped.split(None, 1)[0].casefold()
            if first in _VISIBILITY_PROPERTIES:
                raise UL3DMarkFireStrikeParseError("inline visibility style is malformed")
            continue
        name, setting = stripped.split(":", 1)
        name = name.strip().casefold()
        if name not in _VISIBILITY_PROPERTIES:
            continue

        setting = setting.strip()
        important_match = re.fullmatch(r"(.*?)!\s*important\s*", setting, re.IGNORECASE)
        if important_match is not None:
            setting = important_match.group(1).strip()
            important = True
        else:
            if "!" in setting:
                raise UL3DMarkFireStrikeParseError("inline visibility style is malformed")
            important = False
        normalized = setting.casefold()
        if not normalized:
            raise UL3DMarkFireStrikeParseError("inline visibility style is malformed")
        if name == "display" and normalized not in _VISIBLE_DISPLAY_VALUES | {"none"}:
            raise UL3DMarkFireStrikeParseError("inline display style is unsupported")
        if name == "visibility" and normalized not in {"hidden", "visible", "collapse"}:
            raise UL3DMarkFireStrikeParseError("inline visibility style is unsupported")
        if name == "opacity" and _OPACITY_VALUE.fullmatch(normalized) is None:
            raise UL3DMarkFireStrikeParseError("inline opacity style is unsupported")

        previous = result.get(name)
        if previous is None or important > previous[1] or important == previous[1]:
            result[name] = (normalized, important, order)
    return result


def _score_hidden(attrs: dict[str, str], classes: frozenset[str], *, result_root: bool) -> bool:
    style = _visibility_styles(attrs.get("style", ""))
    display = style.get("display", ("", False, -1))[0]
    visibility = style.get("visibility", ("", False, -1))[0]
    opacity = style.get("opacity", ("", False, -1))[0]
    if "hidden" in attrs or attrs.get("aria-hidden", "").strip().casefold() == "true": return True
    if display == "none" or visibility in {"hidden", "collapse"}: return True
    if _OPACITY_ZERO.fullmatch(opacity): return True
    if "hide" in classes or "hidden-score" in classes: return True
    if "hidden" in classes:
        return not (result_root and re.fullmatch(r"1(?:\.0+)?", opacity))
    return False


class _ULResultHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[_Frame] = []
        self.canonicals: list[str] = []
        self.roots: list[_ResultRoot] = []
        self.sideboxes: list[_SideBox] = []
        self.preset_links: list[tuple[_Frame, str]] = []
        self.preset_targets: list[tuple[_Frame, str]] = []
        self.structural_ids: dict[str, int] = {}

    def _inside(self, role: str) -> bool:
        return any(frame.role == role for frame in self.stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, tag in _VOID)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs, True)

    def _start(self, tag: str, attrs: list[tuple[str, str | None]], is_void: bool) -> None:
        values = _attributes(attrs)
        classes = frozenset(values.get("class", "").split())
        parent = self.stack[-1] if self.stack else None
        parent_role = parent.role if parent else None
        is_root = tag == "div" and "result-header" in classes and parent_role == "container"
        role: str | None = None
        root = _ResultRoot() if is_root else (parent.root if parent else None)
        sidebox = parent.sidebox if parent else None

        if parent and parent.pending is not None:
            label, pending_hidden = parent.pending
            parent.pending = None
            expected = "span" if parent.role == "overall_h1" else "dd"
            if tag != expected:
                if not pending_hidden:
                    raise UL3DMarkFireStrikeParseError(f"{label.lower()} structure is malformed")
            else:
                role = "score_value" if parent.role == "overall_h1" else "detail_value"

        if role is None:
            if tag == "head" and parent is not None and parent.tag == "html":
                role = "document_head"
            elif tag == "body":
                role = "body"
            elif tag == "div" and "container" in classes and parent_role == "body":
                role = "container"
            elif is_root:
                role = "result_root"
            elif tag == "h3" and "result-badge-header" in classes and parent_role == "result_root":
                role = "result_label"
            elif tag == "div" and "column3" in classes and parent_role == "result_root":
                role = "badge_column"
            elif tag == "div" and "result-badge" in classes and parent_role == "badge_column":
                role = "result_badge"
            elif tag == "div" and "result-header-details" in classes and parent_role == "result_root":
                role = "header_details"
            elif tag == "div" and "result-header-details-header" in classes and parent_role == "header_details":
                role = "header_top"
            elif tag == "h1" and parent_role == "header_top":
                role = "overall_h1"
            elif tag == "span" and "result-header-score" in classes and parent_role == "overall_h1":
                role = "overall_label"
            elif tag == "div" and "result-header-details-items" in classes and parent_role == "header_details":
                role = "score_items"
            elif tag == "div" and "column3" in classes and parent_role == "score_items":
                role = "score_column"
            elif tag == "div" and "result-header-details-additional-score" in classes and parent_role == "score_column":
                role = "additional_score"
            elif tag == "dl" and parent_role == "additional_score":
                role = "score_list"
            elif tag == "dt" and parent_role == "score_list":
                role = "score_term"
            elif tag == "div" and "mlr15" in classes and parent_role == "header_details":
                role = "compare_holder"
            elif tag == "a" and values.get("data-type") == "compare" and parent_role == "compare_holder":
                role = "compare_link"
            elif tag == "div" and "result-details" in classes and parent_role == "container":
                role = "result_details"
            elif tag == "div" and values.get("id") == "result-table" and self._inside("result_details"):
                role = "result_table"
            elif tag == "div" and "dataBox" in classes and parent_role == "result_table":
                role = "preset_box"
            elif tag == "h3" and parent_role == "preset_box":
                role = "preset_heading"
            elif tag == "div" and "result-details-side-box" in classes and parent and "result-details-side" in parent.classes:
                role, sidebox = "sidebox", _SideBox()
            elif tag == "div" and "benchmarklogo" in classes and parent_role == "sidebox":
                role = "side_logo"
            elif tag == "h3" and parent_role == "side_logo":
                role = "side_heading"
            elif tag == "div" and "dataBox" in classes and parent_role == "sidebox":
                role = "side_data"
            elif tag == "dl" and parent_role == "side_data":
                role = "side_list"
            elif tag == "dt" and parent_role == "side_list":
                role = "side_term"

        frame_hidden = (parent.hidden if parent else False) or _score_hidden(values, classes, result_root=is_root)
        frame = _Frame(tag, values, classes, role, frame_hidden, root, sidebox)
        if role in {"score_value", "detail_value"} and parent is not None:
            frame.value_label = label
        if parent is not None and parent.role == "detail_value" and parent.root is not None and tag == "span":
            parent.score_suffix_span = True

        structural_id = values.get("id", "")
        folded_id = structural_id.casefold()
        if folded_id.startswith(("scoreslinkfs-", "scoresfs-")):
            self.structural_ids[structural_id] = self.structural_ids.get(structural_id, 0) + 1
            if self.structural_ids[structural_id] > 1:
                raise UL3DMarkFireStrikeParseError(f"duplicate structural HTML id: {structural_id}")
        if (
            tag == "link"
            and parent_role == "document_head"
            and "canonical" in {item.casefold() for item in values.get("rel", "").split()}
        ):
            self.canonicals.append(values.get("href", ""))
        if tag == "a" and parent_role == "preset_heading" and folded_id.startswith("scoreslinkfs-"):
            self.preset_links.append((self.stack[-2], structural_id.removeprefix("scoresLinkfs-")))
        if tag == "div" and parent_role == "preset_box" and folded_id.startswith("scoresfs-"):
            self.preset_targets.append((parent, structural_id.removeprefix("scoresfs-")))

        if not is_void:
            self.stack.append(frame)
        else:
            self._finish(frame, parent)

    def handle_data(self, data: str) -> None:
        for frame in self.stack:
            frame.text.append(data)

    def handle_endtag(self, tag: str) -> None:
        matching = next((index for index in range(len(self.stack) - 1, -1, -1) if self.stack[index].tag == tag), None)
        if matching is None:
            return
        if any(frame.role is not None for frame in self.stack[matching + 1 :]):
            raise UL3DMarkFireStrikeParseError("required HTML structure is malformed")
        frame = self.stack[matching]
        parent = self.stack[matching - 1] if matching else None
        self._finish(frame, parent)
        del self.stack[matching:]

    def _finish(self, frame: _Frame, parent: _Frame | None) -> None:
        content = "".join(frame.text)
        if frame.role == "result_label" and frame.root is not None:
            frame.root.labels.append(_text(content))
        elif frame.role == "result_badge" and frame.root is not None and "test-fs" in frame.classes:
            frame.root.badges += 1
        elif frame.role == "overall_label" and parent is not None:
            if _text(content) != "Score":
                if not frame.hidden:
                    raise UL3DMarkFireStrikeParseError("overall score label is malformed")
            elif not frame.hidden:
                parent.pending = ("Overall Score", frame.hidden)
        elif frame.role == "score_term" and parent is not None:
            label = _text(content)
            if label in _LABELS[1:] and not frame.hidden:
                parent.pending = (label, frame.hidden)
        elif frame.role in {"score_value", "detail_value"} and frame.root is not None:
            if frame.hidden:
                parsed = None
            elif frame.role == "detail_value":
                parsed = _component_score_text(
                    content,
                    frame.value_label or "score",
                    has_suffix_span=frame.score_suffix_span,
                )
            else:
                parsed = _score_text(content, frame.value_label or "score")
            if parsed is not None:
                frame.root.scores[frame.value_label or ""].append(parsed[0])
        elif frame.role == "compare_link" and frame.root is not None:
            path = frame.attrs.get("data-compare-url", "")
            if path:
                frame.root.compare_paths.append(path)
        elif frame.role == "side_heading" and frame.sidebox is not None:
            frame.sidebox.headings.append(_text(content))
        elif frame.role == "side_term" and parent is not None and _text(content) == "ID":
            parent.pending = ("native result ID", False)
        elif frame.role == "detail_value" and frame.sidebox is not None and frame.value_label == "native result ID":
            frame.sidebox.identifiers.append(content)
        if frame.role == "result_root" and frame.root is not None:
            self.roots.append(frame.root)
        elif frame.role == "sidebox" and frame.sidebox is not None:
            self.sideboxes.append(frame.sidebox)

    def validate_complete(self) -> None:
        if any(frame.role is not None for frame in self.stack): raise UL3DMarkFireStrikeParseError("required HTML structure is malformed")


def _canonical_id(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise UL3DMarkFireStrikeParseError("canonical Fire Strike identity is malformed") from error
    match = _FS_PATH.fullmatch(parsed.path)
    invalid = parsed.scheme.casefold() not in {"http", "https"} or parsed.netloc.casefold() != "www.3dmark.com"
    if invalid or parsed.query or parsed.fragment or match is None:
        raise UL3DMarkFireStrikeParseError("canonical Fire Strike identity is malformed")
    return match.group(1)


def _native_id(value: str, label: str) -> str:
    if _ID.fullmatch(value) is None: raise UL3DMarkFireStrikeParseError(f"{label} must be a positive canonical ASCII decimal")
    return value


def _identity(parser: _ULResultHTMLParser) -> str:
    if not parser.canonicals: raise UL3DMarkFireStrikeParseError("canonical Fire Strike identity is missing")
    canonical_ids = {_canonical_id(value) for value in parser.canonicals}
    if len(canonical_ids) != 1:
        raise UL3DMarkFireStrikeParseError("canonical Fire Strike identities conflict")
    if not parser.sideboxes: raise UL3DMarkFireStrikeParseError("Fire Strike result side box is missing")
    body_values: list[str] = []
    for box in parser.sideboxes:
        if box.headings != ["Fire Strike"]:
            raise UL3DMarkFireStrikeParseError("result side-box benchmark identity conflicts")
        if not box.identifiers:
            raise UL3DMarkFireStrikeParseError("native result ID is missing")
        body_values.extend(box.identifiers)
    body_ids = {_native_id(value, "native result ID") for value in body_values}
    if len(body_ids) != 1:
        raise UL3DMarkFireStrikeParseError("native result IDs conflict")
    canonical_id = next(iter(canonical_ids))
    body_id = next(iter(body_ids))
    if canonical_id != body_id:
        raise UL3DMarkFireStrikeParseError("canonical and body native result IDs conflict")
    return body_id


def _authoritative_roots(parser: _ULResultHTMLParser, native_id: str) -> list[_ResultRoot]:
    preset_ok = (
        len(parser.preset_links) == len(parser.preset_targets) == 1
        and parser.preset_links[0][0] is parser.preset_targets[0][0]
        and parser.preset_links[0][1] == parser.preset_targets[0][1] == "P"
    )
    if not preset_ok:
        raise UL3DMarkFireStrikeParseError("Fire Strike Standard preset is missing or ambiguous")
    if not parser.roots:
        raise UL3DMarkFireStrikeParseError("Fire Strike result header is missing")
    for root in parser.roots:
        if root.labels != ["Fire Strike"] or root.badges != 1:
            raise UL3DMarkFireStrikeParseError("result-header benchmark identity conflicts")
        for value in root.compare_paths:
            match = _FS_PATH.fullmatch(value)
            if match is None:
                raise UL3DMarkFireStrikeParseError("compare Fire Strike identity is malformed")
            if match.group(1) != native_id:
                raise UL3DMarkFireStrikeParseError("compare Fire Strike identity conflicts")
    return parser.roots


def _field_value(capture: CapturedSourceV1, native_id: str, label: str, values: list[str]) -> FieldEvidenceV1:
    locator = _LOCATORS[label]
    observed = [(*(_score_text(value, label) or ()), index) for index, value in enumerate(values, 1)]
    distinct: dict[str, tuple[str, int]] = {}
    for raw, normalized, occurrence in observed:
        distinct.setdefault(normalized, (raw, occurrence))

    def evidence(state: FieldState, *, field_locator: str = locator, raw: str | None = None,
                 normalized: str | None = None,
                 alternatives: tuple[FieldEvidenceV1, ...] = ()) -> FieldEvidenceV1:
        return FieldEvidenceV1(
            state=state,
            source_identifier=_SOURCE,
            native_submission_identifier=native_id,
            capture_sha256=capture.sha256,
            field_locator=field_locator,
            raw_value=raw,
            normalized_value=normalized,
            unit="marks",
            alternatives=alternatives,
        )

    if not distinct:
        return evidence(FieldState.MISSING)
    if len(distinct) == 1:
        normalized, (raw, _) = next(iter(distinct.items()))
        return evidence(FieldState.OBSERVED, raw=raw, normalized=normalized)
    alternatives = tuple(
        evidence(
            FieldState.OBSERVED,
            field_locator=f"{locator}[{occurrence}]",
            raw=raw,
            normalized=normalized,
        )
        for normalized, (raw, occurrence) in distinct.items()
    )
    return evidence(FieldState.CONFLICTING, alternatives=alternatives)


def parse_ul_3dmark_fire_strike_submission(capture: CapturedSourceV1) -> FireStrikeSubmissionV1:
    """Parse an offline browser-saved UL Fire Strike Standard result page."""

    if not isinstance(capture, CapturedSourceV1):
        raise TypeError("UL 3DMark parser input must be CapturedSourceV1")
    if capture.source_identifier != _SOURCE:
        raise UL3DMarkFireStrikeParseError("capture source identifier must be source:ul-3dmark-results")
    if capture.media_type != _MEDIA_TYPE:
        raise UL3DMarkFireStrikeParseError("capture media type must be text/html")
    try:
        text = capture.payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise UL3DMarkFireStrikeParseError("UL 3DMark capture must be valid UTF-8") from error

    parser = _ULResultHTMLParser()
    parser.feed(text)
    parser.close()
    parser.validate_complete()
    native_id = _identity(parser)
    roots = _authoritative_roots(parser, native_id)
    values = {
        label: [value for root in roots for value in root.scores[label]]
        for label in _LABELS
    }
    return FireStrikeSubmissionV1(
        source_identifier=_SOURCE,
        native_submission_identifier=native_id,
        overall_score=_field_value(capture, native_id, "Overall Score", values["Overall Score"]),
        graphics_score=_field_value(capture, native_id, "Graphics Score", values["Graphics Score"]),
        physics_score=_field_value(capture, native_id, "Physics Score", values["Physics Score"]),
        combined_score=_field_value(capture, native_id, "Combined Score", values["Combined Score"]),
    )
