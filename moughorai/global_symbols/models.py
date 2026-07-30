from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import hashlib

class GlobalSymbolKind(str, Enum):
    PACKAGE='package'; TYPE='type'; FIELD='field'; CONSTRUCTOR='constructor'; METHOD='method'; ANNOTATION='annotation'

@dataclass(frozen=True, order=True)
class SymbolId:
    value: str
    @classmethod
    def from_parts(cls, kind: GlobalSymbolKind, qualified_name: str, project_id: str | None = None) -> 'SymbolId':
        canonical = (
            f'{kind.value}:{qualified_name}'
            if project_id is None
            else f'{kind.value}:{project_id}:{qualified_name}'
        )
        digest=hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:24]
        return cls(f'{kind.value}:{digest}')
    def __str__(self)->str: return self.value

@dataclass(frozen=True)
class GlobalSymbol:
    id: SymbolId
    kind: GlobalSymbolKind
    name: str
    qualified_name: str
    owner_id: SymbolId|None=None
    source: Path|None=None
    metadata: tuple[tuple[str,str],...]=()
    project_id: str|None=None
    @classmethod
    def create(cls, kind: GlobalSymbolKind, name: str, qualified_name: str, *, owner_id: SymbolId|None=None, source: Path|None=None, metadata: dict[str,str]|None=None, project_id: str|None=None)->'GlobalSymbol':
        return cls(SymbolId.from_parts(kind, qualified_name, project_id), kind, name, qualified_name, owner_id, source, tuple(sorted((metadata or {}).items())), project_id)
