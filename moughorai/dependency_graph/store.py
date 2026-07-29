from __future__ import annotations
import json,os
from pathlib import Path
from moughorai.global_symbols import SymbolId
from .models import DependencyEdge,DependencyKind
from .graph import DependencyGraph
class DependencyGraphStore:
    SCHEMA_VERSION=1
    def save(self,g:DependencyGraph,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_name(path.name+'.tmp')
        tmp.write_text(json.dumps({'schema_version':1,'edges':[{'source':str(e.source),'target':str(e.target),'kind':e.kind.value} for e in g.edges]},indent=2,sort_keys=True),encoding='utf-8'); os.replace(tmp,path)
    def load(self,path:Path):
        p=json.loads(path.read_text(encoding='utf-8'))
        if p.get('schema_version')!=1: raise ValueError('unsupported dependency graph schema')
        return DependencyGraph(DependencyEdge(SymbolId(x['source']),SymbolId(x['target']),DependencyKind(x['kind'])) for x in p['edges'])
