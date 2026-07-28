"""Deterministic keyword-based document relevance scoring."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_WORD_PATTERN = re.compile(r"[A-Za-z0-9_+]+")
_QUOTED_PHRASE_PATTERN = re.compile(r"""["']([^"'\r\n]+)["']""")


@dataclass(frozen=True)
class ScoringWeights:
    """Weights applied to matches in each searchable document section."""

    filename: int = 5
    title: int = 4
    heading: int = 3
    body: int = 1
    quoted_phrase: int = 6


@dataclass(frozen=True)
class ScoreBreakdown:
    """Detailed scoring information for one document."""

    filename: int = 0
    title: int = 0
    heading: int = 0
    body: int = 0
    quoted_phrase: int = 0

    @property
    def total(self) -> int:
        """Return the total relevance score."""

        return (
            self.filename
            + self.title
            + self.heading
            + self.body
            + self.quoted_phrase
        )


class DocumentScorer:
    """Score text documents against a natural-language query."""

    def __init__(
        self,
        weights: ScoringWeights | None = None,
    ) -> None:
        self._weights = weights or ScoringWeights()

    def score(
        self,
        query: str,
        *,
        path: Path,
        content: str,
    ) -> int:
        """Return a deterministic relevance score for one document."""

        return self.explain(
            query,
            path=path,
            content=content,
        ).total

    def explain(
        self,
        query: str,
        *,
        path: Path,
        content: str,
    ) -> ScoreBreakdown:
        """Return a detailed score breakdown for one document."""

        query_terms = self._extract_terms(query)

        if not query_terms:
            return ScoreBreakdown()

        filename_terms = self._extract_terms(path.stem)
        title_terms = self._extract_title_terms(content)
        heading_terms = self._extract_heading_terms(content)
        body_terms = self._extract_terms(content)

        filename_score = self.rank_terms(
            query_terms,
            filename_terms,
        ) * self._weights.filename

        title_score = self.rank_terms(
            query_terms,
            title_terms,
        ) * self._weights.title

        heading_score = self.rank_terms(
            query_terms,
            heading_terms,
        ) * self._weights.heading

        body_score = self.rank_terms(
            query_terms,
            body_terms,
        ) * self._weights.body

        phrase_score = self._score_quoted_phrases(
            query,
            path=path,
            content=content,
        )

        return ScoreBreakdown(
            filename=filename_score,
            title=title_score,
            heading=heading_score,
            body=body_score,
            quoted_phrase=phrase_score,
        )

    @staticmethod
    def _extract_terms(value: str) -> set[str]:
        """Return unique normalized searchable terms."""

        return {
            match.group(0).casefold()
            for match in _WORD_PATTERN.finditer(value)
        }

    @staticmethod
    def _extract_ordered_terms(value: str) -> tuple[str, ...]:
        """Return normalized searchable terms while preserving order."""

        return tuple(
            match.group(0).casefold()
            for match in _WORD_PATTERN.finditer(value)
        )

    def _extract_title_terms(self, content: str) -> set[str]:
        """Return terms from the first Markdown level-one heading."""

        for line in content.splitlines():
            stripped = line.strip()

            if stripped.startswith("# "):
                return self._extract_terms(stripped[2:])

        return set()

    def _extract_heading_terms(self, content: str) -> set[str]:
        """Return terms from all Markdown headings."""

        headings: list[str] = []

        for line in content.splitlines():
            stripped = line.strip()

            if stripped.startswith("#"):
                headings.append(
                    stripped.lstrip("#").strip()
                )

        return self._extract_terms(" ".join(headings))

    def _score_quoted_phrases(
        self,
        query: str,
        *,
        path: Path,
        content: str,
    ) -> int:
        """Reward exact phrases explicitly quoted in the query."""

        phrases = {
            self._normalize_phrase(match.group(1))
            for match in _QUOTED_PHRASE_PATTERN.finditer(query)
            if self._normalize_phrase(match.group(1))
        }

        if not phrases:
            return 0

        filename = self._normalize_phrase(path.stem)
        document = self._normalize_phrase(content)

        matches = sum(
            1
            for phrase in phrases
            if phrase in filename or phrase in document
        )

        return matches * self._weights.quoted_phrase

    @classmethod
    def _normalize_phrase(cls, value: str) -> str:
        """Normalize a phrase while preserving its original word order."""

        return " ".join(cls._extract_ordered_terms(value))

    @staticmethod
    def rank_terms(
        query_terms: Iterable[str],
        document_terms: Iterable[str],
    ) -> int:
        """Return the number of normalized matching terms."""

        normalized_query = {
            term.casefold()
            for term in query_terms
        }
        normalized_document = {
            term.casefold()
            for term in document_terms
        }

        return len(
            normalized_query
            & normalized_document
        )