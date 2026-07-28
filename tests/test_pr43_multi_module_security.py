from pathlib import Path
import pytest
from moughorai.java_security import JavaSourceUnit
from moughorai.multi_module_security import (
    ModuleDescriptor,ModuleDiscovery,ModuleGraphBuilder,ModuleKind,MultiModuleSecurityScanner
)

def mod(name,deps=(),sources=()): return ModuleDescriptor(name,name,ModuleKind.PLAIN,tuple(deps),tuple(sources),name)

def test_descriptor_rejects_empty_name():
    with pytest.raises(ValueError): ModuleDescriptor('', 'x')
def test_descriptor_rejects_empty_root():
    with pytest.raises(ValueError): ModuleDescriptor('x', '')
def test_graph_sorts_modules(): assert [m.name for m in ModuleGraphBuilder().build((mod('b'),mod('A'))).modules]==['A','b']
def test_graph_edges(): assert ModuleGraphBuilder().build((mod('app',['core']),mod('core'))).edges==( ('app','core'), )
def test_unresolved_dependency(): assert ModuleGraphBuilder().build((mod('app',['missing']),)).unresolved_dependencies==( ('app','missing'), )
def test_dependencies_of(): assert ModuleGraphBuilder().build((mod('app',['core']),mod('core'))).dependencies_of('app')==('core',)
def test_dependents_of(): assert ModuleGraphBuilder().build((mod('app',['core']),mod('core'))).dependents_of('core')==('app',)
def test_dependency_first_order(): assert ModuleGraphBuilder().scan_order(ModuleGraphBuilder().build((mod('app',['core']),mod('core'))))==('core','app')
def test_transitive_dependencies():
    g=ModuleGraphBuilder().build((mod('api',['service']),mod('service',['core']),mod('core')))
    assert ModuleGraphBuilder().transitive_dependencies(g,'api')==('core','service')
def test_impacted_modules():
    g=ModuleGraphBuilder().build((mod('api',['service']),mod('service',['core']),mod('core')))
    assert ModuleGraphBuilder().impacted_modules(g,('core',))==('api','core','service')
def test_cycle_detection_two_nodes():
    g=ModuleGraphBuilder().build((mod('a',['b']),mod('b',['a'])))
    assert g.cycles==( ('a','b'), )
def test_self_cycle_detection(): assert ModuleGraphBuilder().build((mod('a',['a']),)).cycles==( ('a',), )
def test_cycle_order_still_complete():
    g=ModuleGraphBuilder().build((mod('b',['a']),mod('a',['b'])))
    assert set(ModuleGraphBuilder().scan_order(g))=={'a','b'}
def test_duplicate_edges_removed(): assert ModuleGraphBuilder().build((mod('a',['b','b']),mod('b'))).edges==( ('a','b'), )
def test_empty_graph():
    g=ModuleGraphBuilder().build(())
    assert g.modules==() and ModuleGraphBuilder().scan_order(g)==()

def test_plain_discovery(tmp_path):
    (tmp_path/'A.java').write_text('class A {}')
    modules=ModuleDiscovery().discover(tmp_path)
    assert len(modules)==1 and modules[0].kind==ModuleKind.PLAIN and len(modules[0].sources)==1
def test_missing_root():
    with pytest.raises(FileNotFoundError): ModuleDiscovery().discover('/definitely/missing/pr43')
def test_maven_discovery(tmp_path):
    (tmp_path/'core').mkdir(); (tmp_path/'app').mkdir()
    (tmp_path/'core'/'pom.xml').write_text('<project><artifactId>core</artifactId></project>')
    (tmp_path/'app'/'pom.xml').write_text('<project><artifactId>app</artifactId><dependencies><dependency><artifactId>core</artifactId></dependency></dependencies></project>')
    modules=ModuleDiscovery().discover(tmp_path); by={m.name:m for m in modules}
    assert by['app'].kind==ModuleKind.MAVEN and by['app'].dependencies==('core',)
def test_gradle_discovery(tmp_path):
    (tmp_path/'core').mkdir(); (tmp_path/'app').mkdir()
    (tmp_path/'core'/'build.gradle').write_text('plugins {}')
    (tmp_path/'app'/'build.gradle').write_text("dependencies { implementation project(':core') }")
    modules=ModuleDiscovery().discover(tmp_path); by={m.name:m for m in modules}
    assert by['app'].dependencies==('core',)
def test_relative_source_paths(tmp_path):
    (tmp_path/'m').mkdir(); (tmp_path/'m'/'pom.xml').write_text('<project><artifactId>m</artifactId></project>')
    (tmp_path/'m'/'src').mkdir(); (tmp_path/'m'/'src'/'X.java').write_text('class X {}')
    assert ModuleDiscovery().discover(tmp_path)[0].sources[0].path=='m/src/X.java'
def test_scanner_empty_module():
    r=MultiModuleSecurityScanner().scan((mod('a'),))
    assert r.metrics.module_count==1 and r.metrics.source_files==0 and r.report.statistics.finding_count==0
def test_scanner_module_order():
    r=MultiModuleSecurityScanner().scan((mod('app',['core']),mod('core')))
    assert r.scan_order==('core','app') and [x.module for x in r.module_results]==['core','app']
def test_scanner_metrics():
    r=MultiModuleSecurityScanner().scan((mod('app',['core'],(JavaSourceUnit('A.java','class A {}'),)),mod('core')))
    assert (r.metrics.module_count,r.metrics.source_files,r.metrics.dependency_edges)==(2,1,1)
def test_scanner_unresolved_metrics():
    r=MultiModuleSecurityScanner().scan((mod('app',['missing']),))
    assert r.metrics.unresolved_dependencies==1
def test_scanner_cycle_metrics():
    r=MultiModuleSecurityScanner().scan((mod('a',['b']),mod('b',['a'])))
    assert r.metrics.cycle_count==1
def test_security_findings_are_aggregated():
    src='class A { void x(String q) throws Exception { java.sql.Statement s=null; s.executeQuery("select "+q); } }'
    r=MultiModuleSecurityScanner().scan((mod('a',sources=(JavaSourceUnit('a/A.java',src),)),))
    assert r.report.statistics.finding_count==len(r.report.findings)
def test_per_module_source_count():
    r=MultiModuleSecurityScanner().scan((mod('a',sources=(JavaSourceUnit('A.java','class A {}'),JavaSourceUnit('B.java','class B {}'))),))
    assert r.module_results[0].source_files==2

def test_by_name(): assert set(ModuleGraphBuilder().build((mod('a'),mod('b'))).by_name())=={'a','b'}

@pytest.mark.parametrize('name',[f'module-{i:02d}' for i in range(23)])
def test_single_module_graph_invariants(name):
    g=ModuleGraphBuilder().build((mod(name),))
    assert g.modules[0].name==name and g.edges==() and g.cycles==() and ModuleGraphBuilder().scan_order(g)==(name,)
