import json

import pytest

from moughorai.call_graph import (
    CallGraphBuilder,
    CallGraphService,
    CallSite,
    CallSiteKind,
    DispatchKind,
    MethodId,
    MethodSymbol,
    ResolutionStatus,
    TypeHierarchy,
    TypeKind,
    TypeSymbol,
)


def mid(owner: str, name: str, descriptor: str = "()") -> MethodId:
    return MethodId(owner, name, descriptor)


def method(owner: str, name: str, descriptor: str = "()", **kwargs) -> MethodSymbol:
    return MethodSymbol(mid(owner, name, descriptor), **kwargs)


def site(caller: MethodId, owner: str, name: str, descriptor: str = "()", **kwargs) -> CallSite:
    return CallSite(caller, owner, name, descriptor, **kwargs)


def basic_report():
    types = [
        TypeSymbol("app.Controller"),
        TypeSymbol("app.Service"),
        TypeSymbol("app.Repository"),
    ]
    methods = [
        method("app.Controller", "handle"),
        method("app.Service", "process"),
        method("app.Repository", "save"),
    ]
    sites = [
        site(mid("app.Controller", "handle"), "app.Service", "process"),
        site(mid("app.Service", "process"), "app.Repository", "save"),
    ]
    return CallGraphService().build(types, methods, sites)


def test_method_id_has_stable_qualified_name():
    assert mid("a.B", "run", "(I)V").qualified_name == "a.B#run(I)V"


def test_method_id_rejects_blank_parts():
    with pytest.raises(ValueError):
        MethodId("", "run")


def test_type_symbol_normalizes_interfaces():
    symbol = TypeSymbol("x.C", interfaces=("x.B", "x.A", "x.A"))
    assert symbol.interfaces == ("x.A", "x.B")


def test_hierarchy_lists_direct_and_transitive_subtypes():
    hierarchy = TypeHierarchy([
        TypeSymbol("A", abstract=True),
        TypeSymbol("B", super_type="A"),
        TypeSymbol("C", super_type="B"),
    ])
    assert hierarchy.direct_subtypes("A") == ("B",)
    assert hierarchy.subtypes("A") == ("B", "C")


def test_hierarchy_lists_supertypes():
    hierarchy = TypeHierarchy([
        TypeSymbol("I", kind=TypeKind.INTERFACE),
        TypeSymbol("A"),
        TypeSymbol("B", super_type="A", interfaces=("I",)),
    ])
    assert hierarchy.supertypes("B") == ("A", "I")
    assert hierarchy.is_subtype("B", "I")


def test_hierarchy_returns_concrete_subtypes_only():
    hierarchy = TypeHierarchy([
        TypeSymbol("I", kind=TypeKind.INTERFACE),
        TypeSymbol("A", super_type="I", abstract=True),
        TypeSymbol("B", super_type="A"),
    ])
    assert hierarchy.concrete_subtypes("I") == ("B",)


def test_hierarchy_rejects_duplicate_types():
    with pytest.raises(ValueError, match="duplicate type"):
        TypeHierarchy([TypeSymbol("A"), TypeSymbol("A")])


def test_builds_direct_static_call():
    caller = method("A", "main", static=True)
    callee = method("B", "work", static=True)
    report = CallGraphBuilder().build(
        types=[TypeSymbol("A"), TypeSymbol("B")],
        methods=[caller, callee],
        call_sites=[site(caller.id, "B", "work", dispatch=DispatchKind.STATIC)],
    )
    assert report.graph.callees(caller.id) == (callee.id,)
    assert report.resolutions[0].status is ResolutionStatus.RESOLVED


def test_special_dispatch_resolves_inherited_method():
    caller = method("B", "run")
    parent = method("A", "base")
    report = CallGraphBuilder().build(
        types=[TypeSymbol("A"), TypeSymbol("B", super_type="A")],
        methods=[caller, parent],
        call_sites=[site(caller.id, "B", "base", dispatch=DispatchKind.SPECIAL)],
    )
    assert report.graph.callees(caller.id) == (parent.id,)
    assert report.resolutions[0].reason == "resolved on supertype"


def test_virtual_dispatch_finds_overrides():
    caller = method("Client", "run")
    base = method("Service", "execute", abstract=True)
    impl_a = method("FastService", "execute")
    impl_b = method("SafeService", "execute")
    report = CallGraphBuilder().build(
        types=[
            TypeSymbol("Client"),
            TypeSymbol("Service", abstract=True),
            TypeSymbol("FastService", super_type="Service"),
            TypeSymbol("SafeService", super_type="Service"),
        ],
        methods=[caller, base, impl_a, impl_b],
        call_sites=[site(caller.id, "Service", "execute")],
    )
    assert report.graph.callees(caller.id) == (impl_a.id, impl_b.id)
    assert report.resolutions[0].status is ResolutionStatus.POLYMORPHIC


def test_interface_dispatch_finds_implementations():
    caller = method("Client", "run")
    contract = method("Port", "send", abstract=True)
    impl = method("Adapter", "send")
    report = CallGraphBuilder().build(
        types=[
            TypeSymbol("Client"),
            TypeSymbol("Port", kind=TypeKind.INTERFACE, abstract=True),
            TypeSymbol("Adapter", interfaces=("Port",)),
        ],
        methods=[caller, contract, impl],
        call_sites=[site(caller.id, "Port", "send", dispatch=DispatchKind.INTERFACE)],
    )
    assert report.graph.callees(caller.id) == (impl.id,)


def test_virtual_dispatch_uses_inherited_concrete_implementation():
    caller = method("Client", "run")
    base = method("Base", "execute")
    report = CallGraphBuilder().build(
        types=[TypeSymbol("Client"), TypeSymbol("Base"), TypeSymbol("Child", super_type="Base")],
        methods=[caller, base],
        call_sites=[site(caller.id, "Child", "execute")],
    )
    assert report.graph.callees(caller.id) == (base.id,)


def test_unknown_receiver_becomes_external_target():
    caller = method("A", "run")
    report = CallGraphBuilder().build(
        types=[TypeSymbol("A")], methods=[caller],
        call_sites=[site(caller.id, "third.party.Client", "send")],
    )
    target = mid("third.party.Client", "send")
    assert report.graph.method(target).external is True
    assert report.resolutions[0].status is ResolutionStatus.EXTERNAL


def test_external_targets_can_be_excluded():
    caller = method("A", "run")
    report = CallGraphBuilder().build(
        types=[TypeSymbol("A")], methods=[caller],
        call_sites=[site(caller.id, "third.party.Client", "send")],
        include_external_targets=False,
    )
    assert report.graph.callees(caller.id) == ()


def test_unresolved_known_target_produces_warning():
    caller = method("A", "run")
    report = CallGraphBuilder().build(
        types=[TypeSymbol("A"), TypeSymbol("B")], methods=[caller],
        call_sites=[site(caller.id, "B", "missing")],
    )
    assert report.unresolved
    assert "unresolved call" in report.warnings[0]


def test_dynamic_dispatch_resolves_unique_signature():
    caller = method("A", "run")
    target = method("B", "lambda$0", "(I)V", synthetic=True)
    report = CallGraphBuilder().build(
        types=[TypeSymbol("A"), TypeSymbol("B")], methods=[caller, target],
        call_sites=[site(caller.id, "unknown", "lambda$0", "(I)V", dispatch=DispatchKind.DYNAMIC, kind=CallSiteKind.LAMBDA)],
    )
    assert report.graph.callees(caller.id) == (target.id,)


def test_dynamic_dispatch_reports_polymorphic_signature():
    caller = method("A", "run")
    first = method("B", "apply", "(I)I")
    second = method("C", "apply", "(I)I")
    report = CallGraphBuilder().build(
        types=[TypeSymbol("A"), TypeSymbol("B"), TypeSymbol("C")], methods=[caller, first, second],
        call_sites=[site(caller.id, "dynamic", "apply", "(I)I", dispatch=DispatchKind.DYNAMIC)],
    )
    assert report.resolutions[0].status is ResolutionStatus.POLYMORPHIC
    assert report.graph.callees(caller.id) == (first.id, second.id)


def test_duplicate_methods_are_rejected():
    duplicate = method("A", "run")
    with pytest.raises(ValueError, match="duplicate method"):
        CallGraphBuilder().build(methods=[duplicate, duplicate])


def test_missing_caller_is_preserved_as_external_method():
    caller = mid("Missing", "run")
    target = method("B", "work")
    report = CallGraphBuilder().build(
        types=[TypeSymbol("B")], methods=[target],
        call_sites=[site(caller, "B", "work")],
    )
    assert report.graph.method(caller).external
    assert any("caller missing" in warning for warning in report.warnings)


def test_direct_and_transitive_callees():
    graph = basic_report().graph
    controller = mid("app.Controller", "handle")
    assert graph.callees(controller) == (mid("app.Service", "process"),)
    assert graph.callees(controller, transitive=True) == (
        mid("app.Repository", "save"), mid("app.Service", "process")
    )


def test_direct_and_transitive_callers():
    graph = basic_report().graph
    repository = mid("app.Repository", "save")
    assert graph.callers(repository) == (mid("app.Service", "process"),)
    assert graph.callers(repository, transitive=True) == (
        mid("app.Controller", "handle"), mid("app.Service", "process")
    )


def test_transitive_walk_respects_depth():
    graph = basic_report().graph
    root = mid("app.Controller", "handle")
    assert graph.callees(root, transitive=True, max_depth=1) == (mid("app.Service", "process"),)


def test_shortest_path_returns_edges_and_methods():
    graph = basic_report().graph
    path = graph.shortest_path(mid("app.Controller", "handle"), mid("app.Repository", "save"))
    assert path.length == 2
    assert path.methods == (
        mid("app.Controller", "handle"), mid("app.Service", "process"), mid("app.Repository", "save")
    )


def test_shortest_path_returns_none_when_disconnected():
    graph = basic_report().graph
    assert graph.shortest_path(mid("app.Repository", "save"), mid("app.Controller", "handle")) is None


def test_paths_from_returns_leaf_paths():
    graph = basic_report().graph
    paths = graph.paths_from(mid("app.Controller", "handle"))
    assert paths[0].methods[-1] == mid("app.Repository", "save")
    assert paths[0].cycle is False


def test_paths_from_marks_cycles():
    a, b = method("A", "a"), method("B", "b")
    graph = CallGraphBuilder().build(
        types=[TypeSymbol("A"), TypeSymbol("B")], methods=[a, b],
        call_sites=[site(a.id, "B", "b"), site(b.id, "A", "a")],
    ).graph
    paths = graph.paths_from(a.id)
    assert paths[0].cycle is True
    assert paths[0].methods == (a.id, b.id, a.id)


def test_paths_validate_limits():
    with pytest.raises(ValueError):
        basic_report().graph.paths_from(mid("app.Controller", "handle"), max_paths=0)


def test_detects_self_recursion():
    recursive = method("A", "recurse")
    graph = CallGraphBuilder().build(
        types=[TypeSymbol("A")], methods=[recursive],
        call_sites=[site(recursive.id, "A", "recurse")],
    ).graph
    components = graph.recursive_components()
    assert components[0].methods == (recursive.id,)


def test_detects_mutual_recursion_as_scc():
    a, b, c = method("A", "a"), method("B", "b"), method("C", "c")
    graph = CallGraphBuilder().build(
        types=[TypeSymbol("A"), TypeSymbol("B"), TypeSymbol("C")], methods=[a, b, c],
        call_sites=[site(a.id, "B", "b"), site(b.id, "C", "c"), site(c.id, "A", "a")],
    ).graph
    assert graph.recursive_components()[0].methods == (a.id, b.id, c.id)


def test_non_recursive_sccs_are_available():
    graph = basic_report().graph
    components = graph.strongly_connected_components()
    assert len(components) == 3
    assert all(not component.recursive for component in components)


def test_roots_and_leaves():
    graph = basic_report().graph
    assert graph.roots() == (mid("app.Controller", "handle"),)
    assert graph.leaves() == (mid("app.Repository", "save"),)


def test_statistics_cover_resolution_and_recursion():
    report = basic_report()
    stats = report.graph.statistics()
    assert stats.method_count == 3
    assert stats.edge_count == 2
    assert stats.unresolved_call_sites == 0
    assert stats.recursive_component_count == 0


def test_json_export_is_deterministic_and_versioned():
    graph = basic_report().graph
    first = graph.to_json()
    second = graph.to_json()
    assert first == second
    payload = json.loads(first)
    assert payload["schema"] == "moughorai.call-graph.v1"
    assert payload["statistics"]["edge_count"] == 2


def test_edges_keep_source_and_declared_target_metadata():
    caller = method("A", "run")
    callee = method("B", "work")
    graph = CallGraphBuilder().build(
        types=[TypeSymbol("A"), TypeSymbol("B")], methods=[caller, callee],
        call_sites=[site(caller.id, "B", "work", source_path="A.java", line=12, column=7)],
    ).graph
    edge = graph.edges[0]
    assert edge.source_path == "A.java"
    assert edge.line == 12
    assert edge.column == 7
    assert edge.declared_target == callee.id


def test_call_site_validates_location_and_ordinal():
    with pytest.raises(ValueError):
        site(mid("A", "run"), "B", "work", line=0)
    with pytest.raises(ValueError):
        site(mid("A", "run"), "B", "work", ordinal=-1)
