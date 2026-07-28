from __future__ import annotations

import pytest

from moughorai.interprocedural_taint import InterproceduralTaintAnalyzer, JavaMethodId, JavaProgramParser, TaintKind, TaintValue
from moughorai.java_security import JavaSourceUnit


def unit(path: str, source: str) -> JavaSourceUnit:
    return JavaSourceUnit(path, source)


def scan(*sources: tuple[str, str], entrypoints: tuple[str, ...] = ()):
    return InterproceduralTaintAnalyzer().analyze_units(tuple(unit(path, source) for path, source in sources), entrypoints)


def test_parser_extracts_package_type_method_and_fields():
    parsed = JavaProgramParser().parse_unit(unit("A.java", "package p; class A { String value; public String get(String x){ return x; } }"))
    assert parsed.qualified_name == "p.A"
    assert parsed.fields == ("value",)
    assert parsed.methods[0].parameters == ("x",)


def test_direct_interprocedural_sql_flow():
    report = scan(
        ("Controller.java", 'class Controller { @GetMapping String go(){ String x=request.getParameter("q"); return new Service().run(x); } }'),
        ("Service.java", 'class Service { String run(String x){ statement.executeQuery(x); return x; } }'),
    )
    assert [f.rule_id for f in report.findings] == ["ATLAS-SQL-001"]
    assert any("returned from Service.run/1" in s.message for s in report.findings[0].trace) is False


def test_return_flow_across_three_methods():
    report = scan(
        ("C.java", 'class C { @GetMapping void go(){ String x=request.getParameter("q"); String y=new A().one(x); statement.executeQuery(y); } }'),
        ("A.java", 'class A { String one(String x){ return new B().two(x); } }'),
        ("B.java", 'class B { String two(String x){ return x; } }'),
    )
    assert len(report.findings_for_rule("ATLAS-SQL-001")) == 1
    messages = [s.message for s in report.findings[0].trace]
    assert any("B.two/1" in message for message in messages)
    assert any("A.one/1" in message for message in messages)


def test_sanitizer_cuts_interprocedural_flow():
    report = scan(
        ("C.java", 'class C { @GetMapping void go(){ String x=request.getParameter("q"); new S().run(x); } }'),
        ("S.java", 'class S { void run(String x){ String safe=sanitize(x); statement.executeQuery(safe); } }'),
    )
    assert report.findings == ()


def test_clean_literal_does_not_report():
    report = scan(("A.java", 'class A { void go(){ statement.executeQuery("select 1"); } }'), entrypoints=("go",))
    assert report.findings == ()


def test_explicit_entrypoint_selection():
    report = scan(("A.java", 'class A { void safe(){ statement.executeQuery("x"); } void bad(){ String x=request.getParameter("q"); statement.executeQuery(x); } }'), entrypoints=("bad",))
    assert len(report.findings) == 1


def test_metrics_and_summaries_are_populated():
    report = scan(("A.java", 'class A { @GetMapping String go(){ return request.getParameter("q"); } }'))
    assert report.metrics.type_count == 1
    assert report.metrics.method_count == 1
    assert report.summaries[0].source_return


def test_unresolved_calls_are_reported_deterministically():
    report = scan(("A.java", 'class A { @GetMapping void go(){ mystery.call("x"); } }'))
    assert report.warnings == ("Unresolved call: mystery.call/1",)


def test_taint_value_merge_deduplicates_trace():
    value = TaintValue.taint("source")
    merged = TaintValue.merge(value, value)
    assert merged.kind is TaintKind.TAINTED
    assert len(merged.trace) == 1


@pytest.mark.parametrize(
    "sink,rule",
    [
        ("statement.executeQuery", "ATLAS-SQL-001"),
        ("statement.executeUpdate", "ATLAS-SQL-001"),
        ("connection.prepareStatement", "ATLAS-SQL-001"),
        ("entityManager.createNativeQuery", "ATLAS-SQL-001"),
        ("Runtime.exec", "ATLAS-CMD-001"),
        ("startProcess", "ATLAS-CMD-001"),
        ("Files.readAllBytes", "ATLAS-PATH-001"),
        ("Files.write", "ATLAS-PATH-001"),
        ("Paths.get", "ATLAS-PATH-001"),
        ("URL.openConnection", "ATLAS-SSRF-001"),
        ("HttpClient.send", "ATLAS-SSRF-001"),
        ("RestTemplate.getForObject", "ATLAS-SSRF-001"),
        ("ObjectInputStream.readObject", "ATLAS-DESER-001"),
        ("XMLDecoder.readObject", "ATLAS-DESER-001"),
        ("Class.forName", "ATLAS-REFLECT-001"),
        ("Method.invoke", "ATLAS-REFLECT-001"),
    ],
)
def test_supported_sinks(sink, rule):
    report = scan(("A.java", f'class A {{ @GetMapping void go(){{ String x=request.getParameter("q"); {sink}(x); }} }}'))
    assert report.findings[0].rule_id == rule


@pytest.mark.parametrize(
    "source",
    [
        'request.getParameter("q")',
        'request.getHeader("X")',
        'request.getQueryString()',
        'Scanner.nextLine()',
        'System.getenv("X")',
        'System.getProperty("X")',
        'reader.readLine()',
        'request.getInputStream()',
    ],
)
def test_supported_sources(source):
    report = scan(("A.java", f'class A {{ @GetMapping void go(){{ String x={source}; statement.executeQuery(x); }} }}'))
    assert len(report.findings) == 1


@pytest.mark.parametrize("sanitizer", ["sanitize", "escapeSql", "normalizePath", "validateUrl", "allowlist", "encodeForSQL"])
def test_supported_sanitizers(sanitizer):
    report = scan(("A.java", f'class A {{ @GetMapping void go(){{ String x=request.getParameter("q"); String y={sanitizer}(x); statement.executeQuery(y); }} }}'))
    assert report.findings == ()


@pytest.mark.parametrize("method_name", ["main", "go", "load", "save", "search", "execute", "handle", "process", "dispatch", "submit", "fetch"])
def test_explicit_entrypoint_names(method_name):
    report = scan(("A.java", f'class A {{ void {method_name}(){{ String x=request.getParameter("q"); statement.executeQuery(x); }} }}'), entrypoints=(method_name,))
    assert len(report.findings) == 1
