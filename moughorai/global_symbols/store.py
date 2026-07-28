from __future__ import annotations
import json, os
from pathlib import Path
from moughorai.global_symbols.models import GlobalSymbol,GlobalSymbolKind,SymbolId
from moughorai.global_symbols.database import GlobalSymbolDatabase
class GlobalSymbolStore:
    SCHEMA_VERSION=1
    def save(self,db:GlobalSymbolDatabase,path:Path)->None:
        path.parent.mkdir(parents=True,exist_ok=True)
        payload={'schema_version':1,'symbols':[{'id':str(s.id),'kind':s.kind.value,'name':s.name,'qualified_name':s.qualified_name,'owner_id':str(s.owner_id) if s.owner_id else None,'source':str(s.source) if s.source else None,'metadata':dict(s.metadata)} for s in db.symbols]}
        tmp=path.with_name(path.name+'.tmp'); tmp.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding='utf-8'); os.replace(tmp,path)
    def load(self,path:Path)->GlobalSymbolDatabase:
        p=json.loads(path.read_text(encoding='utf-8'))
        if p.get('schema_version')!=1: raise ValueError('unsupported global symbol schema')
        return GlobalSymbolDatabase(GlobalSymbol(SymbolId(x['id']),GlobalSymbolKind(x['kind']),x['name'],x['qualified_name'],SymbolId(x['owner_id']) if x['owner_id'] else None,Path(x['source']) if x['source'] else None,tuple(sorted(x.get('metadata',{}).items()))) for x in p['symbols'])
