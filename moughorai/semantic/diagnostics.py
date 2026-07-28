from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Iterator


class DiagnosticSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    location: object | None = None
    rule: str | None = None
    pass_name: str | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticBag:
    """Immutable diagnostic collection used by the language-neutral pipeline."""

    items: tuple[Diagnostic, ...] = ()

    def add(self, diagnostic: Diagnostic) -> DiagnosticBag:
        return DiagnosticBag(self.items + (diagnostic,))

    def extend(self, diagnostics: Iterable[Diagnostic]) -> DiagnosticBag:
        return DiagnosticBag(self.items + tuple(diagnostics))

    def by_severity(self, severity: DiagnosticSeverity) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.items if item.severity is severity)

    @property
    def has_errors(self) -> bool:
        return any(item.severity is DiagnosticSeverity.ERROR for item in self.items)

    def __iter__(self) -> Iterator[Diagnostic]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)
