from pathlib import Path

from typer.testing import CliRunner

from moughorai.architecture_detection import ArchitectureDetectionService
from moughorai.atlas_cli import app
from moughorai.java_architecture import (
    ArchitectureEdge,
    ArchitectureEdgeKind,
    ArchitectureNode,
    JavaArchitectureGraph,
)
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import WorkspaceService


runner = CliRunner()


def _summary():
    return {
        "projects": [
            {"name": "root", "path": ".", "frameworks": [], "entry_points": []},
            {"name": "orders-api", "path": "orders/api", "frameworks": [], "entry_points": ["main.py"]},
            {"name": "billing-service", "path": "billing", "frameworks": [], "entry_points": ["App.java"]},
            {"name": "order-repository", "path": "orders/repository", "frameworks": [], "entry_points": []},
        ],
        "module_hierarchy": [
            {"project": "root", "parent": None},
            {"project": "orders-api", "parent": "root"},
            {"project": "billing-service", "parent": "root"},
            {"project": "order-repository", "parent": "root"},
        ],
    }


def _graph():
    names = (
        ("a", "orders.domain.Order"),
        ("b", "orders.application.CreateOrderCommandHandler"),
        ("c", "orders.application.FindOrderQueryHandler"),
        ("d", "orders.port.OrderPort"),
        ("e", "orders.adapter.OrderAdapter"),
        ("f", "orders.infrastructure.OrderRepository"),
        ("g", "orders.event.OrderEventPublisher"),
        ("h", "billing.event.OrderEventListener"),
        ("i", "plugins.PaymentPlugin"),
        ("j", "plugins.PaymentExtensionProvider"),
    )
    projects = {
        "a": "orders-api", "b": "orders-api", "c": "orders-api",
        "d": "orders-api", "e": "orders-api", "f": "order-repository",
        "g": "orders-api", "h": "billing-service", "i": "billing-service",
        "j": "billing-service",
    }
    return {
        "nodes": [
            {
                "id": identifier,
                "qualified_name": name,
                "project_id": projects[identifier],
                "language": "java",
                "kind": "type",
            }
            for identifier, name in names
        ],
        "edges": [
            {"source": "b", "target": "c", "kind": "imports"},
            {"source": "b", "target": "f", "kind": "imports"},
            {"source": "e", "target": "d", "kind": "imports"},
            {"source": "e", "target": "a", "kind": "imports"},
            {"source": "g", "target": "h", "kind": "imports"},
            {"source": "h", "target": "g", "kind": "imports"},
            {"source": "i", "target": "j", "kind": "imports"},
        ],
    }


def test_detects_requested_architectures_with_evidence() -> None:
    report = ArchitectureDetectionService().detect(_summary(), _graph())
    findings = {item.architecture: item for item in report.findings}
    assert {
        "layered", "modular-monolith", "hexagonal",
        "clean-architecture", "cqrs", "event-driven", "plugin-architecture",
    } <= set(findings)
    assert "microservices" not in findings
    assert all(item.evidence for item in findings.values())
    assert all(0.0 <= item.confidence <= 1.0 for item in findings.values())


def test_reports_directions_cycles_contexts_ports_and_infrastructure() -> None:
    report = ArchitectureDetectionService().detect(_summary(), _graph())
    assert report.dependency_directions == (
        ("billing-service", "orders-api"),
        ("orders-api", "billing-service"),
        ("orders-api", "order-repository"),
    )
    assert report.dependency_cycles == (("billing-service", "orders-api"),)
    assert report.bounded_contexts == ("billing-service", "order-repository", "orders-api")
    assert report.ports == ("orders.port.OrderPort",)
    assert report.adapters == ("orders.adapter.OrderAdapter",)
    assert report.infrastructure_layers == (
        "orders.infrastructure.OrderRepository",
    )


def test_optional_java_architecture_graph_is_reused() -> None:
    graph = JavaArchitectureGraph(
        (
            ArchitectureNode("demo.Api", "Api", "class", "demo"),
            ArchitectureNode("demo.Service", "Service", "class", "demo"),
        ),
        (
            ArchitectureEdge(
                "demo.Api", "demo.Service", ArchitectureEdgeKind.FIELD_TYPE,
                "field:service", "Service",
            ),
        ),
    )
    report = ArchitectureDetectionService().detect(
        {"projects": (), "module_hierarchy": ()},
        {"nodes": (), "edges": ()},
        java_graph=graph,
    )
    assert report.dependency_directions == (("demo.Api", "demo.Service"),)


def test_conflicting_deployment_models_are_explicit() -> None:
    summary = _summary()
    summary["projects"][1]["frameworks"] = ["Spring"]
    summary["projects"][2]["frameworks"] = ["FastAPI"]
    report = ArchitectureDetectionService().detect(summary, _graph())
    assert {"modular-monolith", "microservices"} <= {
        item.architecture for item in report.findings
    }
    assert report.classification_conflicts


def test_report_is_deterministic() -> None:
    service = ArchitectureDetectionService()
    assert service.detect(_summary(), _graph()).to_dict() == service.detect(
        _summary(), _graph(),
    ).to_dict()


def test_port_detection_does_not_treat_support_as_a_port() -> None:
    report = ArchitectureDetectionService().detect(
        {"projects": (), "module_hierarchy": ()},
        {
            "nodes": [
                {
                    "id": "support",
                    "qualified_name": "demo.SupportUtility",
                    "project_id": "demo",
                },
                {
                    "id": "port",
                    "qualified_name": "demo.PaymentPort",
                    "project_id": "demo",
                },
            ],
            "edges": (),
        },
    )
    assert report.ports == ("demo.PaymentPort",)


def test_architecture_is_published_in_semantic_snapshot(tmp_path: Path) -> None:
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: root\n    path: .\n"
        "  - name: orders-api\n    path: orders/api\n"
        "  - name: billing-service\n    path: billing\n"
        "  - name: order-repository\n    path: orders/repository\n",
        encoding="utf-8",
    )
    for relative in ("orders/api", "billing", "orders/repository"):
        folder = tmp_path / relative
        folder.mkdir(parents=True)
        (folder / "main.py").write_text(
            'if __name__ == "__main__":\n    pass\n',
            encoding="utf-8",
        )
    result = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])
    assert result.exit_code == 0
    snapshot = SemanticSnapshotStore(WorkspaceService(tmp_path).workspace).load()
    architecture = snapshot.semantic_context["architecture"]
    assert "layered" not in {
        item["architecture"] for item in architecture["findings"]
    }
    assert architecture["dependency_analysis"] == {
        "executed": False,
        "evidence_edge_count": 0,
    }
