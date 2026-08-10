from pathlib import Path

import pytest

from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.architecture_detection import ArchitectureDetectionService
from moughorai.architecture_detection.models import (
    ArchitectureDependencyEvidenceClass,
    ArchitectureDependencyPairClassification,
    ArchitectureReport,
)
from moughorai.workspace import (
    DependencyGraph,
    Project,
    Workspace,
    WorkspaceDependencyError,
    WorkspaceDiscovery,
)


def _write_pom(
    path: Path,
    *,
    artifact_id: str,
    modules: tuple[str, ...] = (),
    dependencies: tuple[tuple[str, str], ...] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    module_xml = "".join(f"<module>{module}</module>" for module in modules)
    dependency_xml = "".join(
        (
            f"<dependency><groupId>{group_id}</groupId>"
            f"<artifactId>{dependency}</artifactId>"
            "<version>1</version></dependency>"
        )
        for group_id, dependency in dependencies
    )
    path.write_text(
        (
            "<project><modelVersion>4.0.0</modelVersion>"
            "<groupId>com.example</groupId>"
            f"<artifactId>{artifact_id}</artifactId><version>1</version>"
            f"<modules>{module_xml}</modules>"
            f"<dependencies>{dependency_xml}</dependencies>"
            "</project>"
        ),
        encoding="utf-8",
    )


def _project(name: str) -> dict[str, object]:
    return {
        "id": f"project:{name}",
        "kind": "project",
        "qualified_name": name,
        "project_id": None,
        "language": "unknown",
    }


def _symbol(identifier: str, project: str) -> dict[str, object]:
    return {
        "id": identifier,
        "kind": "type",
        "qualified_name": identifier,
        "project_id": project,
        "language": "java",
    }


def _build(source: str, target: str) -> dict[str, object]:
    return {
        "source": f"project:{source}",
        "target": f"project:{target}",
        "kind": "depends_on",
        "evidence": [
            f"workspace.projects:{source}:dependencies:{target}",
        ],
    }


def _imports(
    source: str,
    target: str,
    *,
    evidence: tuple[str, ...] = ("global_symbol.metadata:imports:target",),
) -> dict[str, object]:
    return {
        "source": source,
        "target": target,
        "kind": "imports",
        "evidence": list(evidence),
    }


def _graph(
    nodes: tuple[dict[str, object], ...],
    edges: tuple[dict[str, object], ...],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "nodes": list(nodes),
        "edges": list(edges),
    }


def _detect(graph: dict[str, object]) -> ArchitectureReport:
    return ArchitectureDetectionService().detect(
        {"projects": (), "module_hierarchy": ()},
        graph,
    )


def test_maven_build_dependency_is_build_only_without_source_import(
    tmp_path: Path,
) -> None:
    root = tmp_path / "reactor"
    _write_pom(
        root / "pom.xml",
        artifact_id="root",
        modules=("module-a", "module-b"),
    )
    _write_pom(root / "module-a/pom.xml", artifact_id="module-a")
    _write_pom(
        root / "module-b/pom.xml",
        artifact_id="module-b",
        dependencies=(
            ("com.example", "module-a"),
            ("org.external", "library"),
        ),
    )

    workspace = WorkspaceDiscovery().discover(root)
    graph = WorkspaceContextBuilder().build(workspace).to_dict()["semantic_graph"]
    report = _detect(graph)

    assert workspace.names() == ("module-a", "module-b", "reactor")
    assert report.dependency_directions == ()
    assert report.build_dependency_topology.evidence_class is (
        ArchitectureDependencyEvidenceClass.BUILD_MODULE
    )
    assert tuple(
        (item.source_project, item.target_project)
        for item in report.build_dependency_topology.directions
    ) == (("module-b", "module-a"),)
    direction = report.build_dependency_topology.directions[0]
    assert direction.evidence_count == 1
    assert direction.provenance == ("workspace.projects",)
    assert report.import_dependency_topology.directions == ()
    assert tuple(
        item.classification for item in report.dependency_pair_classifications
    ) == (ArchitectureDependencyPairClassification.BUILD_ONLY,)


def test_observed_import_is_import_only_and_preserves_evidence_count() -> None:
    graph = _graph(
        (
            _symbol("type:b.One", "module-b"),
            _symbol("type:a.One", "module-a"),
        ),
        (
            _imports(
                "type:b.One",
                "type:a.One",
                evidence=(
                    "global_symbol.metadata:imports:a.One",
                    "global_symbol.metadata:imports:a.Two",
                ),
            ),
        ),
    )

    report = _detect(graph)

    assert report.dependency_directions == (("module-b", "module-a"),)
    assert report.dependency_evidence_edges == 1
    assert report.build_dependency_topology.directions == ()
    direction = report.import_dependency_topology.directions[0]
    assert (
        direction.source_project,
        direction.target_project,
        direction.evidence_count,
        direction.provenance,
    ) == ("module-b", "module-a", 2, ("global_symbol.metadata",))
    assert tuple(
        item.classification for item in report.dependency_pair_classifications
    ) == (ArchitectureDependencyPairClassification.IMPORT_ONLY,)


def test_matching_build_and_import_evidence_is_corroborated() -> None:
    graph = _graph(
        (
            _project("module-a"),
            _project("module-b"),
            _symbol("type:b.One", "module-b"),
            _symbol("type:a.One", "module-a"),
        ),
        (
            _build("module-b", "module-a"),
            _imports("type:b.One", "type:a.One"),
        ),
    )

    report = _detect(graph)

    assert tuple(
        item.classification for item in report.dependency_pair_classifications
    ) == (ArchitectureDependencyPairClassification.CORROBORATED,)
    assert report.dependency_directions == (("module-b", "module-a"),)
    assert report.dependency_cycles == ()


def test_opposing_evidence_classes_do_not_manufacture_a_union_cycle() -> None:
    graph = _graph(
        (
            _project("module-a"),
            _project("module-b"),
            _symbol("type:a.One", "module-a"),
            _symbol("type:b.One", "module-b"),
        ),
        (
            _build("module-a", "module-b"),
            _imports("type:b.One", "type:a.One"),
        ),
    )

    report = _detect(graph)

    assert report.build_dependency_topology.cycles == ()
    assert report.import_dependency_topology.cycles == ()
    assert report.dependency_cycles == ()
    assert tuple(
        (
            item.source_project,
            item.target_project,
            item.classification,
        )
        for item in report.dependency_pair_classifications
    ) == (
        (
            "module-a",
            "module-b",
            ArchitectureDependencyPairClassification.BUILD_ONLY,
        ),
        (
            "module-b",
            "module-a",
            ArchitectureDependencyPairClassification.IMPORT_ONLY,
        ),
    )
    reversed_graph = {
        **graph,
        "nodes": list(reversed(graph["nodes"])),
        "edges": list(reversed(graph["edges"])),
    }
    assert _detect(reversed_graph).to_dict() == report.to_dict()


def test_build_cycles_are_separate_but_workspace_still_rejects_them(
    tmp_path: Path,
) -> None:
    direct = _detect(
        _graph(
            (_project("module-a"), _project("module-b")),
            (
                _build("module-a", "module-b"),
                _build("module-b", "module-a"),
            ),
        ),
    )

    assert direct.build_dependency_topology.cycles == (("module-a", "module-b"),)
    assert direct.import_dependency_topology.cycles == ()
    assert direct.dependency_cycles == ()

    workspace = Workspace(
        tmp_path,
        (
            Project("module-a", tmp_path / "module-a", ("module-b",)),
            Project("module-b", tmp_path / "module-b", ("module-a",)),
        ),
    )
    with pytest.raises(WorkspaceDependencyError, match="project dependency cycle"):
        DependencyGraph(workspace)


def test_new_topologies_are_additive_to_legacy_schema_one_report() -> None:
    report = ArchitectureReport((), (), (), (), (), (), ())
    payload = report.to_dict()

    assert payload["schema_version"] == 1
    assert payload["dependency_directions"] == []
    assert payload["dependency_cycles"] == []
    assert payload["dependency_analysis"] == {
        "executed": False,
        "evidence_edge_count": 0,
    }
    assert payload["build_dependency_topology"] == {
        "evidence_class": "BUILD_MODULE",
        "directions": [],
        "cycles": [],
    }
    assert payload["import_dependency_topology"] == {
        "evidence_class": "SOURCE_IMPORT",
        "directions": [],
        "cycles": [],
    }
    assert payload["dependency_pair_classifications"] == []
