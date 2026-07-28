from __future__ import annotations
from collections import defaultdict
from pathlib import Path
from typing import Iterable
from moughorai.global_symbols.models import GlobalSymbol, GlobalSymbolKind, SymbolId

class DuplicateSymbolError(ValueError): pass

class GlobalSymbolDatabase:
    def __init__(self, symbols: Iterable[GlobalSymbol]=()):
        self._by_id={}; self._by_q={}; self._by_name=defaultdict(list); self._by_source=defaultdict(list)
        for s in symbols: self.add(s)
    def add(self,s:GlobalSymbol)->None:
        if s.id in self._by_id: raise DuplicateSymbolError(str(s.id))
        if s.qualified_name in self._by_q: raise DuplicateSymbolError(s.qualified_name)
        self._by_id[s.id]=s; self._by_q[s.qualified_name]=s; self._by_name[s.name].append(s)
        if s.source is not None: self._by_source[s.source].append(s)
    def get(self, symbol_id:SymbolId)->GlobalSymbol|None: return self._by_id.get(symbol_id)
    def by_qualified_name(self,name:str)->GlobalSymbol|None: return self._by_q.get(name)
    def find_simple(self,name:str)->tuple[GlobalSymbol,...]: return tuple(self._by_name.get(name,()))
    def by_kind(self,kind:GlobalSymbolKind)->tuple[GlobalSymbol,...]: return tuple(s for s in self.symbols if s.kind is kind)
    def by_source(self,source:Path)->tuple[GlobalSymbol,...]: return tuple(self._by_source.get(source,()))
    @property
    def symbols(self)->tuple[GlobalSymbol,...]: return tuple(sorted(self._by_id.values(), key=lambda s:(s.qualified_name,s.kind.value)))
    def remove_source(self,source:Path)->int:
        doomed=list(self._by_source.pop(source,()))
        for s in doomed:
            self._by_id.pop(s.id,None); self._by_q.pop(s.qualified_name,None)
            self._by_name[s.name]=[x for x in self._by_name[s.name] if x.id!=s.id]
        return len(doomed)
