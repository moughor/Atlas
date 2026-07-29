from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Mapping


class DiagnosticSeverity(IntEnum):
    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4


@dataclass(frozen=True, slots=True, order=True)
class Position:
    line: int
    character: int

    def __post_init__(self) -> None:
        if self.line < 0 or self.character < 0:
            raise ValueError("position coordinates must be non-negative")

    def to_dict(self) -> dict[str, int]:
        return {"line": self.line, "character": self.character}


@dataclass(frozen=True, slots=True)
class Range:
    start: Position
    end: Position

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("range end must not precede start")

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start.to_dict(), "end": self.end.to_dict()}


@dataclass(frozen=True, slots=True)
class Diagnostic:
    range: Range
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.WARNING
    code: str = ""
    source: str = "atlas"
    data: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("diagnostic message must not be empty")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "range": self.range.to_dict(),
            "message": self.message,
            "severity": int(self.severity),
            "source": self.source,
        }
        if self.code:
            result["code"] = self.code
        if self.data:
            result["data"] = dict(self.data)
        return result


@dataclass(frozen=True, slots=True)
class TextDocument:
    uri: str
    text: str
    version: int = 0
    language_id: str = "java"

    def __post_init__(self) -> None:
        if not self.uri.strip():
            raise ValueError("document uri must not be empty")
        if self.version < 0:
            raise ValueError("document version must be non-negative")


@dataclass(frozen=True, slots=True)
class PublishDiagnostics:
    uri: str
    version: int
    diagnostics: tuple[Diagnostic, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "version": self.version,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
