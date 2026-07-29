import pytest

from moughorai.cross_language import Language, build_workspace, language_for_path, parse_source


@pytest.mark.parametrize("path,language", [
    ("A.java", Language.JAVA), ("A.kt", Language.KOTLIN), ("build.kts", Language.KOTLIN),
    ("A.scala", Language.SCALA), ("A.groovy", Language.GROOVY),
])
def test_language_detection(path, language):
    assert language_for_path(path) is language


def test_unsupported_language():
    with pytest.raises(ValueError): language_for_path("a.py")


@pytest.mark.parametrize("path,source,package,name", [
    ("A.java", "package a.b; class A {}", "a.b", "A"),
    ("A.kt", "package a.b\nclass A {}", "a.b", "A"),
    ("A.scala", "package a.b\nclass A {}", "a.b", "A"),
    ("A.groovy", "package a.b\nclass A {}", "a.b", "A"),
])
def test_type_parsing(path, source, package, name):
    module = parse_source(path, source)
    assert module.package == package
    assert module.types[0].simple_name == name
    assert module.types[0].qualified_name == f"{package}.{name}"


@pytest.mark.parametrize("path,source,expected", [
    ("A.java", "import java.util.List;\nclass A {}", ("java.util.List",)),
    ("A.kt", "import java.util.List\nclass A {}", ("java.util.List",)),
    ("A.scala", "import java.util.List\nclass A {}", ("java.util.List",)),
    ("A.groovy", "import java.util.List\nclass A {}", ("java.util.List",)),
])
def test_imports(path, source, expected):
    assert parse_source(path, source).imports == expected


def test_java_method():
    m = parse_source("A.java", "package p; class A { public String hi(String name) { return name; } }")
    f = m.types[0].functions[0]
    assert (f.name, f.arity, f.return_type, f.parameters[0].name) == ("hi", 1, "String", "name")
    assert f.returns == ("name",)


def test_kotlin_method():
    m = parse_source("A.kt", "package p\nclass A { fun hi(name: String): String { return name } }")
    f = m.types[0].functions[0]
    assert (f.name, f.parameters[0].type_name, f.return_type) == ("hi", "String", "String")


def test_scala_method():
    m = parse_source("A.scala", "package p\nclass A { def hi(name: String): String = { return name } }")
    f = m.types[0].functions[0]
    assert (f.name, f.parameters[0].name, f.return_type) == ("hi", "name", "String")


def test_groovy_method():
    m = parse_source("A.groovy", "package p\nclass A { def hi(String name) { return name } }")
    f = m.types[0].functions[0]
    assert (f.name, f.parameters[0].name) == ("hi", "name")


@pytest.mark.parametrize("path,source", [
    ("Top.kt", "package p\nfun greet(name: String): String { return name }"),
    ("Top.scala", "package p\ndef greet(name: String): String = { return name }"),
    ("Top.groovy", "package p\ndef greet(String name) { return name }"),
])
def test_top_level_functions(path, source):
    m = parse_source(path, source)
    assert m.top_level_functions[0].name == "greet"


def test_annotations_on_type_and_function():
    m = parse_source("A.kt", "package p\n@RestController class A { @GetMapping fun x(): String { return \"x\" } }")
    assert m.types[0].annotations == ("RestController",)
    assert m.types[0].functions[0].annotations == ("GetMapping",)


def test_parameter_annotations():
    m = parse_source("A.java", "class A { String x(@RequestParam String q) { return q; } }")
    assert m.types[0].functions[0].parameters[0].annotations == ("RequestParam",)


def test_calls_and_arguments():
    m = parse_source("A.java", "class A { void x(String q) { service.save(q, 1); } }")
    call = m.types[0].functions[0].calls[0]
    assert (call.receiver, call.name, call.arguments, call.arity) == ("service", "save", ("q", "1"), 2)


def test_assignments():
    m = parse_source("A.kt", "class A { fun x(q: String) { val y = q.trim() } }")
    assignment = m.types[0].functions[0].assignments[0]
    assert assignment.target == "y"
    assert assignment.expression == "q.trim()"


def test_compact_single_line_source():
    m = parse_source("A.java", "class A{String a(String x){return x;}String b(){return a(\"x\");}}")
    assert [f.name for f in m.types[0].functions] == ["a", "b"]


def test_no_declarations_diagnostic():
    m = parse_source("A.kt", "package p\n// empty")
    assert m.diagnostics == ("no declarations found in A.kt",)


def test_source_spans():
    m = parse_source("A.kt", "package p\n\nclass A {\n fun x() {\n println(1)\n }\n}")
    f = m.types[0].functions[0]
    assert f.span.line == 4
    assert f.calls[0].span.line == 5


def test_modifiers():
    m = parse_source("A.java", "class A { public static final String x() { return \"x\"; } }")
    assert m.types[0].functions[0].modifiers == ("public", "static", "final")


def test_supertypes_java():
    m = parse_source("A.java", "class A extends B implements C, D {}")
    assert "B" in m.types[0].supertypes


def test_workspace_metrics():
    w = build_workspace({"A.java": "class A { void x(){} }", "B.kt": "class B { fun y(){} }"})
    assert w.metrics.module_count == 2
    assert w.metrics.type_count == 2
    assert w.metrics.function_count == 2
    assert w.metrics.languages == ("java", "kotlin")


def test_cross_language_call_edge_java_to_kotlin():
    w = build_workspace({
        "A.java": "class A { String run(String q) { return process(q); } }",
        "B.kt": "class B { fun process(q: String): String { return q } }",
    })
    assert len(w.call_edges) == 1
    assert w.call_edges[0].caller.endswith("A.run/1")
    assert w.call_edges[0].callee.endswith("B.process/1")


def test_cross_language_call_edge_kotlin_to_scala():
    w = build_workspace({
        "A.kt": "class A { fun run(q: String): String { return convert(q) } }",
        "B.scala": "class B { def convert(q: String): String = { return q } }",
    })
    assert len(w.call_edges) == 1


def test_cross_language_call_edge_scala_to_groovy():
    w = build_workspace({
        "A.scala": "class A { def run(q: String): String = { return clean(q) } }",
        "B.groovy": "class B { def clean(String q) { return q } }",
    })
    assert len(w.call_edges) == 1


def test_ambiguous_call_fans_out_deterministically():
    w = build_workspace({
        "A.java": "class A { void run(String q) { save(q); } }",
        "B.kt": "class B { fun save(q: String) {} }",
        "C.scala": "class C { def save(q: String) = {} }",
    })
    assert len(w.call_edges) == 2
    assert [e.callee for e in w.call_edges] == sorted(e.callee for e in w.call_edges)


def test_unresolved_calls():
    w = build_workspace({"A.java": "class A { void run(String q) { missing(q); } }"})
    assert len(w.unresolved_calls) == 1
    assert "missing/1" in w.unresolved_calls[0]


def test_builtin_calls_not_reported_unresolved():
    w = build_workspace({"A.kt": "class A { fun run() { println(1) } }"})
    assert w.unresolved_calls == ()


def test_workspace_function_lookup():
    w = build_workspace({"A.java": "package p; class A { void run(){} }"})
    assert w.function("p.A.run/0").name == "run"
    assert w.function("missing") is None


def test_workspace_functions_named():
    w = build_workspace({"A.java": "class A { void run(){} }", "B.kt": "class B { fun run(){} }"})
    assert len(w.functions_named("run")) == 2


def test_workspace_determinism():
    sources = {"B.kt": "class B { fun b(){} }", "A.java": "class A { void a(){} }"}
    a = build_workspace(sources)
    b = build_workspace(dict(reversed(list(sources.items()))))
    assert a == b


def test_module_functions_sorted():
    m = parse_source("A.java", "class A { void z(){} void a(){} }")
    assert [f.name for f in m.functions] == ["a", "z"]


def test_qualified_names_include_arity():
    m = parse_source("A.kt", "package p\nclass A { fun x(a: String, b: Int){} }")
    assert m.types[0].functions[0].qualified_name == "p.A.x/2"


def test_multiple_types():
    m = parse_source("A.java", "class B {} class A {}")
    assert [t.simple_name for t in m.types] == ["A", "B"]


def test_interface_kind():
    assert parse_source("A.java", "interface A {}").types[0].kind == "interface"


def test_kotlin_object_kind():
    assert parse_source("A.kt", "object A {}").types[0].kind == "object"


def test_scala_trait_kind():
    assert parse_source("A.scala", "trait A {}").types[0].kind == "trait"


def test_call_edge_location():
    w = build_workspace({
        "A.java": "class A {\n void run() { target(); }\n}",
        "B.java": "class B { void target(){} }",
    })
    assert w.call_edges[0].path == "A.java"
    assert w.call_edges[0].line == 2


def test_metrics_unresolved_count():
    w = build_workspace({"A.java": "class A { void run(){ nope(); } }"})
    assert w.metrics.unresolved_call_count == 1


def test_metrics_edge_count():
    w = build_workspace({"A.java": "class A { void a(){ b(); } void b(){} }"})
    assert w.metrics.call_edge_count == 1


def test_explicit_language_override():
    m = parse_source("strange.txt", "class A { void x(){} }", Language.JAVA)
    assert m.language is Language.JAVA


def test_empty_workspace():
    w = build_workspace({})
    assert w.metrics.module_count == 0
    assert w.call_edges == ()


def test_return_order_preserved():
    m = parse_source("A.java", "class A { String x(boolean ok){ if(ok){return \"a\";} return \"b\";} }")
    assert m.types[0].functions[0].returns == ('"a"', '"b"')


def test_receiver_call_resolution_by_type_name():
    w = build_workspace({
        "A.java": "class A { void run(B b){ b.save(); } }",
        "B.java": "class B { void save(){} }",
    })
    assert any(edge.callee.endswith("B.save/0") for edge in w.call_edges)
