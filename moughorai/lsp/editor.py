from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .models import Position, Range, TextDocument


@dataclass(frozen=True, slots=True)
class TextChange:
    text: str
    range: Range | None = None


@dataclass(frozen=True, slots=True)
class DocumentChangeSet:
    previous: TextDocument
    current: TextDocument
    changes: tuple[TextChange, ...]


def apply_document_changes(
    previous: TextDocument,
    version: int,
    raw_changes: Sequence[Mapping[str, Any]],
) -> DocumentChangeSet:
    if version <= previous.version:
        raise ValueError(f"document version must increase: {version} <= {previous.version}")
    if not raw_changes:
        raise ValueError("didChange requires contentChanges")
    text = previous.text
    changes: list[TextChange] = []
    for raw in raw_changes:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("text"), str):
            raise ValueError("content change requires text")
        span = _range(raw.get("range"))
        change = TextChange(raw["text"], span)
        if span is None:
            text = change.text
        else:
            start = position_to_offset(text, span.start)
            end = position_to_offset(text, span.end)
            if end < start:
                raise ValueError("change range end precedes start")
            text = text[:start] + change.text + text[end:]
        changes.append(change)
    current = TextDocument(previous.uri, text, version, previous.language_id)
    return DocumentChangeSet(previous, current, tuple(changes))


def position_to_offset(text: str, position: Position) -> int:
    lines = text.splitlines(keepends=True)
    if position.line == len(lines) and position.character == 0:
        return len(text)
    if position.line >= len(lines):
        raise ValueError("position line is outside document")
    line = lines[position.line]
    content = line.rstrip("\r\n")
    if position.character > len(content):
        raise ValueError("position character is outside line")
    return sum(len(item) for item in lines[:position.line]) + position.character


def _range(value: Any) -> Range | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("change range must be an object")
    try:
        start = value["start"]
        end = value["end"]
        return Range(
            Position(int(start["line"]), int(start["character"])),
            Position(int(end["line"]), int(end["character"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("change range is invalid") from exc
