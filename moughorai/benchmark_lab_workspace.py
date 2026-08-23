"""Narrow navigation and current-session search contracts for Benchmark Lab."""

from __future__ import annotations

from collections.abc import Mapping
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit


MAX_HWBOT_REFERENCE_CHARACTERS = 2048
MAX_ATLAS_SEARCH_CHARACTERS = 128
HWBOT_CANONICAL_ORIGIN = "https://hwbot.org"
HWBOT_SOURCE_IDENTIFIER = "source:hwbot"
FIRE_STRIKE_BENCHMARK_ID = "benchmark:ul:3dmark:fire-strike-standard"
FIRE_STRIKE_SLUG = "3dmark_-_fire_strike"
_PORTABLE_SEGMENT = r"[a-z0-9][a-z0-9._-]*"
_PROFILE = re.compile(rf"^/users/(?P<profile>{_PORTABLE_SEGMENT})/?$")
_FIRE_STRIKE_SUBMISSION = re.compile(
    rf"^/benchmarks/{FIRE_STRIKE_SLUG}/submissions/(?P<submission>[1-9][0-9]*)/?$"
)
_CONTROL_CATEGORIES = {"Cc", "Cf", "Cs"}
_SCORE_FIELD_ORDER = (
    "overall_score",
    "graphics_score",
    "physics_score",
    "combined_score",
)
_SOURCE_ORDER = (
    ("hwbot", "HWBOT"),
    ("ul_3dmark", "UL / 3DMark"),
)


class BenchmarkLabWorkspaceInputError(ValueError):
    """Navigation or current-session search input is outside the V1 contract."""


def _contains_control(value: str) -> bool:
    return any(unicodedata.category(character) in _CONTROL_CATEGORIES for character in value)


def _route(path: str) -> tuple[str, str | None, str | None]:
    fixed = {
        "/": ("home", None, None),
        "/search": ("site_search", None, None),
        "/submissions": ("submission_search", None, None),
        "/users": ("member_search", None, None),
        f"/benchmarks/{FIRE_STRIKE_SLUG}": (
            "fire_strike_benchmark",
            FIRE_STRIKE_BENCHMARK_ID,
            None,
        ),
        f"/benchmarks/{FIRE_STRIKE_SLUG}/": (
            "fire_strike_benchmark",
            FIRE_STRIKE_BENCHMARK_ID,
            None,
        ),
        f"/benchmarks/{FIRE_STRIKE_SLUG}/rankings": (
            "fire_strike_ranking",
            FIRE_STRIKE_BENCHMARK_ID,
            None,
        ),
        f"/benchmarks/{FIRE_STRIKE_SLUG}/rankings/": (
            "fire_strike_ranking",
            FIRE_STRIKE_BENCHMARK_ID,
            None,
        ),
    }
    if path in fixed:
        return fixed[path]
    submission = _FIRE_STRIKE_SUBMISSION.fullmatch(path)
    if submission is not None:
        return (
            "fire_strike_submission",
            FIRE_STRIKE_BENCHMARK_ID,
            submission.group("submission"),
        )
    if path.startswith(f"/benchmarks/{FIRE_STRIKE_SLUG}/submissions/"):
        raise BenchmarkLabWorkspaceInputError(
            "HWBOT Fire Strike submission path is malformed"
        )
    if _PROFILE.fullmatch(path) is not None:
        return "profile", None, None
    raise BenchmarkLabWorkspaceInputError("HWBOT reference URL route is unsupported")


def detect_hwbot_reference(value: object) -> dict[str, object]:
    """Classify one explicit HWBOT URL without creating source evidence."""

    if type(value) is not str:
        raise TypeError("HWBOT reference URL must be a string")
    if not value or len(value) > MAX_HWBOT_REFERENCE_CHARACTERS:
        raise BenchmarkLabWorkspaceInputError("HWBOT reference URL length is invalid")
    if value != value.strip():
        raise BenchmarkLabWorkspaceInputError(
            "HWBOT reference URL cannot contain surrounding whitespace"
        )
    if unicodedata.normalize("NFC", value) != value or _contains_control(value):
        raise BenchmarkLabWorkspaceInputError("HWBOT reference URL text is invalid")
    if "\\" in value:
        raise BenchmarkLabWorkspaceInputError("HWBOT reference URL cannot contain backslashes")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise BenchmarkLabWorkspaceInputError("HWBOT reference URL is malformed") from error
    if parsed.scheme != "https":
        raise BenchmarkLabWorkspaceInputError("HWBOT reference URL must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise BenchmarkLabWorkspaceInputError("HWBOT reference URL cannot contain credentials")
    if parsed.hostname not in {"hwbot.org", "www.hwbot.org"}:
        raise BenchmarkLabWorkspaceInputError("HWBOT reference URL host is unsupported")
    if port not in {None, 443}:
        raise BenchmarkLabWorkspaceInputError("HWBOT reference URL port is unsupported")
    if "%" in parsed.path:
        raise BenchmarkLabWorkspaceInputError(
            "HWBOT reference URL path cannot contain percent encoding"
        )

    route_family, benchmark_hint, path_submission_segment = _route(parsed.path)
    normalized_url = urlunsplit(
        ("https", "hwbot.org", parsed.path, parsed.query, parsed.fragment)
    )
    return {
        "authority": "navigation_only",
        "benchmark_hint": benchmark_hint,
        "normalized_reference_url": normalized_url,
        "path_submission_segment": path_submission_segment,
        "route_family": route_family,
        "semantic_evidence": False,
        "source_identifier": HWBOT_SOURCE_IDENTIFIER,
        "status": "url_detected_unparsed",
    }


def reference_capture_comparison(
    reference: Mapping[str, object],
    hwbot_projection: Mapping[str, object] | None,
) -> dict[str, object]:
    """Compare navigation text to parsed identity without linking or mutation."""

    path_value = reference.get("path_submission_segment")
    parsed_value = (
        hwbot_projection.get("native_submission_identifier")
        if hwbot_projection is not None
        else None
    )
    comparable = isinstance(path_value, str) and isinstance(parsed_value, str)
    return {
        "matches_parsed_capture": path_value == parsed_value if comparable else None,
        "parsed_native_submission_identifier": parsed_value,
        "path_submission_segment": path_value,
        "warning": (
            "Detected path ID differs from parser-authoritative capture ID"
            if comparable and path_value != parsed_value
            else None
        ),
    }


def _searchable_values(
    projection: Mapping[str, object],
    source_label: str,
) -> tuple[tuple[str, str], ...]:
    values: list[tuple[str, str]] = [("source_label", source_label)]
    for field in (
        "benchmark_id",
        "source_identifier",
        "native_submission_identifier",
        "submission_id",
    ):
        value = projection.get(field)
        if isinstance(value, str):
            values.append((field, value))
    scores = projection.get("scores")
    if isinstance(scores, Mapping):
        for field in _SCORE_FIELD_ORDER:
            evidence = scores.get(field)
            if not isinstance(evidence, Mapping) or evidence.get("state") != "observed":
                continue
            normalized = evidence.get("normalized_value")
            if isinstance(normalized, str):
                values.append((field, normalized))
    return tuple(values)


def search_current_session(
    state: Mapping[str, object],
    query: object,
) -> dict[str, object]:
    """Search only the two parsed projections already held by Benchmark Lab."""

    if type(query) is not str:
        raise TypeError("Atlas Search query must be a string")
    normalized = unicodedata.normalize("NFC", query)
    if _contains_control(normalized):
        raise BenchmarkLabWorkspaceInputError("Atlas Search query contains control text")
    if len(normalized) > MAX_ATLAS_SEARCH_CHARACTERS:
        raise BenchmarkLabWorkspaceInputError("Atlas Search query exceeds 128 characters")
    normalized = normalized.strip()
    if not normalized:
        raise BenchmarkLabWorkspaceInputError("Atlas Search query must not be empty")
    needle = normalized.casefold()
    sources = state.get("sources")
    if not isinstance(sources, Mapping):
        raise ValueError("Benchmark Lab state has no source projections")

    results: list[dict[str, object]] = []
    for source_key, source_label in _SOURCE_ORDER:
        projection = sources.get(source_key)
        if not isinstance(projection, Mapping):
            continue
        matches = tuple(
            field
            for field, value in _searchable_values(projection, source_label)
            if needle in unicodedata.normalize("NFC", value).casefold()
        )
        if not matches:
            continue
        results.append(
            {
                "benchmark_id": projection.get("benchmark_id"),
                "matched_fields": list(matches),
                "native_submission_identifier": projection.get(
                    "native_submission_identifier"
                ),
                "source_identifier": projection.get("source_identifier"),
                "source_key": source_key,
                "source_label": source_label,
                "submission_id": projection.get("submission_id"),
            }
        )
    return {
        "query": normalized,
        "results": results,
        "scope": "current_session",
    }
