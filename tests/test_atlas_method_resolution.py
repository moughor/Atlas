from moughorai.passes import (
    METHOD_AMBIGUOUS, METHOD_INCOMPATIBLE_ARGUMENT, METHOD_NOT_FOUND,
    METHOD_STATIC_CONTEXT_MISMATCH, MethodSignature, resolve_constructor, resolve_method,
)
from moughorai.semantic.types import TypeRegistry

R = TypeRegistry()

def sig(name, params, result="void", **kwargs):
    def t(value):
        if value in {"boolean", "byte", "short", "char", "int", "long", "float", "double"}:
            return R.primitive(value)
        return R.void if value == "void" else R.class_type(value)
    return MethodSignature("Example", name, tuple(t(x) for x in params), t(result), **kwargs)

def test_exact_overload_wins():
    candidates = [sig("pick", ["int"], "int"), sig("pick", ["long"], "long")]
    result = resolve_method("Example", "pick", [R.primitive("int")], candidates)
    assert result.selected == candidates[0]

def test_primitive_widening_is_supported():
    candidate = sig("accept", ["long"])
    result = resolve_method("Example", "accept", [R.primitive("int")], [candidate])
    assert result.selected == candidate

def test_boxing_is_supported():
    candidate = sig("accept", ["java.lang.Integer"])
    assert resolve_method("Example", "accept", [R.primitive("int")], [candidate]).selected == candidate

def test_varargs_are_ranked_after_fixed_arity():
    fixed = sig("join", ["int", "int"])
    varargs = sig("join", ["int"], is_varargs=True)
    result = resolve_method("Example", "join", [R.primitive("int"), R.primitive("int")], [varargs, fixed])
    assert result.selected == fixed

def test_ambiguous_overloads_report_diagnostic():
    a = sig("pick", ["Object"])
    b = sig("pick", ["java.lang.Object"])
    result = resolve_method("Example", "pick", [R.null], [a, b])
    assert result.diagnostics[0].code == METHOD_AMBIGUOUS

def test_missing_and_incompatible_calls_are_distinct():
    missing = resolve_method("Example", "missing", [], [])
    incompatible = resolve_method("Example", "pick", [R.class_type("String")], [sig("pick", ["int"])])
    assert missing.diagnostics[0].code == METHOD_NOT_FOUND
    assert incompatible.diagnostics[0].code == METHOD_INCOMPATIBLE_ARGUMENT

def test_static_context_is_checked():
    instance = sig("work", [], is_static=False)
    result = resolve_method("Example", "work", [], [instance], static_context=True)
    assert result.diagnostics[0].code == METHOD_STATIC_CONTEXT_MISMATCH

def test_constructor_resolution():
    constructor = sig("<init>", ["int"], result="Example", is_constructor=True)
    assert resolve_constructor("Example", [R.primitive("byte")], [constructor]).selected == constructor