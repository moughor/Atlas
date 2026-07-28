from __future__ import annotations
from pathlib import Path
from moughorai.project_index import IndexChangeSet
from moughorai.global_symbols import GlobalSymbolDatabase,SymbolId
from moughorai.dependency_graph import DependencyGraph
from .models import IncrementalAnalysisPlan
class IncrementalAnalysisPlanner:
    def plan(self,changes:IndexChangeSet,symbols:GlobalSymbolDatabase,graph:DependencyGraph)->IncrementalAnalysisPlan:
        changed=tuple(sorted(changes.added+changes.modified,key=lambda p:p.as_posix().casefold())); removed=tuple(sorted(changes.removed,key=lambda p:p.as_posix().casefold()))
        direct={s.id for p in changed+removed for s in symbols.by_source(p)}
        impacted=set(direct)
        for sid in tuple(direct): impacted.update(graph.dependents(sid,transitive=True))
        files=set(changed)
        for sid in impacted:
            symbol=symbols.get(sid)
            if symbol and symbol.source is not None and symbol.source not in removed: files.add(symbol.source)
        return IncrementalAnalysisPlan(changed,removed,tuple(sorted(direct,key=str)),tuple(sorted(impacted,key=str)),tuple(sorted(files,key=lambda p:p.as_posix().casefold())))
