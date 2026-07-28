from pathlib import Path
import json
import pytest
from moughorai.java_security import JavaSourceUnit
from moughorai.incremental_security import IncrementalCache, IncrementalCacheStore, IncrementalJavaSecurityScanner

VULN='''class App { void run(HttpServletRequest request) throws Exception { String cmd=request.getParameter("cmd"); Runtime.getRuntime().exec(cmd); } }'''
SAFE='''class Safe { void run() { String value="ok"; System.out.println(value); } }'''

def unit(path,source): return JavaSourceUnit(path,source)

def test_first_scan_analyzes_all():
 r=IncrementalJavaSecurityScanner().scan((unit('App.java',VULN),unit('Safe.java',SAFE)))
 assert r.metrics.analyzed_files==2 and r.metrics.reused_files==0 and len(r.report.findings)==1

def test_second_scan_reuses_all():
 s=IncrementalJavaSecurityScanner(); a=s.scan((unit('App.java',VULN),)); b=s.scan((unit('App.java',VULN),),a.cache)
 assert b.analyzed_paths==() and b.reused_paths==('App.java',) and b.metrics.cache_hit_ratio==1.0

def test_changed_file_reanalyzed():
 s=IncrementalJavaSecurityScanner(); a=s.scan((unit('A.java',SAFE),)); b=s.scan((unit('A.java',VULN),),a.cache)
 assert b.analyzed_paths==('A.java',) and len(b.report.findings)==1

def test_removed_file_report_disappears():
 s=IncrementalJavaSecurityScanner(); a=s.scan((unit('A.java',VULN),)); b=s.scan((),a.cache)
 assert b.removed_paths==('A.java',) and not b.report.findings and b.metrics.removed_files==1

def test_force_reanalyzes():
 s=IncrementalJavaSecurityScanner(); a=s.scan((unit('A.java',SAFE),)); b=s.scan((unit('A.java',SAFE),),a.cache,force=True)
 assert b.analyzed_paths==('A.java',)

def test_analyzer_key_invalidates_cache():
 a=IncrementalJavaSecurityScanner(analyzer_key='a').scan((unit('A.java',SAFE),))
 b=IncrementalJavaSecurityScanner(analyzer_key='b').scan((unit('A.java',SAFE),),a.cache)
 assert b.metrics.analyzed_files==1

def test_empty_scan_hit_ratio():
 r=IncrementalJavaSecurityScanner().scan(())
 assert r.metrics.cache_hit_ratio==1.0

def test_dependency_change_invalidates_dependent():
 s=IncrementalJavaSecurityScanner(); src=(unit('Base.java','class Base {}'),unit('Child.java','class Child extends Base {}'))
 a=s.scan(src); b=s.scan((unit('Base.java','class Base { int x; }'),src[1]),a.cache)
 assert b.analyzed_paths==('Base.java','Child.java')

def test_transitive_invalidation():
 s=IncrementalJavaSecurityScanner(); src=(unit('A.java','class A {}'),unit('B.java','class B extends A {}'),unit('C.java','class C extends B {}'))
 a=s.scan(src); b=s.scan((unit('A.java','class A { int x; }'),src[1],src[2]),a.cache)
 assert b.analyzed_paths==('A.java','B.java','C.java')

def test_unrelated_file_is_reused():
 s=IncrementalJavaSecurityScanner(); src=(unit('A.java','class A {}'),unit('B.java','class B {}'))
 a=s.scan(src); b=s.scan((unit('A.java','class A { int x; }'),src[1]),a.cache)
 assert b.reused_paths==('B.java',)

def test_new_dependency_is_recorded():
 r=IncrementalJavaSecurityScanner().scan((unit('A.java','class A {}'),unit('B.java','class B { A a = new A(); }')))
 assert r.cache.by_path()['B.java'].dependencies==('A.java',)

def test_import_dependency_is_recorded():
 r=IncrementalJavaSecurityScanner().scan((unit('Foo.java','class Foo {}'),unit('Bar.java','import x.Foo; class Bar {}')))
 assert r.cache.by_path()['Bar.java'].dependencies==('Foo.java',)

def test_deterministic_path_order():
 r=IncrementalJavaSecurityScanner().scan((unit('z/Z.java',SAFE),unit('a/A.java',SAFE)))
 assert tuple(e.path for e in r.cache.entries)==('a/A.java','z/Z.java')

def test_deterministic_finding_order():
 r=IncrementalJavaSecurityScanner().scan((unit('z/Z.java',VULN.replace('App','Z')),unit('a/A.java',VULN.replace('App','A'))))
 assert tuple(f.location.path for f in r.report.findings)==('a/A.java','z/Z.java')

def test_fingerprint_stable():
 s=IncrementalJavaSecurityScanner(); assert s.fingerprint('abc')==s.fingerprint('abc')

def test_fingerprint_changes():
 s=IncrementalJavaSecurityScanner(); assert s.fingerprint('abc')!=s.fingerprint('abd')

def test_cache_json_round_trip():
 s=IncrementalJavaSecurityScanner(); r=s.scan((unit('App.java',VULN),)); restored=IncrementalCacheStore.loads(IncrementalCacheStore.dumps(r.cache))
 assert restored==r.cache

def test_cache_json_is_deterministic():
 s=IncrementalJavaSecurityScanner(); r=s.scan((unit('B.java',SAFE),unit('A.java',SAFE)))
 assert IncrementalCacheStore.dumps(r.cache)==IncrementalCacheStore.dumps(r.cache)

def test_cache_store_file_round_trip(tmp_path):
 store=IncrementalCacheStore(); cache=IncrementalJavaSecurityScanner().scan((unit('A.java',SAFE),)).cache; p=tmp_path/'cache.json'; store.save(cache,p)
 assert store.load(p)==cache and p.read_text().endswith('\n')

def test_missing_cache_file_returns_empty(tmp_path):
 assert IncrementalCacheStore().load(tmp_path/'missing.json')==IncrementalCache()

def test_invalid_json_raises():
 with pytest.raises(json.JSONDecodeError): IncrementalCacheStore.loads('{')

def test_cache_path_created(tmp_path):
 p=tmp_path/'nested'/'cache.json'; IncrementalCacheStore().save(IncrementalCache(),p); assert p.exists()

def test_cache_version_invalidates():
 s=IncrementalJavaSecurityScanner(); a=s.scan((unit('A.java',SAFE),)); bad=IncrementalCache(2,a.cache.analyzer_key,a.cache.entries); b=s.scan((unit('A.java',SAFE),),bad)
 assert b.metrics.analyzed_files==1

def test_warning_reused():
 s=IncrementalJavaSecurityScanner(); src='class A { void x(){ ???; } }'; a=s.scan((unit('A.java',src),)); b=s.scan((unit('A.java',src),),a.cache)
 assert b.report.warnings==a.report.warnings

def test_statistics_rebuilt_from_entries():
 r=IncrementalJavaSecurityScanner().scan((unit('A.java',VULN),)); assert r.report.statistics.finding_count==len(r.report.findings)==1

def test_invalidated_paths_include_changed():
 s=IncrementalJavaSecurityScanner(); a=s.scan((unit('A.java',SAFE),)); b=s.scan((unit('A.java',SAFE+' '),),a.cache)
 assert b.invalidated_paths==('A.java',)

def test_removed_dependency_invalidates_dependent():
 s=IncrementalJavaSecurityScanner(); a=s.scan((unit('A.java','class A {}'),unit('B.java','class B extends A {}'))); b=s.scan((unit('B.java','class B extends A {}'),),a.cache)
 assert b.analyzed_paths==('B.java',) and b.removed_paths==('A.java',)

def test_same_content_different_path_is_not_reused():
 s=IncrementalJavaSecurityScanner(); a=s.scan((unit('A.java',SAFE),)); b=s.scan((unit('B.java',SAFE),),a.cache)
 assert b.analyzed_paths==('B.java',)

def test_finding_location_preserved_after_cache():
 s=IncrementalJavaSecurityScanner(); a=s.scan((unit('src/App.java',VULN),)); b=s.scan((unit('src/App.java',VULN),),a.cache)
 assert b.report.findings[0].location.path=='src/App.java'

def test_properties_preserved_after_serialization():
 s=IncrementalJavaSecurityScanner(); cache=s.scan((unit('App.java',VULN),)).cache; restored=IncrementalCacheStore.loads(IncrementalCacheStore.dumps(cache))
 assert restored.entries[0].findings[0].properties==cache.entries[0].findings[0].properties

def test_trace_preserved_after_serialization():
 s=IncrementalJavaSecurityScanner(); cache=s.scan((unit('App.java',VULN),)).cache; restored=IncrementalCacheStore.loads(IncrementalCacheStore.dumps(cache))
 assert restored.entries[0].findings[0].trace==cache.entries[0].findings[0].trace

@pytest.mark.parametrize('source,expected',[
 ('class A {}',()),
 ('interface A {}',()),
 ('record A(int x) {}',()),
 ('enum A { X }',()),
 ('class B extends A {}',('A',)),
 ('class B implements A {}',('A',)),
 ('class B { A a=new A(); }',('A',)),
 ('class B { boolean x(Object o){ return o instanceof A; }}',('A',)),
])
def test_dependency_extraction(source,expected):
 assert IncrementalJavaSecurityScanner._dependencies(source)==expected

@pytest.mark.parametrize('path,source,name',[
 ('A.java','class A {}','A'),('B.java','interface B {}','B'),('C.java','enum C {}','C'),('D.java','record D() {}','D'),('pkg/Fallback.java','// none','Fallback')
])
def test_type_name(path,source,name): assert IncrementalJavaSecurityScanner._type_name(path,source)==name

@pytest.mark.parametrize('count',range(1,8))
def test_many_unchanged_files_reused(count):
 s=IncrementalJavaSecurityScanner(); sources=tuple(unit(f'A{i}.java',f'class A{i} {{}}') for i in range(count)); a=s.scan(sources); b=s.scan(sources,a.cache)
 assert b.metrics.reused_files==count and b.metrics.analyzed_files==0
