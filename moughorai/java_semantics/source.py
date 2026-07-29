from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True, order=True)
class SourceSpan:
    start: int
    end: int
    line: int = 1
    column: int = 1

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError("invalid source span")

    @property
    def length(self) -> int:
        return self.end - self.start
