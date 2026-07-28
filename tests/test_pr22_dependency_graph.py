import pytest
from moughorai.global_symbols import SymbolId
from moughorai.dependency_graph import *
def s(x): return SymbolId(x)
def e(a,b,k=DependencyKind.USES): return DependencyEdge(s(a),s(b),k)
def test_edges_deduplicated(): assert len(DependencyGraph([e('a','b'),e('a','b')]).edges)==1
def test_add():
 g=DependencyGraph();g.add(e('a','b'));assert len(g.edges)==1
def test_outgoing(): assert DependencyGraph([e('a','b')]).outgoing(s('a'))[0].target==s('b')
def test_incoming(): assert DependencyGraph([e('a','b')]).incoming(s('b'))[0].source==s('a')
def test_kind_filter(): assert not DependencyGraph([e('a','b')]).outgoing(s('a'),DependencyKind.CALLS)
def test_direct_dependencies(): assert DependencyGraph([e('a','b'),e('b','c')]).dependencies(s('a'))==(s('b'),)
def test_transitive_dependencies(): assert DependencyGraph([e('a','b'),e('b','c')]).dependencies(s('a'),True)==(s('b'),s('c'))
def test_direct_dependents(): assert DependencyGraph([e('a','b')]).dependents(s('b'))==(s('a'),)
def test_transitive_dependents(): assert DependencyGraph([e('a','b'),e('b','c')]).dependents(s('c'),True)==(s('a'),s('b'))
def test_cycle_detected(): assert DependencyGraph([e('a','b'),e('b','a')]).cycles()==((s('a'),s('b')),)
def test_self_cycle(): assert DependencyGraph([e('a','a')]).cycles()==((s('a'),),)
def test_acyclic(): assert DependencyGraph([e('a','b')]).cycles()==()
def test_store_roundtrip(tmp_path):
 g=DependencyGraph([e('a','b',DependencyKind.CALLS)]);p=tmp_path/'g.json';DependencyGraphStore().save(g,p);assert DependencyGraphStore().load(p).edges==g.edges
def test_store_schema(tmp_path):
 p=tmp_path/'g.json';p.write_text('{"schema_version":2,"edges":[]}')
 with pytest.raises(ValueError):DependencyGraphStore().load(p)
def test_edge_sorting(): assert DependencyGraph([e('z','b'),e('a','b')]).edges[0].source==s('a')
def test_multiple_kinds_distinct(): assert len(DependencyGraph([e('a','b'),e('a','b',DependencyKind.CALLS)]).edges)==2
def test_empty_graph(): assert DependencyGraph().edges==()
