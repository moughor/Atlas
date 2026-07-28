from pathlib import Path
import pytest
from moughorai.global_symbols import *

def sym(q='a.A',kind=GlobalSymbolKind.TYPE,source=None): return GlobalSymbol.create(kind,q.rsplit('.',1)[-1],q,source=source)
def test_ids_are_stable(): assert sym().id==sym().id
def test_kinds_change_id(): assert sym().id!=sym(kind=GlobalSymbolKind.METHOD).id
def test_lookup_by_id():
 d=GlobalSymbolDatabase([sym()]); assert d.get(sym().id)==sym()
def test_lookup_qualified(): assert GlobalSymbolDatabase([sym()]).by_qualified_name('a.A')==sym()
def test_find_simple(): assert len(GlobalSymbolDatabase([sym('a.A'),sym('b.A')]).find_simple('A'))==2
def test_by_kind(): assert len(GlobalSymbolDatabase([sym(),sym('a.m',GlobalSymbolKind.METHOD)]).by_kind(GlobalSymbolKind.METHOD))==1
def test_duplicate_rejected():
 with pytest.raises(DuplicateSymbolError): GlobalSymbolDatabase([sym(),sym()])
def test_source_lookup():
 p=Path('A.java'); assert GlobalSymbolDatabase([sym(source=p)]).by_source(p)[0].source==p
def test_remove_source():
 p=Path('A.java'); d=GlobalSymbolDatabase([sym(source=p)]); assert d.remove_source(p)==1 and not d.symbols
def test_metadata_sorted(): assert GlobalSymbol.create(GlobalSymbolKind.TYPE,'A','A',metadata={'z':'1','a':'2'}).metadata[0][0]=='a'
def test_store_roundtrip(tmp_path):
 d=GlobalSymbolDatabase([sym(source=Path('A.java'))]); p=tmp_path/'s.json'; GlobalSymbolStore().save(d,p); assert GlobalSymbolStore().load(p).symbols==d.symbols
def test_store_rejects_schema(tmp_path):
 p=tmp_path/'s.json'; p.write_text('{"schema_version":9,"symbols":[]}')
 with pytest.raises(ValueError): GlobalSymbolStore().load(p)
def test_symbols_sorted(): assert [x.qualified_name for x in GlobalSymbolDatabase([sym('z.Z'),sym('a.A')]).symbols]==['a.A','z.Z']
def test_package_symbol(): assert sym('a.b',GlobalSymbolKind.PACKAGE).kind is GlobalSymbolKind.PACKAGE
def test_string_id(): assert str(sym().id).startswith('type:')
