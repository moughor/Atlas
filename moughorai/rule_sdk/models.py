from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class RuleSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class RuleContext:
    path: Path
    source: str
    language: str
    configuration: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        if not self.language.strip():
            raise ValueError("rule language must not be empty")
        object.__setattr__(self, "configuration", dict(self.configuration))


@dataclass(frozen=True, slots=True)
class RuleLocation:
    path: Path
    line: int = 1
    column: int = 1
    end_line: int | None = None
    end_column: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        if self.line < 1 or self.column < 1:
            raise ValueError("rule location coordinates are one-based")
        if self.end_line is not None and self.end_line < self.line:
            raise ValueError("rule location end line precedes start")
        if self.end_column is not None and (self.end_line or self.line) == self.line and self.end_column < self.column:
            raise ValueError("rule location end column precedes start")


@dataclass(frozen=True, slots=True)
class RuleFinding:
    rule_id: str
    message: str
    severity: RuleSeverity
    location: RuleLocation
    data: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("rule finding id must not be empty")
        if not self.message.strip():
            raise ValueError("rule finding message must not be empty")
        if self.data != tuple(sorted(self.data, key=lambda item: item[0])):
            raise ValueError("rule finding data must be sorted")

    def to_dict(self) -> dict[str, Any]:
        value = {
            "rule_id": self.rule_id,
            "message": self.message,
            "severity": self.severity.value,
            "path": self.location.path.as_posix(),
            "line": self.location.line,
            "column": self.location.column,
        }
        if self.location.end_line is not None:
            value["end_line"] = self.location.end_line
        if self.location.end_column is not None:
            value["end_column"] = self.location.end_column
        if self.data:
            value["properties"] = dict(self.data)
        return value
