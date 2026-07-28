from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True, slots=True)
class Interval:
    lower: float | int | None = None
    lower_inclusive: bool = True
    upper: float | int | None = None
    upper_inclusive: bool = True

    def intersect(self, other: 'Interval') -> 'Interval | None':
        lo, li = self.lower, self.lower_inclusive
        if other.lower is not None and (lo is None or other.lower > lo or (other.lower == lo and not other.lower_inclusive)):
            lo, li = other.lower, other.lower_inclusive
        elif other.lower == lo and lo is not None:
            li = li and other.lower_inclusive
        hi, ui = self.upper, self.upper_inclusive
        if other.upper is not None and (hi is None or other.upper < hi or (other.upper == hi and not other.upper_inclusive)):
            hi, ui = other.upper, other.upper_inclusive
        elif other.upper == hi and hi is not None:
            ui = ui and other.upper_inclusive
        if lo is not None and hi is not None and (lo > hi or (lo == hi and not (li and ui))):
            return None
        return Interval(lo, li, hi, ui)

    def contains(self, value: Any) -> bool:
        if not isinstance(value, (int, float)) or isinstance(value, bool): return False
        if self.lower is not None and (value < self.lower or (value == self.lower and not self.lower_inclusive)): return False
        if self.upper is not None and (value > self.upper or (value == self.upper and not self.upper_inclusive)): return False
        return True

@dataclass(frozen=True, slots=True)
class StringFacts:
    equals: str | None = None
    prefixes: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = ()
    contains: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    min_length: int = 0
    max_length: int | None = None

@dataclass(frozen=True, slots=True)
class CollectionFacts:
    min_size: int = 0
    max_size: int | None = None
    empty: bool | None = None

@dataclass(frozen=True, slots=True)
class SolveResult:
    feasible: bool
    intervals: tuple[tuple[str, Interval], ...] = ()
    strings: tuple[tuple[str, StringFacts], ...] = ()
    collections: tuple[tuple[str, CollectionFacts], ...] = ()
    booleans: tuple[tuple[str, bool], ...] = ()
    nullability: tuple[tuple[str, bool], ...] = ()
    reasons: tuple[str, ...] = ()
