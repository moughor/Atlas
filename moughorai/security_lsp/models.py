from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

class DiagnosticSeverity(IntEnum):
    ERROR=1; WARNING=2; INFORMATION=3; HINT=4

@dataclass(frozen=True, slots=True, order=True)
class Position:
    line: int
    character: int
    def __post_init__(self):
        if self.line < 0 or self.character < 0: raise ValueError('position values must be non-negative')
    def to_dict(self): return {'line': self.line, 'character': self.character}

@dataclass(frozen=True, slots=True)
class Range:
    start: Position
    end: Position
    def __post_init__(self):
        if self.end < self.start: raise ValueError('range end must not precede start')
    def to_dict(self): return {'start': self.start.to_dict(), 'end': self.end.to_dict()}

@dataclass(frozen=True, slots=True)
class Diagnostic:
    range: Range
    message: str
    severity: DiagnosticSeverity
    code: str
    source: str = 'atlas'
    data: tuple[tuple[str, Any], ...] = ()
    def to_dict(self):
        result={'range':self.range.to_dict(),'message':self.message,'severity':int(self.severity),'code':self.code,'source':self.source}
        if self.data: result['data']={k:v for k,v in self.data}
        return result

@dataclass(frozen=True, slots=True)
class TextEdit:
    range: Range
    new_text: str
    def to_dict(self): return {'range':self.range.to_dict(),'newText':self.new_text}

@dataclass(frozen=True, slots=True)
class CodeAction:
    title: str
    kind: str
    diagnostics: tuple[Diagnostic, ...] = ()
    edits: tuple[tuple[str, tuple[TextEdit, ...]], ...] = ()
    command: str | None = None
    data: tuple[tuple[str, Any], ...] = ()
    def to_dict(self):
        out={'title':self.title,'kind':self.kind}
        if self.diagnostics: out['diagnostics']=[d.to_dict() for d in self.diagnostics]
        if self.edits: out['edit']={'changes':{uri:[e.to_dict() for e in edits] for uri,edits in self.edits}}
        if self.command: out['command']={'title':self.title,'command':self.command}
        if self.data: out['data']={k:v for k,v in self.data}
        return out

@dataclass(frozen=True, slots=True)
class DocumentSymbol:
    name: str
    kind: int
    range: Range
    selection_range: Range
    children: tuple['DocumentSymbol', ...] = ()
    def to_dict(self):
        out={'name':self.name,'kind':self.kind,'range':self.range.to_dict(),'selectionRange':self.selection_range.to_dict()}
        if self.children: out['children']=[c.to_dict() for c in self.children]
        return out

@dataclass(frozen=True, slots=True)
class PublishDiagnostics:
    uri: str
    version: int | None
    diagnostics: tuple[Diagnostic, ...]
    def to_dict(self):
        out={'uri':self.uri,'diagnostics':[d.to_dict() for d in self.diagnostics]}
        if self.version is not None: out['version']=self.version
        return out
