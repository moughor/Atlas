from pathlib import Path

from typer.testing import CliRunner

from moughorai.ai_context.persistence import (
    decode_analysis_result,
    encode_analysis_result,
)
from moughorai.atlas_cli import app
from moughorai.call_graph import (
    CallEdge,
    CallGraph,
    CallSiteKind,
    DispatchKind,
    MethodId,
    MethodSymbol,
    TypeSymbol,
)
from moughorai.design_patterns import (
    PatternAvailability,
    PatternDetectionReport,
    PatternDetectionService,
    PatternKind,
)
from moughorai.java_architecture import (
    ArchitectureEdge,
    ArchitectureEdgeKind,
    ArchitectureNode,
    JavaArchitectureGraph,
)
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.semantic import SemanticDocument
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    ConfidenceTier,
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
)
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import WorkspaceService


runner = CliRunner()


def _type(identifier: str, name: str, project: str = "demo") -> KnowledgeNode:
    return KnowledgeNode(
        identifier,
        KnowledgeKind.TYPE,
        name,
        qualified_name=name,
        project_id=project,
        language="java",
    )


def _method(
    identifier: str,
    name: str,
    owner: str,
    project: str = "demo",
) -> tuple[KnowledgeNode, KnowledgeEdge]:
    return (
        KnowledgeNode(
            identifier,
            KnowledgeKind.METHOD,
            name,
            qualified_name=name,
            project_id=project,
            language="java",
        ),
        KnowledgeEdge(
            identifier,
            owner,
            KnowledgeRelation.MEMBER_OF,
            ("global_symbol.owner_id",),
        ),
    )


def _edge(
    source: str,
    target: str,
    relation: KnowledgeRelation,
    reference: str,
) -> KnowledgeEdge:
    return KnowledgeEdge(source, target, relation, (reference,))


def test_evidence_ids_and_confidence_are_deterministic() -> None:
    first = EvidenceRecord.create(
        EvidenceKind.GRAPH_EDGE,
        "child|inheritance|base",
        "knowledge-graph/1",
        "snapshot:one",
        source_refs=("b", "a"),
        detail={"target": "base", "source": "child"},
        reliability=1.0,
        specificity=0.9,
    )
    second = EvidenceRecord.create(
        EvidenceKind.GRAPH_EDGE,
        "child|inheritance|base",
        "knowledge-graph/1",
        "snapshot:one",
        source_refs=("a", "b"),
        detail={"source": "child", "target": "base"},
        reliability=1.0,
        specificity=0.9,
    )
    assert first == second

    index = EvidenceIndex((first,))
    result = ConfidenceCalculator().calculate(
        (EvidenceRole("inheritance", (first.evidence_id,)),),
        index,
    )
    assert result.score == 0.9
    assert result.tier is ConfidenceTier.HIGH
    assert EvidenceIndex.from_dict(index.to_dict()).to_dict() == index.to_dict()


def test_missing_required_evidence_is_insufficient_not_negative() -> None:
    result = ConfidenceCalculator().calculate(
        (EvidenceRole("resolved calls"),),
        EvidenceIndex(),
    )
    assert result.score == 0.0
    assert result.tier is ConfidenceTier.INSUFFICIENT
    assert result.missing_roles == ("resolved calls",)


def test_strategy_and_builder_use_structured_java_evidence() -> None:
    nodes = (
        _type("strategy", "demo.Strategy"),
        _type("a", "demo.StrategyA"),
        _type("b", "demo.StrategyB"),
        _type("client", "demo.Client"),
        _type("builder", "demo.ProductBuilder"),
        _type("product", "demo.Product"),
    )
    graph = KnowledgeGraph(nodes, (
        _edge("a", "strategy", KnowledgeRelation.INHERITS, "implements:Strategy"),
        _edge("b", "strategy", KnowledgeRelation.INHERITS, "implements:Strategy"),
    ))
    architecture = JavaArchitectureGraph(
        tuple(
            ArchitectureNode(
                node.name,
                node.name.rsplit(".", 1)[-1],
                "interface" if node.id == "strategy" else "class",
                "demo",
            )
            for node in nodes
        ),
        (
            ArchitectureEdge(
                "demo.Client",
                "demo.Strategy",
                ArchitectureEdgeKind.FIELD_TYPE,
                "field:selected",
                "Strategy",
            ),
            ArchitectureEdge(
                "demo.ProductBuilder",
                "demo.ProductBuilder",
                ArchitectureEdgeKind.METHOD_RETURN,
                "method-return:first",
                "ProductBuilder",
            ),
            ArchitectureEdge(
                "demo.ProductBuilder",
                "demo.ProductBuilder",
                ArchitectureEdgeKind.METHOD_RETURN,
                "method-return:second",
                "ProductBuilder",
            ),
            ArchitectureEdge(
                "demo.ProductBuilder",
                "demo.Product",
                ArchitectureEdgeKind.METHOD_RETURN,
                "method-return:finish",
                "Product",
            ),
        ),
    )

    report = PatternDetectionService().detect(
        graph,
        java_architecture_graphs={"demo": architecture},
    )
    by_pattern = {item.pattern: item for item in report.findings}

    assert {PatternKind.STRATEGY, PatternKind.BUILDER} <= set(by_pattern)
    assert all(item.evidence_ids for item in by_pattern.values())
    assert all(item.participants for item in by_pattern.values())
    assert all(item.explanation for item in by_pattern.values())
    assert all(item.limitations for item in by_pattern.values())
    evidence_ids = {
        item["evidence_id"]
        for item in report.to_dict()["evidence_index"]["records"]
    }
    assert set(by_pattern[PatternKind.STRATEGY].evidence_ids) <= evidence_ids
    assert (
        PatternDetectionReport.from_dict(report.to_dict()).to_dict()
        == report.to_dict()
    )


def test_name_only_candidates_are_not_patterns() -> None:
    graph = KnowledgeGraph((
        _type("strategy", "demo.PaymentStrategy"),
        _type("factory", "demo.WidgetFactory"),
        _type("builder", "demo.RequestBuilder"),
        _type("observer", "demo.EventObserver"),
    ))

    report = PatternDetectionService().detect(graph)

    assert report.findings == ()
    capabilities = {item.pattern: item for item in report.capabilities}
    assert capabilities[PatternKind.OBSERVER].availability is PatternAvailability.INSUFFICIENT
    assert any(
        "subscription registration" in limitation
        for limitation in capabilities[PatternKind.OBSERVER].limitations
    )
    assert {item.pattern for item in report.capabilities} == set(PatternKind)


def test_detection_is_reproducible_and_cache_invalidates_by_input() -> None:
    nodes = (
        _type("contract", "demo.Contract"),
        _type("one", "demo.One"),
        _type("two", "demo.Two"),
        _type("client", "demo.Client"),
    )
    edges = (
        _edge("one", "contract", KnowledgeRelation.INHERITS, "implements:Contract"),
        _edge("two", "contract", KnowledgeRelation.INHERITS, "implements:Contract"),
        _edge("client", "contract", KnowledgeRelation.COMPOSES, "field:contract"),
    )
    service = PatternDetectionService()

    first = service.detect(KnowledgeGraph(nodes, edges))
    reordered = service.detect(
        KnowledgeGraph(tuple(reversed(nodes)), tuple(reversed(edges))),
    )
    changed = service.detect(
        KnowledgeGraph((*nodes, _type("extra", "demo.Extra")), edges),
    )

    assert first.to_dict() == reordered.to_dict()
    assert first.input_fingerprint != changed.input_fingerprint


def test_call_dependent_patterns_use_resolved_graph_evidence() -> None:
    nodes = [
        _type("target", "demo.Target"),
        _type("adapter", "demo.Adapter"),
        _type("adaptee", "demo.Adaptee"),
        _type("component", "demo.Component"),
        _type("decorator", "demo.Decorator"),
        _type("base", "demo.Base"),
        _type("child", "demo.Child"),
    ]
    methods_and_edges = [
        _method("adapter:run", "demo.Adapter#run()", "adapter"),
        _method("adaptee:run", "demo.Adaptee#run()", "adaptee"),
        _method("decorator:run", "demo.Decorator#run()", "decorator"),
        _method("component:run", "demo.Component#run()", "component"),
        _method("base:template", "demo.Base#template()", "base"),
        _method("base:hook", "demo.Base#hook()", "base"),
        _method("child:hook", "demo.Child#hook()", "child"),
    ]
    nodes.extend(item[0] for item in methods_and_edges)
    edges = [item[1] for item in methods_and_edges]
    edges.extend((
        _edge("adapter", "target", KnowledgeRelation.INHERITS, "implements:Target"),
        _edge("adapter", "adaptee", KnowledgeRelation.COMPOSES, "field:adaptee"),
        _edge("adapter:run", "adaptee:run", KnowledgeRelation.CALLS, "resolved-call"),
        _edge("decorator", "component", KnowledgeRelation.INHERITS, "implements:Component"),
        _edge("decorator", "component", KnowledgeRelation.COMPOSES, "field:component"),
        _edge("decorator:run", "component:run", KnowledgeRelation.CALLS, "resolved-call"),
        _edge("child", "base", KnowledgeRelation.INHERITS, "extends:Base"),
        _edge("child:hook", "base:hook", KnowledgeRelation.OVERRIDES, "@Override"),
        _edge("base:template", "base:hook", KnowledgeRelation.CALLS, "resolved-call"),
    ))

    report = PatternDetectionService().detect(KnowledgeGraph(nodes, edges))
    patterns = {item.pattern for item in report.findings}

    assert {
        PatternKind.ADAPTER,
        PatternKind.DECORATOR,
        PatternKind.TEMPLATE_METHOD,
    } <= patterns


def test_factory_uses_return_and_constructor_call_evidence() -> None:
    nodes = (
        _type("product", "demo.Product"),
        _type("a", "demo.ProductA"),
        _type("b", "demo.ProductB"),
        _type("creator", "demo.Creator"),
    )
    graph = KnowledgeGraph(nodes, (
        _edge("a", "product", KnowledgeRelation.INHERITS, "implements:Product"),
        _edge("b", "product", KnowledgeRelation.INHERITS, "implements:Product"),
    ))
    architecture = JavaArchitectureGraph(
        tuple(
            ArchitectureNode(
                node.name,
                node.name.rsplit(".", 1)[-1],
                "interface" if node.id == "product" else "class",
                "demo",
            )
            for node in nodes
        ),
        (
            ArchitectureEdge(
                "demo.Creator",
                "demo.Product",
                ArchitectureEdgeKind.METHOD_RETURN,
                "method-return:make",
                "Product",
            ),
        ),
    )
    caller = MethodSymbol(MethodId("demo.Creator", "make"))
    constructor_a = MethodSymbol(MethodId("demo.ProductA", "<init>"))
    constructor_b = MethodSymbol(MethodId("demo.ProductB", "<init>"))
    call_graph = CallGraph(
        (caller, constructor_a, constructor_b),
        (
            CallEdge(
                caller.id,
                constructor_a.id,
                DispatchKind.SPECIAL,
                CallSiteKind.CONSTRUCTOR,
            ),
            CallEdge(
                caller.id,
                constructor_b.id,
                DispatchKind.SPECIAL,
                CallSiteKind.CONSTRUCTOR,
            ),
        ),
        types=(
            TypeSymbol("demo.Creator"),
            TypeSymbol("demo.Product"),
            TypeSymbol("demo.ProductA"),
            TypeSymbol("demo.ProductB"),
        ),
    )

    report = PatternDetectionService().detect(
        graph,
        java_architecture_graphs={"demo": architecture},
        call_graphs={"demo": call_graph},
    )

    assert PatternKind.FACTORY in {item.pattern for item in report.findings}


def test_command_requires_invoker_and_receiver_delegation() -> None:
    nodes = [
        _type("command", "demo.Command"),
        _type("first", "demo.FirstCommand"),
        _type("second", "demo.SecondCommand"),
        _type("invoker", "demo.Invoker"),
        _type("receiver", "demo.Receiver"),
    ]
    methods_and_edges = [
        _method("command:execute", "demo.Command#execute()", "command"),
        _method("invoker:invoke", "demo.Invoker#invoke()", "invoker"),
        _method("first:execute", "demo.FirstCommand#execute()", "first"),
        _method("receiver:act", "demo.Receiver#act()", "receiver"),
    ]
    nodes.extend(item[0] for item in methods_and_edges)
    edges = [item[1] for item in methods_and_edges]
    edges.extend((
        _edge("first", "command", KnowledgeRelation.INHERITS, "implements:Command"),
        _edge("second", "command", KnowledgeRelation.INHERITS, "implements:Command"),
        _edge("invoker", "command", KnowledgeRelation.COMPOSES, "field:command"),
        _edge("invoker:invoke", "command:execute", KnowledgeRelation.CALLS, "resolved-call"),
        _edge("first", "receiver", KnowledgeRelation.COMPOSES, "field:receiver"),
        _edge("first:execute", "receiver:act", KnowledgeRelation.CALLS, "resolved-call"),
    ))

    report = PatternDetectionService().detect(KnowledgeGraph(nodes, edges))

    assert PatternKind.COMMAND in {item.pattern for item in report.findings}


def test_java_architecture_artifact_survives_recovery_encoding() -> None:
    graph = JavaArchitectureGraph(
        (
            ArchitectureNode("demo.Builder", "Builder", "class", "demo"),
            ArchitectureNode("demo.Product", "Product", "class", "demo"),
        ),
        (
            ArchitectureEdge(
                "demo.Builder",
                "demo.Product",
                ArchitectureEdgeKind.METHOD_RETURN,
                "method-return:finish",
                "Product",
            ),
        ),
    )
    document = SemanticDocument("java", "", ()).with_artifact(
        "java_architecture_graph", graph,
    )

    restored = decode_analysis_result(encode_analysis_result(document))
    restored_graph = restored.get_artifact("java_architecture_graph")

    assert isinstance(restored_graph, JavaArchitectureGraph)
    assert restored_graph.edges == graph.edges
    assert restored_graph.nodes == graph.nodes


def test_normal_workspace_analysis_publishes_source_free_pattern_report(
    tmp_path: Path,
) -> None:
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: demo\n    path: .\n",
        encoding="utf-8",
    )
    (tmp_path / "Strategy.java").write_text(
        "package demo; public interface Strategy { void apply(); }",
        encoding="utf-8",
    )
    (tmp_path / "First.java").write_text(
        "package demo; public class First implements Strategy {"
        " public void apply() {} }",
        encoding="utf-8",
    )
    (tmp_path / "Second.java").write_text(
        "package demo; public class Second implements Strategy {"
        " public void apply() {} }",
        encoding="utf-8",
    )
    (tmp_path / "Client.java").write_text(
        "package demo; public class Client { private Strategy selected; }",
        encoding="utf-8",
    )
    (tmp_path / "Product.java").write_text(
        "package demo; public class Product {}",
        encoding="utf-8",
    )
    (tmp_path / "ProductBuilder.java").write_text(
        "package demo; public class ProductBuilder {"
        " public ProductBuilder first() { return this; }"
        " public ProductBuilder second() { return this; }"
        " public Product finish() { return null; } }",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])

    assert result.exit_code == 0, result.output
    snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    assert snapshot is not None
    report = snapshot.semantic_context["design_patterns"]
    patterns = {item["pattern"] for item in report["findings"]}
    assert {"strategy", "builder"} <= patterns
    assert all(item["evidence_ids"] for item in report["findings"])
    serialized = str(report)
    assert "public class" not in serialized
    assert "return this" not in serialized
