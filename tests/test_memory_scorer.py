"""Tests for keyword-based memory relevance scoring."""

from pathlib import Path

from moughorai.memory.scorer import MemoryScorer


def test_empty_query_returns_zero() -> None:
    scorer = MemoryScorer()

    score = scorer.score(
        "",
        path=Path("intel-memory.md"),
        content="# Intel Memory\nDDR5 tuning notes.",
    )

    assert score == 0


def test_whitespace_query_returns_zero() -> None:
    scorer = MemoryScorer()

    score = scorer.score(
        "   ",
        path=Path("intel-memory.md"),
        content="# Intel Memory\nDDR5 tuning notes.",
    )

    assert score == 0


def test_filename_match_adds_five_points() -> None:
    scorer = MemoryScorer()

    score = scorer.score(
        "intel",
        path=Path("intel-memory.md"),
        content="Unrelated content.",
    )

    assert score == 5


def test_title_match_adds_title_heading_and_body_points() -> None:
    scorer = MemoryScorer()

    score = scorer.score(
        "intel",
        path=Path("notes.md"),
        content="# Intel Memory\nUnrelated details.",
    )

    assert score == 8


def test_secondary_heading_match_adds_heading_and_body_points() -> None:
    scorer = MemoryScorer()

    score = scorer.score(
        "voltage",
        path=Path("notes.md"),
        content="# Memory\n## Voltage tuning\nUse safe limits.",
    )

    assert score == 4


def test_body_match_adds_one_point() -> None:
    scorer = MemoryScorer()

    score = scorer.score(
        "timings",
        path=Path("notes.md"),
        content="# Memory\nTune the secondary timings carefully.",
    )

    assert score == 1


def test_matching_is_case_insensitive() -> None:
    scorer = MemoryScorer()

    score = scorer.score(
        "INTEL",
        path=Path("Intel-Memory.md"),
        content="# INTEL MEMORY\nIntel tuning notes.",
    )

    assert score == 13


def test_multiple_query_terms_accumulate_scores() -> None:
    scorer = MemoryScorer()

    score = scorer.score(
        "intel memory",
        path=Path("intel-memory.md"),
        content="# Intel Memory\nIntel memory tuning.",
    )

    assert score == 26


def test_unmatched_query_returns_zero() -> None:
    scorer = MemoryScorer()

    score = scorer.score(
        "python",
        path=Path("intel-memory.md"),
        content="# Intel Memory\nDDR5 tuning notes.",
    )

    assert score == 0


def test_rank_terms_counts_case_insensitive_matches() -> None:
    score = MemoryScorer.rank_terms(
        ["Intel", "Memory", "DDR5"],
        ["memory", "intel", "voltage"],
    )

    assert score == 2