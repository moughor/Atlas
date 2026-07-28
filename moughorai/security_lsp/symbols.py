from __future__ import annotations
import re
from .models import DocumentSymbol, Position, Range

_TYPE=re.compile(r'\b(class|interface|enum|record)\s+([A-Za-z_$][\w$]*)')
_METHOD=re.compile(r'(?<![\w$])(?:public\s+|protected\s+|private\s+|static\s+|final\s+|abstract\s+|synchronized\s+|native\s+|default\s+|strictfp\s+)*[A-Za-z_$][\w$<>\[\],.?]*\s+([A-Za-z_$][\w$]*)\s*\([^;{}]*\)\s*(?:throws[^\{]+)?\{')

def _range(source,start,end):
    def pos(offset):
        before=source[:offset]; line=before.count('\n'); last=before.rfind('\n'); return Position(line,offset if last<0 else offset-last-1)
    return Range(pos(start),pos(end))

def document_symbols(source:str)->tuple[DocumentSymbol,...]:
    symbols=[]
    for m in _TYPE.finditer(source):
        r=_range(source,m.start(2),m.end(2)); symbols.append(DocumentSymbol(m.group(2),5,r,r))
    for m in _METHOD.finditer(source):
        r=_range(source,m.start(1),m.end(1)); symbols.append(DocumentSymbol(m.group(1),6,r,r))
    return tuple(sorted(symbols,key=lambda s:(s.range.start.line,s.range.start.character,s.name)))
