"""Deterministic parser for one offline HWBOT Fire Strike representation."""

from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from .canonical import normalize_decimal
from .capture import CapturedSourceV1
from .evidence import FieldEvidenceV1, FieldState
from .fire_strike import FireStrikeSubmissionV1


_SOURCE = "source:hwbot"
_MEDIA_TYPE = "text/html"
_BENCHMARK_PATH = "/benchmarks/3dmark_-_fire_strike"
_SUBMISSION_PREFIX = f"{_BENCHMARK_PATH}/submissions/"
_OVERALL_LOCATOR = "//*[@id='submission-score-wrapper']//span[@class='score-item']"
_SCORE_SCOPE_LOCATOR = "//*[@id='submission-score-wrapper']"
_SCORE_TEXT = re.compile(r"^(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)(?:\.[0-9]+)?$")
_RANKING_SCORE = re.compile(r"^(.+?)\s+marks$", re.IGNORECASE)
_USER_PATH = re.compile(r"^/users/[^/]+$")
_NON_AUTHORITATIVE_SCORE_CLASSES = frozenset(
    {"hidden", "suggestion", "wr-ranking-grid"}
)
_HTML_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_STANDARD_LABEL = re.compile(
    r"^(?:3dmark(?:\s*[-:]\s*|\s+))?fire\s+strike(?:\s+standard)?$",
    re.IGNORECASE,
)


class HWBOTFireStrikeParseError(ValueError):
    """The capture does not satisfy the supported HWBOT source contract."""


def _collapsed(value: str) -> str:
    return " ".join(value.split())


def _path(href: str) -> str:
    try:
        return urlsplit(href).path
    except ValueError:
        return ""


def _attributes(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for name, value in attrs:
        normalized = name.lower()
        if normalized in values:
            raise HWBOTFireStrikeParseError(f"duplicate HTML attribute: {normalized}")
        values[normalized] = value or ""
    return values


def _score(value: str, label: str) -> tuple[str, str]:
    raw = _collapsed(value)
    if _SCORE_TEXT.fullmatch(raw) is None:
        raise HWBOTFireStrikeParseError(f"{label} is malformed")
    try:
        return raw, normalize_decimal(raw.replace(",", ""))
    except ValueError as error:
        raise HWBOTFireStrikeParseError(f"{label} is malformed") from error


class _HWBOTHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.wrapper_depth: int | None = None
        self.wrapper_count = 0
        self.non_authoritative_score_depths: list[int] = []
        self.score_wrapper_depth: int | None = None
        self.value_depth: int | None = None
        self.user_depths: list[int] = []
        self.score_frame: tuple[int, list[str]] | None = None
        self.anchor_frame: tuple[int, str, bool, bool, list[str]] | None = None
        self.ranking_row: tuple[int, list[tuple[str, str]]] | None = None
        self.benchmark_anchors: list[tuple[str, str]] = []
        self.header_users: set[str] = set()
        self.ranking_rows: list[list[tuple[str, str]]] = []
        self.score_texts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = _attributes(attrs)
        classes = set(values.get("class", "").split())
        depth = len(self.tags)
        is_void = tag in _HTML_VOID_ELEMENTS
        excludes_score = "hidden" in values or not classes.isdisjoint(
            _NON_AUTHORITATIVE_SCORE_CLASSES
        )
        score_authoritative = (
            not self.non_authoritative_score_depths and not excludes_score
        )
        if excludes_score and not is_void:
            self.non_authoritative_score_depths.append(depth)
        if not is_void:
            self.tags.append(tag)

        if self.score_frame is not None:
            raise HWBOTFireStrikeParseError("overall score structure is malformed")

        if values.get("id") == "submission-score-wrapper":
            self.wrapper_count += 1
            if self.wrapper_count != 1 or tag != "div":
                raise HWBOTFireStrikeParseError("submission score wrapper is duplicated or malformed")
            if score_authoritative:
                self.wrapper_depth = depth
        if self.wrapper_depth is not None and "user" in classes and not is_void:
            self.user_depths.append(depth)
        if (
            self.wrapper_depth is not None
            and depth == self.wrapper_depth + 1
            and tag == "div"
            and "score-wrapper" in classes
            and score_authoritative
        ):
            self.score_wrapper_depth = depth
        if (
            self.score_wrapper_depth is not None
            and depth == self.score_wrapper_depth + 1
            and tag == "div"
            and "value" in classes
            and score_authoritative
        ):
            self.value_depth = depth
        if self.value_depth is not None and depth == self.value_depth + 1 and "score-item" in classes:
            if score_authoritative:
                if tag != "span":
                    raise HWBOTFireStrikeParseError("overall score structure is malformed")
                self.score_frame = (depth, [])
        if "wr-ranking-grid" in classes and not is_void:
            if self.ranking_row is not None:
                raise HWBOTFireStrikeParseError("ranking structure is malformed")
            self.ranking_row = (depth, [])
        if tag == "a" and (self.user_depths or self.ranking_row is not None):
            if self.anchor_frame is not None:
                raise HWBOTFireStrikeParseError("anchor structure is malformed")
            self.anchor_frame = (depth, values.get("href", ""), bool(self.user_depths), self.ranking_row is not None, [])

    def handle_data(self, data: str) -> None:
        if self.score_frame is not None:
            self.score_frame[1].append(data)
        if self.anchor_frame is not None:
            self.anchor_frame[4].append(data)

    def handle_endtag(self, tag: str) -> None:
        try:
            depth = len(self.tags) - 1 - self.tags[::-1].index(tag)
        except ValueError:
            return
        relevant = list(self.user_depths)
        relevant.extend(frame[0] for frame in (self.score_frame, self.anchor_frame, self.ranking_row) if frame is not None)
        relevant.extend(frame for frame in (self.score_wrapper_depth, self.value_depth) if frame is not None)
        if self.wrapper_depth is not None:
            relevant.append(self.wrapper_depth)
        if any(item > depth for item in relevant):
            raise HWBOTFireStrikeParseError("required HTML structure is malformed")

        if self.score_frame is not None and self.score_frame[0] == depth:
            self.score_texts.append("".join(self.score_frame[1]))
            self.score_frame = None
        if self.anchor_frame is not None and self.anchor_frame[0] == depth:
            _, href, in_user, in_ranking, parts = self.anchor_frame
            text = _collapsed("".join(parts))
            path = _path(href)
            if in_user and _USER_PATH.fullmatch(path):
                self.header_users.add(path)
            if in_user and path.startswith("/benchmarks/") and "/submissions/" not in path:
                self.benchmark_anchors.append((path, text))
            if in_ranking and self.ranking_row is not None:
                self.ranking_row[1].append((href, text))
            self.anchor_frame = None
        self.user_depths = [item for item in self.user_depths if item != depth]
        if self.value_depth == depth:
            self.value_depth = None
        if self.score_wrapper_depth == depth:
            self.score_wrapper_depth = None
        if self.ranking_row is not None and self.ranking_row[0] == depth:
            self.ranking_rows.append(self.ranking_row[1])
            self.ranking_row = None
        if self.wrapper_depth == depth:
            self.wrapper_depth = None
        self.non_authoritative_score_depths = [
            item for item in self.non_authoritative_score_depths if item < depth
        ]
        del self.tags[depth:]

    def validate_complete(self) -> None:
        if self.wrapper_count != 1:
            raise HWBOTFireStrikeParseError("submission score wrapper is required exactly once")
        active = (
            self.wrapper_depth,
            self.score_wrapper_depth,
            self.value_depth,
            self.score_frame,
            self.anchor_frame,
            self.ranking_row,
        )
        if any(item is not None for item in active):
            raise HWBOTFireStrikeParseError("required HTML structure is malformed")


def _submission_user(parser: _HWBOTHTMLParser) -> str:
    if not parser.benchmark_anchors:
        raise HWBOTFireStrikeParseError("supported benchmark path is missing")
    paths = {path for path, _ in parser.benchmark_anchors}
    if len(paths) != 1:
        raise HWBOTFireStrikeParseError("conflicting benchmark paths")
    path = next(iter(paths))
    if path != _BENCHMARK_PATH:
        raise HWBOTFireStrikeParseError(f"unsupported HWBOT benchmark path: {path}")
    conflicting_label = any(_STANDARD_LABEL.fullmatch(label) is None for _, label in parser.benchmark_anchors)
    if conflicting_label:
        raise HWBOTFireStrikeParseError("visible benchmark label conflicts with Fire Strike Standard")
    if len(parser.header_users) != 1:
        raise HWBOTFireStrikeParseError("submission user structure is missing or ambiguous")
    return next(iter(parser.header_users))


def _native_identifier(parser: _HWBOTHTMLParser, user_path: str, scores: set[str]) -> str:
    identifiers: set[str] = set()
    for row in parser.ranking_rows:
        row_users = {_path(href) for href, _ in row if _USER_PATH.fullmatch(_path(href))}
        if user_path not in row_users:
            continue
        for href, text in row:
            path = _path(href)
            match = _RANKING_SCORE.fullmatch(text)
            if not path.startswith(_SUBMISSION_PREFIX) or match is None:
                continue
            try:
                _, ranking_score = _score(match.group(1), "ranking score")
            except HWBOTFireStrikeParseError:
                continue
            if ranking_score not in scores:
                continue
            identifier = path.removeprefix(_SUBMISSION_PREFIX)
            if re.fullmatch(r"[0-9]+", identifier) is None or identifier == "0" or identifier.startswith("0"):
                raise HWBOTFireStrikeParseError(
                    "native submission identifier must be a positive decimal without leading zeros"
                )
            identifiers.add(identifier)
    if not identifiers:
        raise HWBOTFireStrikeParseError("matching native submission identifier is missing")
    if len(identifiers) != 1:
        raise HWBOTFireStrikeParseError("matching native submission identifier is ambiguous")
    return next(iter(identifiers))


def _field(
    capture: CapturedSourceV1, native_id: str, state: FieldState, locator: str,
    raw: str | None = None,
    normalized: str | None = None,
    alternatives: tuple[FieldEvidenceV1, ...] = (),
) -> FieldEvidenceV1:
    return FieldEvidenceV1(
        state=state,
        source_identifier=_SOURCE,
        native_submission_identifier=native_id,
        capture_sha256=capture.sha256,
        field_locator=locator,
        raw_value=raw,
        normalized_value=normalized,
        unit="marks",
        alternatives=alternatives,
    )


def parse_hwbot_fire_strike_submission(capture: CapturedSourceV1) -> FireStrikeSubmissionV1:
    """Parse a verified offline HWBOT Fire Strike Standard HTML capture."""

    if not isinstance(capture, CapturedSourceV1):
        raise TypeError("HWBOT parser input must be CapturedSourceV1")
    if capture.source_identifier != _SOURCE:
        raise HWBOTFireStrikeParseError("capture source identifier must be source:hwbot")
    if capture.media_type != _MEDIA_TYPE:
        raise HWBOTFireStrikeParseError("capture media type must be text/html")
    try:
        text = capture.payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise HWBOTFireStrikeParseError("HWBOT capture must be valid UTF-8") from error

    parser = _HWBOTHTMLParser()
    parser.feed(text)
    parser.close()
    parser.validate_complete()
    if not parser.score_texts:
        raise HWBOTFireStrikeParseError("authoritative overall score is missing")
    observed = [(*_score(value, "overall score"), occurrence) for occurrence, value in enumerate(parser.score_texts, start=1)]
    score_values = {normalized for _, normalized, _ in observed}
    native_id = _native_identifier(parser, _submission_user(parser), score_values)
    distinct: dict[str, tuple[str, int]] = {}
    for raw, normalized, occurrence in observed:
        distinct.setdefault(normalized, (raw, occurrence))
    if len(distinct) == 1:
        normalized, (raw, _) = next(iter(distinct.items()))
        overall = _field(capture, native_id, FieldState.OBSERVED, _OVERALL_LOCATOR, raw, normalized)
    else:
        alternatives = tuple(
            _field(
                capture,
                native_id,
                FieldState.OBSERVED,
                f"{_OVERALL_LOCATOR}[{occurrence}]",
                raw,
                normalized,
            )
            for normalized, (raw, occurrence) in distinct.items()
        )
        overall = _field(
            capture,
            native_id,
            FieldState.CONFLICTING,
            _OVERALL_LOCATOR,
            alternatives=alternatives,
        )
    missing = _field(capture, native_id, FieldState.MISSING, _SCORE_SCOPE_LOCATOR)
    return FireStrikeSubmissionV1(
        source_identifier=_SOURCE,
        native_submission_identifier=native_id,
        overall_score=overall,
        graphics_score=missing,
        physics_score=missing,
        combined_score=missing,
    )
