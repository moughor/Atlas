from pathlib import Path
from moughorai.project_index import IndexChangeSet
from moughorai.global_symbols import *
from moughorai.dependency_graph import *
from moughorai.incremental_analysis import *
def gs(q,p): return GlobalSymbol.create(GlobalSymbolKind.TYPE,q.split('.')[-1],q,source=Path(p))
def setup():
 a,b,c=gs('A','A.java'),gs('B','B.java'),gs('C','C.java');db=GlobalSymbolDatabase([a,b,c]);g=DependencyGraph([DependencyEdge(b.id,a.id,DependencyKind.USES),DependencyEdge(c.id,b.id,DependencyKind.USES)]);return a,b,c,db,g
def test_noop():
 *_,db,g=setup();assert IncrementalAnalysisPlanner().plan(IndexChangeSet(),db,g).is_noop
def test_modified_file():
 a,b,c,db,g=setup();p=IncrementalAnalysisPlanner().plan(IndexChangeSet(modified=(Path('A.java'),)),db,g);assert p.files_to_analyze==(Path('A.java'),Path('B.java'),Path('C.java'))
def test_added_unknown_file():
 *_,db,g=setup();p=IncrementalAnalysisPlanner().plan(IndexChangeSet(added=(Path('New.java'),)),db,g);assert p.files_to_analyze==(Path('New.java'),)
def test_removed_not_reanalyzed():
 a,b,c,db,g=setup();p=IncrementalAnalysisPlanner().plan(IndexChangeSet(removed=(Path('A.java'),)),db,g);assert Path('A.java') not in p.files_to_analyze
def test_removed_impacts_dependents():
 a,b,c,db,g=setup();p=IncrementalAnalysisPlanner().plan(IndexChangeSet(removed=(Path('A.java'),)),db,g);assert p.files_to_analyze==(Path('B.java'),Path('C.java'))
def test_direct_symbols():
 a,b,c,db,g=setup();p=IncrementalAnalysisPlanner().plan(IndexChangeSet(modified=(Path('A.java'),)),db,g);assert p.directly_changed_symbols==(a.id,)
def test_impacted_symbols_transitive():
 a,b,c,db,g=setup();p=IncrementalAnalysisPlanner().plan(IndexChangeSet(modified=(Path('A.java'),)),db,g);assert set(p.impacted_symbols)=={a.id,b.id,c.id}
def test_unrelated_change_stays_local():
 a,b,c,db,g=setup();p=IncrementalAnalysisPlanner().plan(IndexChangeSet(modified=(Path('C.java'),)),db,g);assert p.files_to_analyze==(Path('C.java'),)
def test_changed_files_sorted():
 *_,db,g=setup();p=IncrementalAnalysisPlanner().plan(IndexChangeSet(modified=(Path('z'),Path('A'))),db,g);assert p.changed_files==(Path('A'),Path('z'))
def test_state_saved(tmp_path):
 *_,db,g=setup();plan=IncrementalAnalysisPlanner().plan(IndexChangeSet(modified=(Path('A.java'),)),db,g);p=tmp_path/'state.json';IncrementalStateStore().save(plan,p);assert 'files_to_analyze' in p.read_text()
def test_empty_graph_only_direct():
 a,b,c,db,g=setup();p=IncrementalAnalysisPlanner().plan(IndexChangeSet(modified=(Path('A.java'),)),db,DependencyGraph());assert p.files_to_analyze==(Path('A.java'),)
def test_multiple_changed_union():
 a,b,c,db,g=setup();p=IncrementalAnalysisPlanner().plan(IndexChangeSet(modified=(Path('A.java'),Path('C.java'))),db,g);assert len(p.files_to_analyze)==3
def test_removed_recorded():
 *_,db,g=setup();p=IncrementalAnalysisPlanner().plan(IndexChangeSet(removed=(Path('A.java'),)),db,g);assert p.removed_files==(Path('A.java'),)
def test_plan_frozen():
 import dataclasses;assert IncrementalAnalysisPlan.__dataclass_params__.frozen
def test_noop_false_on_removed(): assert not IncrementalAnalysisPlan(removed_files=(Path('x'),)).is_noop
