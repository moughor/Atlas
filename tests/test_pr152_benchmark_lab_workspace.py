from __future__ import annotations

from pathlib import Path

import pytest

from moughorai.benchmark_lab import BenchmarkLabState
from moughorai.benchmark_lab_workspace import (
    MAX_ATLAS_SEARCH_CHARACTERS,
    BenchmarkLabWorkspaceInputError,
    detect_hwbot_reference,
    reference_capture_comparison,
    search_current_session,
)


FIXTURES = Path(__file__).parent / "fixtures" / "benchmark_intelligence"
HWBOT = FIXTURES / "hwbot_fire_strike_submission_v1.html"
UL = FIXTURES / "ul_3dmark_fire_strike_result_v1.html"


def _loaded_state() -> dict[str, object]:
    state = BenchmarkLabState()
    state.ingest_hwbot(HWBOT.read_bytes())
    state.ingest_ul(UL.read_bytes())
    return state.to_dict()


def test_fire_strike_submission_reference_is_navigation_only() -> None:
    result = detect_hwbot_reference(
        "https://hwbot.org/benchmarks/3dmark_-_fire_strike/submissions/6026699"
    )

    assert result == {
        "authority": "navigation_only",
        "benchmark_hint": "benchmark:ul:3dmark:fire-strike-standard",
        "normalized_reference_url": (
            "https://hwbot.org/benchmarks/3dmark_-_fire_strike/submissions/6026699"
        ),
        "path_submission_segment": "6026699",
        "route_family": "fire_strike_submission",
        "semantic_evidence": False,
        "source_identifier": "source:hwbot",
        "status": "url_detected_unparsed",
    }
    assert "capture_sha256" not in result
    assert "submission_id" not in result


@pytest.mark.parametrize(
    ("url", "family"),
    [
        ("https://hwbot.org/", "home"),
        ("https://hwbot.org/search", "site_search"),
        ("https://hwbot.org/submissions", "submission_search"),
        ("https://hwbot.org/users", "member_search"),
        (
            "https://hwbot.org/benchmarks/3dmark_-_fire_strike",
            "fire_strike_benchmark",
        ),
        (
            "https://hwbot.org/benchmarks/3dmark_-_fire_strike/rankings",
            "fire_strike_ranking",
        ),
        ("https://hwbot.org/users/moughor", "profile"),
    ],
)
def test_supported_navigation_route_families(url: str, family: str) -> None:
    assert detect_hwbot_reference(url)["route_family"] == family


def test_www_host_is_narrowly_normalized() -> None:
    result = detect_hwbot_reference("https://www.hwbot.org/users/moughor?q=1#top")

    assert result["normalized_reference_url"] == (
        "https://hwbot.org/users/moughor?q=1#top"
    )
    assert result["route_family"] == "profile"


@pytest.mark.parametrize(
    "url",
    [
        "http://hwbot.org/",
        "ftp://hwbot.org/",
        "https://evil.example/",
        "https://hwbot.org.evil.example/",
        "https://hwbot.org@evil.example/",
        "https://user@hwbot.org/",
        "https://user:password@hwbot.org/",
        "https://hwbot.org:444/",
        "https://hwbot.org\\@evil.example/",
        "https://hwbot.org/%2f%2fevil.example/",
        "https://hwbot.org/benchmarks/3dmark_-_fire_strike/submissions/%36%30",
        "https://hwbot.org/benchmarks/3dmark_-_fire_strike/submissions/0",
        "https://hwbot.org/benchmarks/3dmark_-_fire_strike/submissions/01",
        "https://hwbot.org/benchmarks/3dmark_-_fire_strike/submissions/+1",
        "https://hwbot.org/benchmarks/3dmark_-_fire_strike/submissions/１２",
        "https://hwbоt.org/",  # Cyrillic o.
        "https://hwbot.org/articles",
        "https://hwbot.org/\nusers",
        "https://hwbot.org/\u200busers",
        " https://hwbot.org/",
    ],
)
def test_reference_attacks_are_rejected(url: str) -> None:
    with pytest.raises(BenchmarkLabWorkspaceInputError):
        detect_hwbot_reference(url)


@pytest.mark.parametrize("value", [None, 1, b"https://hwbot.org/"])
def test_reference_requires_exact_text(value: object) -> None:
    with pytest.raises(TypeError):
        detect_hwbot_reference(value)


def test_query_and_fragment_never_supply_submission_identity() -> None:
    result = detect_hwbot_reference(
        "https://hwbot.org/search?submission=6026699#"
        "/benchmarks/3dmark_-_fire_strike/submissions/6026699"
    )

    assert result["route_family"] == "site_search"
    assert result["path_submission_segment"] is None
    assert result["semantic_evidence"] is False


def test_path_identity_is_explicitly_unverified_and_cannot_repair_capture() -> None:
    detected = detect_hwbot_reference(
        "https://hwbot.org/benchmarks/3dmark_-_fire_strike/submissions/6026699"
    )
    parsed = _loaded_state()["sources"]["hwbot"]

    comparison = reference_capture_comparison(detected, parsed)

    assert comparison == {
        "matches_parsed_capture": False,
        "parsed_native_submission_identifier": "1480001",
        "path_submission_segment": "6026699",
        "warning": "Detected path ID differs from parser-authoritative capture ID",
    }
    assert parsed["native_submission_identifier"] == "1480001"


def test_matching_path_is_only_a_nonsemantic_comparison() -> None:
    detected = detect_hwbot_reference(
        "https://hwbot.org/benchmarks/3dmark_-_fire_strike/submissions/1480001"
    )
    parsed = _loaded_state()["sources"]["hwbot"]

    comparison = reference_capture_comparison(detected, parsed)

    assert comparison["matches_parsed_capture"] is True
    assert comparison["warning"] is None
    assert detected["authority"] == "navigation_only"


def test_current_session_search_is_case_insensitive_and_source_ordered() -> None:
    value = search_current_session(_loaded_state(), "FIRE-STRIKE-STANDARD")

    assert [item["source_key"] for item in value["results"]] == [
        "hwbot",
        "ul_3dmark",
    ]
    assert len(value["results"]) == 2
    assert value["scope"] == "current_session"


@pytest.mark.parametrize(
    ("query", "source"),
    [
        ("HWBOT", "hwbot"),
        ("source:ul-3dmark-results", "ul_3dmark"),
        ("1480001", "hwbot"),
        ("90000001", "ul_3dmark"),
        ("13579", "ul_3dmark"),
    ],
)
def test_searchable_current_session_fields(query: str, source: str) -> None:
    result = search_current_session(_loaded_state(), query)["results"]

    assert result
    assert result[0]["source_key"] == source


def test_search_preserves_nfc_query_and_handles_html_like_text_as_plain_text() -> None:
    result = search_current_session(_loaded_state(), "  <SCRIPT>  ")

    assert result == {
        "query": "<SCRIPT>",
        "results": [],
        "scope": "current_session",
    }


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
        "x" * (MAX_ATLAS_SEARCH_CHARACTERS + 1),
        "line\nbreak",
        "zero\u200bwidth",
    ],
)
def test_search_query_bounds_and_controls(query: str) -> None:
    with pytest.raises(BenchmarkLabWorkspaceInputError):
        search_current_session(_loaded_state(), query)


def test_conflicts_missing_fields_and_alternatives_are_not_indexed() -> None:
    state = {
        "sources": {
            "hwbot": {
                "benchmark_id": "benchmark:ul:3dmark:fire-strike-standard",
                "source_identifier": "source:hwbot",
                "native_submission_identifier": "1",
                "submission_id": "submission:source:hwbot:1",
                "scores": {
                    "overall_score": {
                        "state": "conflicting",
                        "normalized_value": None,
                        "alternatives": [
                            {"normalized_value": "99991"},
                            {"normalized_value": "99992"},
                        ],
                    },
                    "graphics_score": {
                        "state": "missing",
                        "normalized_value": None,
                    },
                },
            },
            "ul_3dmark": None,
        }
    }

    assert search_current_session(state, "99991")["results"] == []
    assert search_current_session(state, "missing")["results"] == []


def test_empty_state_has_no_false_results() -> None:
    state = {"sources": {"hwbot": None, "ul_3dmark": None}}

    assert search_current_session(state, "fire strike")["results"] == []


def test_search_is_repeatable_and_does_not_mutate_state() -> None:
    state = _loaded_state()
    before = repr(state)

    first = search_current_session(state, "12345")
    second = search_current_session(state, "12345")

    assert first == second
    assert repr(state) == before
