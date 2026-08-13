from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pickle
import signal

import pytest
from typer.testing import CliRunner

import moughorai.atlas_cli as atlas_cli
from moughorai.ai_context import (
    AnalyzerRegistry,
    SemanticContextCollector,
    decode_analysis_result,
    encode_analysis_result,
)
from moughorai.ai_context.persistence import (
    decode_analysis_result_bytes,
    encode_analysis_result_bytes,
)
from moughorai.ai_context.process_execution import (
    ProcessProjectAnalyzer,
    ProjectAnalysisRequest,
)
from moughorai.java_code_intelligence.code_graph import code_graph_from_dict
from moughorai.java_code_intelligence.persistence import (
    callable_index_from_dict,
)
from moughorai.java_code_intelligence.test_evidence import (
    java_test_evidence_from_dict,
)
from moughorai.semantic import SemanticDocument
from moughorai.workspace import (
    ProjectRunStatus,
    WorkspaceAnalysisOrchestrator,
    WorkspaceEventKind,
    WorkspaceRecoveryManager,
    WorkspaceService,
)


runner = CliRunner()


def _write_workspace(
    root: Path,
    projects: tuple[tuple[str, tuple[str, ...]], ...],
) -> WorkspaceService:
    lines = ["projects:"]
    for name, dependencies in projects:
        (root / name).mkdir(parents=True, exist_ok=True)
        lines.extend((f"  - name: {name}", f"    path: {name}"))
        if dependencies:
            lines.append(f"    dependencies: [{', '.join(dependencies)}]")
    (root / "atlas.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return WorkspaceService(root)


def _write_java(root: Path, project: str, source: str, *, name: str = "App") -> Path:
    path = root / project / "src" / "main" / "java" / "demo" / f"{name}.java"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _simple_workspace(root: Path, count: int = 4) -> WorkspaceService:
    names = tuple(f"p{index}" for index in range(count))
    service = _write_workspace(root, tuple((name, ()) for name in names))
    for index, name in enumerate(names):
        _write_java(
            root,
            name,
            "package demo; "
            f"class App{index} {{ void run() {{ helper(); }} "
            "void helper() {} }",
        )
    return service


def _encoded_runs(report) -> dict[str, object]:
    return {
        run.project: encode_analysis_result(run.value)
        for run in report.runs
        if run.successful
    }


def _context_digest(context: dict[str, object]) -> str:
    canonical = json.dumps(
        context,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_request_is_frozen_compact_and_spawn_picklable(tmp_path: Path) -> None:
    project = _write_workspace(
        tmp_path,
        (("core", ()), ("app", ("core",))),
    ).project("app")
    request = ProjectAnalysisRequest.create(project, {"core": object()})
    restored = pickle.loads(pickle.dumps(request))

    assert restored == request
    assert restored.project() == project
    assert restored.available_dependencies == ("core",)
    with pytest.raises((AttributeError, TypeError)):
        restored.project_name = "changed"  # type: ignore[misc]


def test_canonical_transport_round_trip_contains_every_project_artifact(
    tmp_path: Path,
) -> None:
    service = _write_workspace(tmp_path, (("app", ()),))
    source = _write_java(
        tmp_path,
        "app",
        "package demo; class Helper { static void target() {} } "
        "class App { void run() { Helper.target(); } }",
    )
    _write_java(
        tmp_path,
        "app",
        "package demo; class Broken { void run() { missing(",
        name="Broken",
    )
    original = AnalyzerRegistry()(service.project("app"), {})
    payload = encode_analysis_result_bytes(original)
    restored = decode_analysis_result_bytes(payload)

    assert isinstance(restored, SemanticDocument)
    assert restored.language == original.language
    assert restored.metadata == original.metadata
    assert restored.diagnostics == original.diagnostics
    assert original.diagnostics
    assert restored.syntax_tree == ()
    assert encode_analysis_result_bytes(restored) == payload
    assert set(restored.artifacts) == set(original.artifacts)
    for artifact in sorted(original.artifacts):
        if artifact == "java_architecture_graph":
            continue
        assert restored.get_artifact(artifact) == original.get_artifact(artifact)
    restored_architecture = restored.require_artifact("java_architecture_graph")
    original_architecture = original.require_artifact("java_architecture_graph")
    assert restored_architecture.nodes == tuple(sorted(
        original_architecture.nodes,
        key=lambda item: item.qualified_name,
    ))
    assert restored_architecture.edges == tuple(sorted(
        original_architecture.edges,
        key=lambda item: (item.source, item.target, item.kind.value, item.role),
    ))
    assert restored_architecture.unresolved == tuple(sorted(
        original_architecture.unresolved,
        key=lambda item: (item.owner, item.role, item.requested_name),
    ))
    serialized = payload.decode("utf-8")
    assert source.read_text(encoding="utf-8") not in serialized
    assert "worker_pid" not in serialized
    assert "duration" not in serialized
    assert "java_test_evidence" not in serialized
    assert '"reachability"' not in serialized


def test_process_transport_encoder_emits_canonical_json(tmp_path: Path) -> None:
    service = _write_workspace(tmp_path, (("app", ()),))
    _write_java(tmp_path, "app", "package demo; class App {}")
    canonical = encode_analysis_result_bytes(
        AnalyzerRegistry()(service.project("app"), {})
    )
    reconstructed = json.dumps(
        json.loads(canonical.decode("utf-8")),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")

    assert reconstructed == canonical
    assert isinstance(decode_analysis_result_bytes(canonical), SemanticDocument)


def test_process_worker_is_spawned_and_reuses_one_owned_registry(
    tmp_path: Path,
) -> None:
    service = _simple_workspace(tmp_path, 2)
    serial = WorkspaceAnalysisOrchestrator(service).execute(
        AnalyzerRegistry(), max_workers=1,
    )
    with ProcessProjectAnalyzer(1) as analyzer:
        process = WorkspaceAnalysisOrchestrator(service).execute(
            analyzer, max_workers=1,
        )
        metrics = analyzer.task_metrics

    assert process.succeeded
    assert _encoded_runs(process) == _encoded_runs(serial)
    assert len(metrics) == 2
    assert len({item.worker_pid for item in metrics}) == 1
    assert metrics[0].worker_pid != os.getpid()
    assert all(item.payload_bytes > 0 for item in metrics)


@pytest.mark.parametrize("workers", [1, 2, 4, 8])
def test_worker_counts_preserve_project_result_identity(
    tmp_path: Path,
    workers: int,
) -> None:
    service = _simple_workspace(tmp_path, 4)
    serial = WorkspaceAnalysisOrchestrator(service).execute(
        AnalyzerRegistry(), max_workers=1,
    )
    with ProcessProjectAnalyzer(workers) as analyzer:
        process = WorkspaceAnalysisOrchestrator(service).execute(
            analyzer, max_workers=workers,
        )

    assert process.analysis_order == serial.analysis_order
    assert tuple(run.project for run in process.runs) == serial.analysis_order
    assert _encoded_runs(process) == _encoded_runs(serial)


def test_process_and_serial_build_identical_pr157_pr158_contexts(
    tmp_path: Path,
) -> None:
    service = _write_workspace(tmp_path, (("app", ()),))
    _write_java(
        tmp_path,
        "app",
        "package demo; class Service { static void run() {} } "
        "class Application { void start() { Service.run(); "
        "external.Library.call(); } }",
        name="Service",
    )
    _write_java(
        tmp_path,
        "app",
        "package demo; class Broken { void run() { missing(",
        name="Broken",
    )
    test_path = (
        tmp_path / "app" / "src" / "test" / "java" / "demo" / "ServiceTest.java"
    )
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "package demo; @interface Test {} class ServiceTest { "
        "@Test void verifies() { Service.run(); } }",
        encoding="utf-8",
    )

    serial_report = WorkspaceAnalysisOrchestrator(service).execute(
        AnalyzerRegistry(), max_workers=1,
    )
    serial_context = SemanticContextCollector(service).collect(
        serial_report,
    ).context.to_dict()
    with ProcessProjectAnalyzer(2) as analyzer:
        process_report = WorkspaceAnalysisOrchestrator(service).execute(
            analyzer, max_workers=2,
        )
    process_context = SemanticContextCollector(service).collect(
        process_report,
    ).context.to_dict()

    assert _encoded_runs(process_report) == _encoded_runs(serial_report)
    assert process_context == serial_context
    assert _context_digest(process_context) == _context_digest(serial_context)
    assert process_context["java_code_graph"]["digest"] == (
        serial_context["java_code_graph"]["digest"]
    )
    assert process_context["java_test_evidence"]["digest"] == (
        serial_context["java_test_evidence"]["digest"]
    )
    assert process_context["reachability"] == serial_context["reachability"]

    serial_index = callable_index_from_dict(
        serial_context["java_callable_index"]
    )
    process_index = callable_index_from_dict(
        process_context["java_callable_index"]
    )
    serial_graph = code_graph_from_dict(
        serial_context["java_code_graph"],
        serial_index,
    )
    process_graph = code_graph_from_dict(
        process_context["java_code_graph"],
        process_index,
    )
    serial_tests = java_test_evidence_from_dict(
        serial_context["java_test_evidence"],
        serial_index,
    )
    process_tests = java_test_evidence_from_dict(
        process_context["java_test_evidence"],
        process_index,
    )

    assert process_index == serial_index
    assert process_graph == serial_graph
    assert process_tests == serial_tests
    assert serial_graph.call_sites
    assert serial_graph.edges
    assert serial_graph.diagnostics
    assert any(item.limitations for item in serial_graph.call_sites)
    assert serial_tests.records
    assert serial_tests.roots
    assert tuple(item.evidence_id for item in process_graph.call_sites) == tuple(
        item.evidence_id for item in serial_graph.call_sites
    )
    assert tuple(item.evidence_id for item in process_tests.records) == tuple(
        item.evidence_id for item in serial_tests.records
    )
    for payload_name in (
        "java_callable_index",
        "java_code_graph",
        "java_test_evidence",
    ):
        serial_payload = serial_context[payload_name]
        process_payload = process_context[payload_name]
        assert process_payload["format"] == serial_payload["format"]
        assert process_payload["schema_version"] == serial_payload["schema_version"]
        assert (
            process_payload["producer_version"]
            == serial_payload["producer_version"]
        )
        assert process_payload["digest"] == serial_payload["digest"]
        assert (
            process_payload["input_fingerprint"]
            == serial_payload["input_fingerprint"]
        )


def test_dependency_names_and_mixed_language_results_match_serial(
    tmp_path: Path,
) -> None:
    service = _write_workspace(
        tmp_path,
        (("core", ()), ("mixed", ("core",))),
    )
    _write_java(tmp_path, "core", "package demo; class Core {}")
    _write_java(tmp_path, "mixed", "package demo; class Mixed {}")
    (tmp_path / "mixed" / "module.py").write_text(
        "class PythonType:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "mixed" / "module.ts").write_text(
        "export class TypeScriptType {}\n",
        encoding="utf-8",
    )
    serial = WorkspaceAnalysisOrchestrator(service).execute(
        AnalyzerRegistry(), max_workers=1,
    )
    with ProcessProjectAnalyzer(2) as analyzer:
        process = WorkspaceAnalysisOrchestrator(service).execute(
            analyzer, max_workers=2,
        )

    assert _encoded_runs(process) == _encoded_runs(serial)
    serial_mixed = serial.get("mixed").value
    process_mixed = process.get("mixed").value
    assert process_mixed.metadata["dependencies"] == ("core",)
    assert process_mixed.language == "mixed"
    assert set(process_mixed.artifacts) == set(serial_mixed.artifacts)
    for artifact in sorted(serial_mixed.artifacts):
        if artifact == "java_architecture_graph":
            process_architecture = process_mixed.require_artifact(artifact)
            serial_architecture = serial_mixed.require_artifact(artifact)
            assert process_architecture.nodes == serial_architecture.nodes
            assert process_architecture.edges == serial_architecture.edges
            assert process_architecture.unresolved == serial_architecture.unresolved
        else:
            assert process_mixed.get_artifact(artifact) == (
                serial_mixed.get_artifact(artifact)
            )


def _failure_workspace(root: Path) -> WorkspaceService:
    service = _write_workspace(
        root,
        (("core", ()), ("api", ("core",)), ("docs", ()), ("tools", ())),
    )
    _write_java(
        root, "core", "package demo; class Duplicate {}", name="First",
    )
    _write_java(
        root, "core", "package demo; class Duplicate {}", name="Second",
    )
    methods = " ".join(f"void m{index}() {{}}" for index in range(1500))
    _write_java(root, "docs", f"package demo; class Docs {{ {methods} }}")
    _write_java(root, "tools", "package demo; class Tools {}")
    _write_java(root, "api", "package demo; class Api {}")
    return service


def test_dependency_failure_blocking_and_error_identity_match_serial(
    tmp_path: Path,
) -> None:
    service = _failure_workspace(tmp_path)
    serial = WorkspaceAnalysisOrchestrator(service).execute(
        AnalyzerRegistry(), max_workers=1,
    )
    with ProcessProjectAnalyzer(2) as analyzer:
        process = WorkspaceAnalysisOrchestrator(service).execute(
            analyzer, max_workers=2,
        )

    assert process.get("core").status is ProjectRunStatus.FAILED
    assert process.get("core").error == serial.get("core").error
    assert process.get("api").status is ProjectRunStatus.BLOCKED
    assert process.get("api").blocked_by == ("core",)
    assert process.get("docs").status is ProjectRunStatus.SUCCEEDED
    assert process.get("tools").status is ProjectRunStatus.SUCCEEDED


def test_process_fail_fast_and_cancellation_preserve_scheduler_semantics(
    tmp_path: Path,
) -> None:
    service = _failure_workspace(tmp_path)
    with ProcessProjectAnalyzer(2) as analyzer:
        failed = WorkspaceAnalysisOrchestrator(service).execute(
            analyzer,
            max_workers=2,
            fail_fast=True,
        )
    assert failed.get("core").status is ProjectRunStatus.FAILED
    assert failed.get("api").status is ProjectRunStatus.BLOCKED
    assert failed.get("tools").status is ProjectRunStatus.CANCELLED

    with ProcessProjectAnalyzer(2) as analyzer:
        cancelled = WorkspaceAnalysisOrchestrator(service).execute(
            analyzer,
            max_workers=2,
            cancelled=lambda: True,
        )
        assert analyzer.task_metrics == ()
    assert all(
        run.status in {ProjectRunStatus.CANCELLED, ProjectRunStatus.BLOCKED}
        for run in cancelled.runs
    )


def test_hard_worker_failure_is_reported_without_parent_corruption(
    tmp_path: Path,
) -> None:
    service = _simple_workspace(tmp_path, 2)
    analyzer = ProcessProjectAnalyzer(1)
    try:
        first = analyzer(service.project("p0"), {})
        assert isinstance(first, SemanticDocument)
        pid = analyzer.worker_pids[0]
        os.kill(pid, signal.SIGTERM)
        report = WorkspaceAnalysisOrchestrator(service).execute(
            analyzer,
            projects=("p1",),
            include_dependencies=False,
            max_workers=1,
        )
        assert report.get("p1").status is ProjectRunStatus.FAILED
        assert report.get("p1").error is not None
        assert report.get("p1").error.startswith("BrokenProcessPool:")
    finally:
        analyzer.close()


def test_completion_order_cannot_become_semantic_order(tmp_path: Path) -> None:
    service = _write_workspace(tmp_path, (("a-slow", ()), ("z-fast", ())))
    methods = " ".join(f"void m{index}() {{}}" for index in range(4000))
    _write_java(
        tmp_path,
        "a-slow",
        f"package demo; class Slow {{ {methods} }}",
        name="Slow",
    )
    _write_java(
        tmp_path,
        "z-fast",
        "package demo; class Fast {}",
        name="Fast",
    )
    with ProcessProjectAnalyzer(2) as analyzer:
        report = WorkspaceAnalysisOrchestrator(service).execute(
            analyzer, max_workers=2,
        )
        completion_order = tuple(
            item.project_name for item in analyzer.task_metrics
        )

    assert completion_order == ("z-fast", "a-slow")
    assert report.analysis_order == ("a-slow", "z-fast")
    assert tuple(run.project for run in report.runs) == report.analysis_order


def test_recovery_checkpoint_and_resume_preserve_process_results(
    tmp_path: Path,
) -> None:
    service = _simple_workspace(tmp_path, 3)
    manager = WorkspaceRecoveryManager(
        service,
        encoder=encode_analysis_result,
        decoder=decode_analysis_result,
    )
    with ProcessProjectAnalyzer(2) as analyzer:
        original = manager.execute(
            WorkspaceAnalysisOrchestrator(service),
            analyzer,
            max_workers=2,
        )
    assert original.succeeded

    resumed_service = WorkspaceService(tmp_path)
    resumed_manager = WorkspaceRecoveryManager(
        resumed_service,
        encoder=encode_analysis_result,
        decoder=decode_analysis_result,
    )
    with ProcessProjectAnalyzer(2) as analyzer:
        resumed, recovery = resumed_manager.resume(
            WorkspaceAnalysisOrchestrator(resumed_service),
            analyzer,
            max_workers=2,
        )
        assert analyzer.task_metrics == ()

    assert resumed is not None and resumed.succeeded
    assert recovery.journal_found
    assert _encoded_runs(resumed) == _encoded_runs(original)


def test_interrupted_process_resume_matches_uninterrupted_full_result(
    tmp_path: Path,
) -> None:
    service = _simple_workspace(tmp_path, 3)
    with ProcessProjectAnalyzer(2) as analyzer:
        uninterrupted = WorkspaceAnalysisOrchestrator(service).execute(
            analyzer,
            max_workers=2,
        )
    uninterrupted_context = SemanticContextCollector(service).collect(
        uninterrupted,
    ).context.to_dict()

    cancelled = False

    def cancel_after_first(event) -> None:
        nonlocal cancelled
        if event.kind is WorkspaceEventKind.PROJECT_COMPLETED:
            cancelled = True

    service.events.subscribe(
        cancel_after_first,
        kinds=[WorkspaceEventKind.PROJECT_COMPLETED],
    )
    manager = WorkspaceRecoveryManager(
        service,
        encoder=encode_analysis_result,
        decoder=decode_analysis_result,
    )
    with ProcessProjectAnalyzer(1) as analyzer:
        partial = manager.execute(
            WorkspaceAnalysisOrchestrator(service),
            analyzer,
            max_workers=1,
            cancelled=lambda: cancelled,
        )

    assert partial.get("p0").status is ProjectRunStatus.SUCCEEDED
    assert partial.get("p1").status is ProjectRunStatus.CANCELLED
    assert partial.get("p2").status is ProjectRunStatus.CANCELLED
    assert manager.inspect().completed == ("p0",)

    resumed_service = WorkspaceService(tmp_path)
    resumed_manager = WorkspaceRecoveryManager(
        resumed_service,
        encoder=encode_analysis_result,
        decoder=decode_analysis_result,
    )
    with ProcessProjectAnalyzer(2) as analyzer:
        resumed, recovery = resumed_manager.resume(
            WorkspaceAnalysisOrchestrator(resumed_service),
            analyzer,
            max_workers=2,
        )
        resumed_projects = tuple(
            item.project_name for item in analyzer.task_metrics
        )

    assert resumed is not None and resumed.succeeded
    assert recovery.resumed == ("p1", "p2")
    assert resumed.analysis_order == uninterrupted.analysis_order
    assert tuple(run.project for run in resumed.runs) == (
        uninterrupted.analysis_order
    )
    assert resumed.get("p0").status is ProjectRunStatus.REUSED
    assert set(resumed_projects) == {"p1", "p2"}
    assert _encoded_runs(resumed) == _encoded_runs(uninterrupted)
    resumed_context = SemanticContextCollector(resumed_service).collect(
        resumed,
    ).context.to_dict()
    assert resumed_context == uninterrupted_context
    assert _context_digest(resumed_context) == _context_digest(
        uninterrupted_context
    )


def test_cli_exposes_process_executor_and_rejects_invalid_combinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _simple_workspace(tmp_path, 2)
    process = runner.invoke(
        atlas_cli.app,
        [
            "analyze",
            str(tmp_path),
            "--executor",
            "process",
            "--workers",
            "2",
            "--no-recover",
        ],
    )
    assert process.exit_code == 0, process.output
    assert "projects: 2" in process.stdout

    invalid = runner.invoke(
        atlas_cli.app,
        [
            "analyze",
            str(tmp_path),
            "--executor",
            "serial",
            "--workers",
            "2",
            "--no-recover",
        ],
    )
    assert invalid.exit_code == 2
    assert "serial executor requires --workers 1" in invalid.stderr

    monkeypatch.setattr(
        atlas_cli,
        "_analyzer_factory",
        lambda service: AnalyzerRegistry(),
    )
    custom = runner.invoke(
        atlas_cli.app,
        [
            "analyze",
            str(tmp_path),
            "--executor",
            "process",
            "--no-recover",
        ],
    )
    assert custom.exit_code == 2
    assert "only the built-in AnalyzerRegistry" in custom.stderr
