"""Shared immutable source-location models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class SourceLocation:
    """One position in a source file."""

    offset: int
    line: int
    column: int

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise ValueError("offset must be non-negative")
        if self.line < 1:
            raise ValueError("line must be at least 1")
        if self.column < 1:
            raise ValueError("column must be at least 1")


@dataclass(frozen=True)
class SourceSpan:
    """Half-open source range from start to end."""

    start: SourceLocation
    end: SourceLocation

    def __post_init__(self) -> None:
        if self.end.offset < self.start.offset:
            raise ValueError("span end must not precede span start")

    @property
    def length(self) -> int:
        return self.end.offset - self.start.offset
