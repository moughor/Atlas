from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Iterable, Mapping

from .models import Diagnostic, DiagnosticSeverity, Position, PublishDiagnostics, Range, TextDocument


_SEVERITY_MAP = {
    "error": DiagnosticSeverity.ERROR,
    "critical": DiagnosticSeverity.ERROR,
    "high": DiagnosticSeverity.ERROR,
    "warning": DiagnosticSeverity.WARNING,
    "warn": DiagnosticSeverity.WARNING,
    "medium": DiagnosticSeverity.WARNING,
    "information": DiagnosticSeverity.INFORMATION,
    "info": DiagnosticSeverity.INFORMATION,
    "low": DiagnosticSeverity.INFORMATION,
    "hint": DiagnosticSeverity.HINT,
}


def offset_to_position(text: str, offset: int) -> Position:
    if offset < 0 or offset > len(text):
        raise ValueError("offset is outside document")
    prefix = text[:offset]
    line = prefix.count("\n")
    last_newline = prefix.rfind("\n")
    character = offset if last_newline < 0 else offset - last_newline - 1
    return Position(line, character)


def offsets_to_range(text: str, start: int, end: int) -> Range:
    if end < start:
        raise ValueError("end offset must not precede start offset")
    return Range(offset_to_position(text, start), offset_to_position(text, end))


def _read(finding: Any, *names: str, default: Any = None) -> Any:
    if isinstance(finding, Mapping):
        for name in names:
            if name in finding:
                return finding[name]
        return default
    for name in names:
        if hasattr(finding, name):
            return getattr(finding, name)
    return default


def finding_to_diagnostic(document: TextDocument, finding: Any) -> Diagnostic:
    message = str(_read(finding, "message", "title", default="Analysis finding"))
    code = str(_read(finding, "rule_id", "code", "id", default=""))
    raw_severity = str(_read(finding, "severity", default="warning")).lower()
    severity = _SEVERITY_MAP.get(raw_severity, DiagnosticSeverity.WARNING)

    start = _read(finding, "start_offset", "offset", default=None)
    end = _read(finding, "end_offset", default=None)
    if start is not None:
        start_i = int(start)
        end_i = int(end if end is not None else start_i + 1)
        span = offsets_to_range(document.text, start_i, min(end_i, len(document.text)))
    else:
        line = max(0, int(_read(finding, "line", "start_line", default=1)) - 1)
        column = max(0, int(_read(finding, "column", "start_column", default=1)) - 1)
        end_line = max(line, int(_read(finding, "end_line", default=line + 1)) - 1)
        end_column = max(column + 1, int(_read(finding, "end_column", default=column + 2)) - 1)
        span = Range(Position(line, column), Position(end_line, end_column))

    metadata = _read(finding, "metadata", "properties", default={}) or {}
    if isinstance(metadata, Mapping):
        data = tuple(sorted((str(k), str(v)) for k, v in metadata.items()))
    else:
        data = ()
    return Diagnostic(span, message, severity, code, data=data)


class DiagnosticPublisher:
    def __init__(self, analyzer: Callable[[TextDocument], Iterable[Any]]) -> None:
        self._analyzer = analyzer
        self._versions: dict[str, int] = {}
        self._last_payload: dict[str, PublishDiagnostics] = {}

    def analyze(self, document: TextDocument) -> PublishDiagnostics:
        current = self._versions.get(document.uri, -1)
        if document.version < current:
            raise ValueError(f"stale document version: {document.version} < {current}")
        diagnostics = tuple(
            sorted(
                (finding_to_diagnostic(document, finding) for finding in self._analyzer(document)),
                key=lambda item: (
                    item.range.start.line,
                    item.range.start.character,
                    item.code,
                    item.message,
                ),
            )
        )
        payload = PublishDiagnostics(document.uri, document.version, diagnostics)
        self._versions[document.uri] = document.version
        self._last_payload[document.uri] = payload
        return payload

    def clear(self, uri: str, *, version: int | None = None) -> PublishDiagnostics:
        effective_version = self._versions.get(uri, 0) if version is None else version
        if effective_version < self._versions.get(uri, -1):
            raise ValueError("cannot clear diagnostics with a stale version")
        payload = PublishDiagnostics(uri, effective_version, ())
        self._versions[uri] = effective_version
        self._last_payload[uri] = payload
        return payload

    def last(self, uri: str) -> PublishDiagnostics | None:
        return self._last_payload.get(uri)
