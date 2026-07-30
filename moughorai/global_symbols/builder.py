from __future__ import annotations
from pathlib import Path
from moughorai.java_symbols import JavaSymbolIndex, SymbolKind
from moughorai.global_symbols.models import GlobalSymbol, GlobalSymbolKind, SymbolId
from moughorai.global_symbols.database import GlobalSymbolDatabase

_MAP={SymbolKind.TYPE:GlobalSymbolKind.TYPE,SymbolKind.FIELD:GlobalSymbolKind.FIELD,SymbolKind.CONSTRUCTOR:GlobalSymbolKind.CONSTRUCTOR,SymbolKind.METHOD:GlobalSymbolKind.METHOD}
class GlobalSymbolDatabaseBuilder:
    def build(self,index:JavaSymbolIndex)->GlobalSymbolDatabase:
        out=[]; packages=set(); emitted=set()
        for s in index.symbols:
            if s.kind is SymbolKind.TYPE:
                pkg=getattr(s,'package_name','')
                if pkg: packages.add(pkg)
        for pkg in sorted(packages): out.append(GlobalSymbol.create(GlobalSymbolKind.PACKAGE,pkg.rsplit('.',1)[-1],pkg))
        known={s.qualified_name:SymbolId.from_parts(_MAP[s.kind],s.qualified_name) for s in index.symbols}
        for s in index.symbols:
            identity=(s.kind,s.qualified_name,s.source)
            if identity in emitted:
                continue
            emitted.add(identity)
            meta={}
            for attr in ('return_type','type_name'):
                if hasattr(s,attr): meta[attr]=str(getattr(s,attr))
            if hasattr(s,'parameter_types'): meta['parameter_types']=','.join(getattr(s,'parameter_types'))
            out.append(GlobalSymbol.create(_MAP[s.kind],s.name,s.qualified_name,owner_id=known.get(s.owner or ''),source=s.source,metadata=meta))
        return GlobalSymbolDatabase(out)
