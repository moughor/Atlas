"""Tests for the shared document relevance scorer."""

from pathlib import Path

from moughorai.search.scorer import (
    DocumentScorer,
    ScoreBreakdown,
    ScoringWeights,
)


def test_default_weights_preserve_existing_scoring() -> None:
    scorer = DocumentScorer()

    score = scorer.score(
        "intel",
        path=Path("intel-memory.md"),
        content="# Intel Memory\nIntel tuning notes.",
    )

    assert score == 13


def test_explain_returns_score_breakdown() -> None:
    scorer = DocumentScorer()

    result = scorer.explain(
        "intel",
        path=Path("intel-memory.md"),
        content="# Intel Memory\nIntel tuning notes.",
    )

    assert result == ScoreBreakdown(
        filename=5,
        title=4,
        heading=3,
        body=1,
        quoted_phrase=0,
    )
    assert result.total == 13


def test_empty_query_returns_empty_breakdown() -> None:
    scorer = DocumentScorer()

    result = scorer.explain(
        "   ",
        path=Path("intel-memory.md"),
        content="# Intel Memory\nIntel tuning notes.",
    )

    assert result == ScoreBreakdown()
    assert result.total == 0


def test_custom_weights_are_applied() -> None:
    scorer = DocumentScorer(
        ScoringWeights(
            filename=10,
            title=8,
            heading=6,
            body=2,
            quoted_phrase=12,
        )
    )

    result = scorer.explain(
        "intel",
        path=Path("intel-memory.md"),
        content="# Intel Memory\nIntel tuning notes.",
    )

    assert result == ScoreBreakdown(
        filename=10,
        title=8,
        heading=6,
        body=2,
        quoted_phrase=0,
    )
    assert result.total == 26


def test_quoted_phrase_adds_exact_phrase_bonus() -> None:
    scorer = DocumentScorer()

    result = scorer.explain(
        '"intel memory"',
        path=Path("notes.md"),
        content="# Intel Memory\nDDR5 tuning notes.",
    )

    assert result.quoted_phrase == 6
    assert result.total == 22


def test_single_quoted_phrase_is_supported() -> None:
    scorer = DocumentScorer()

    result = scorer.explain(
        "'intel memory'",
        path=Path("notes.md"),
        content="# Intel Memory\nDDR5 tuning notes.",
    )

    assert result.quoted_phrase == 6


def test_quoted_phrase_matching_is_case_insensitive() -> None:
    scorer = DocumentScorer()

    result = scorer.explain(
        '"INTEL MEMORY"',
        path=Path("notes.md"),
        content="# Intel Memory\nDDR5 tuning notes.",
    )

    assert result.quoted_phrase == 6


def test_quoted_phrase_can_match_filename() -> None:
    scorer = DocumentScorer()

    result = scorer.explain(
        '"intel memory"',
        path=Path("intel-memory.md"),
        content="Unrelated content.",
    )

    assert result.quoted_phrase == 6


def test_unmatched_quoted_phrase_adds_no_bonus() -> None:
    scorer = DocumentScorer()

    result = scorer.explain(
        '"amd memory"',
        path=Path("intel-memory.md"),
        content="# Intel Memory\nDDR5 tuning notes.",
    )

    assert result.quoted_phrase == 0


def test_duplicate_quoted_phrases_are_counted_once() -> None:
    scorer = DocumentScorer()

    result = scorer.explain(
        '"intel memory" and "intel memory"',
        path=Path("notes.md"),
        content="# Intel Memory\nDDR5 tuning notes.",
    )

    assert result.quoted_phrase == 6


def test_multiple_distinct_quoted_phrases_accumulate() -> None:
    scorer = DocumentScorer()

    result = scorer.explain(
        '"intel memory" "ddr5 tuning"',
        path=Path("notes.md"),
        content="# Intel Memory\nDDR5 tuning notes.",
    )

    assert result.quoted_phrase == 12


def test_rank_terms_is_case_insensitive() -> None:
    score = DocumentScorer.rank_terms(
        ["Intel", "Memory", "DDR5"],
        ["memory", "intel", "voltage"],
    )

    assert score == 2