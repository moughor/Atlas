from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from .source import SourceSpan

class DiagnosticSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"

@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    severity: DiagnosticSeverity
    span: SourceSpan | None = None

class DiagnosticBag:
    def __init__(self) -> None:
        self._items: list[Diagnostic] = []

    def add(
        self,
        code: str,
        message: str,
        severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
        span: SourceSpan | None = None,
    ) -> Diagnostic:
        item = Diagnostic(code, message, severity, span)
        self._items.append(item)
        return item

    def extend(self, items) -> None:
        self._items.extend(items)

    def snapshot(self) -> tuple[Diagnostic, ...]:
        return tuple(self._items)

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)
