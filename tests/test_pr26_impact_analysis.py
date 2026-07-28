from pathlib import Path
from moughorai.global_symbols import *
from moughorai.dependency_graph import *
from moughorai.impact_analysis import *

def s(q): return GlobalSymbol.create(GlobalSymbolKind.METHOD,q,q,source=Path(q+'.java'))
def setup():
 a,b,c,d=map(s,'ABCD'); db=GlobalSymbolDatabase([a,b,c,d]); g=DependencyGraph([DependencyEdge(b.id,a.id,DependencyKind.CALLS),DependencyEdge(c.id,b.id,DependencyKind.CALLS),DependencyEdge(d.id,a.id,DependencyKind.USES)]); return db,g,a,b,c,d

def test_direct_impact():
 db,g,a,b,c,d=setup(); r=ImpactAnalysisService(db,g).analyze([a.id],max_depth=1); assert {x.symbol for x in r.impacted}=={b,d}
def test_transitive_impact():
 db,g,a,b,c,d=setup(); assert {x.symbol for x in ImpactAnalysisService(db,g).analyze([a.id]).impacted}=={b,c,d}
def test_distance():
 db,g,a,b,c,d=setup(); r=ImpactAnalysisService(db,g).analyze([a.id]); assert next(x for x in r.impacted if x.symbol==c).distance==2
def test_path_symbols():
 db,g,a,b,c,d=setup(); x=next(x for x in ImpactAnalysisService(db,g).analyze([a.id]).impacted if x.symbol==c); assert x.path.symbols==(c.id,b.id,a.id)
def test_path_kinds():
 db,g,a,b,c,d=setup(); x=next(x for x in ImpactAnalysisService(db,g).analyze([a.id]).impacted if x.symbol==c); assert x.path.kinds==(DependencyKind.CALLS,DependencyKind.CALLS)
def test_kind_filter():
 db,g,a,b,c,d=setup(); r=ImpactAnalysisService(db,g).analyze([a.id],kinds={DependencyKind.CALLS}); assert {x.symbol for x in r.impacted}=={b,c}
def test_include_roots():
 db,g,a,*_=setup(); assert ImpactAnalysisService(db,g).analyze([a.id],include_roots=True).impacted[0].symbol==a
def test_roots_default_excluded():
 db,g,a,*_=setup(); assert all(x.symbol!=a for x in ImpactAnalysisService(db,g).analyze([a.id]).impacted)
def test_files_include_root_and_impacts():
 db,g,a,b,c,d=setup(); assert set(ImpactAnalysisService(db,g).analyze([a.id],max_depth=1).files)=={Path('A.java'),Path('B.java'),Path('D.java')}
def test_unresolved_root():
 db,g,*_=setup(); ghost=SymbolId.from_parts(GlobalSymbolKind.METHOD,'ghost'); assert ImpactAnalysisService(db,g).analyze([ghost]).unresolved_ids==(ghost,)
def test_duplicate_roots_removed():
 db,g,a,*_=setup(); assert len(ImpactAnalysisService(db,g).analyze([a.id,a.id]).roots)==1
def test_multiple_roots():
 db,g,a,b,c,d=setup(); r=ImpactAnalysisService(db,g).analyze([a.id,b.id]); assert set(r.roots)=={a,b}
def test_zero_depth():
 db,g,a,*_=setup(); assert ImpactAnalysisService(db,g).analyze([a.id],max_depth=0).impacted==()
def test_stable_distance_order():
 db,g,a,b,c,d=setup(); ds=[x.distance for x in ImpactAnalysisService(db,g).analyze([a.id]).impacted]; assert ds==sorted(ds)
def test_missing_dependent_symbol_recorded():
 db,g,a,*_=setup(); ghost=SymbolId.from_parts(GlobalSymbolKind.METHOD,'ghost'); g.add(DependencyEdge(ghost,a.id,DependencyKind.CALLS)); assert ghost in ImpactAnalysisService(db,g).analyze([a.id]).unresolved_ids
