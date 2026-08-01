"""Benchmark deterministic PR133 report construction from an ASS snapshot.

Pass a path to ``latest.ass`` to replay an existing snapshot. With no path, the
benchmark uses a bounded deterministic synthetic PR127-PR129 context. Snapshot
loading, checksum verification, and graph construction are excluded from the
reported timings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import sys
from time import perf_counter
import tracemalloc
from typing import Any, Mapping

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.repository_report import (
    RepositoryReportContextSelector,
    RepositoryReportService,
)
from moughorai.semantic_snapshot.models import (
    AtlasSemanticSnapshot,
    SEMANTIC_SNAPSHOT_FORMAT,
    canonical_json,
)


DEFAULT_REPEATS = 5
DEFAULT_SYNTHETIC_PROJECTS = 250
MAX_SYNTHETIC_PROJECTS = 1_000_000


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)]


def _process_peak_rss_bytes() -> int | None:
    """Return the process peak working set without adding a runtime dependency."""

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        get_memory_info = psapi.GetProcessMemoryInfo
        get_memory_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_memory_info.restype = wintypes.BOOL
        current_process = kernel32.GetCurrentProcess()
        succeeded = get_memory_info(
            current_process,
            ctypes.byref(counters),
            counters.cb,
        )
        return int(counters.PeakWorkingSetSize) if succeeded else None
    try:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return peak if sys.platform == "darwin" else peak * 1024
    except (ImportError, OSError, ValueError):
        return None


def _snapshot_bytes(snapshot: AtlasSemanticSnapshot) -> bytes:
    payload = snapshot.to_dict()
    envelope = {
        "format": SEMANTIC_SNAPSHOT_FORMAT,
        "checksum": hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest(),
        "snapshot": payload,
    }
    return (
        json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _load_snapshot(path: Path) -> tuple[AtlasSemanticSnapshot, int]:
    raw_bytes = path.read_bytes()
    try:
        envelope = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot decode semantic snapshot: {exc}") from exc
    if (
        not isinstance(envelope, dict)
        or envelope.get("format") != SEMANTIC_SNAPSHOT_FORMAT
    ):
        raise ValueError("semantic snapshot envelope is invalid")
    raw_snapshot = envelope.get("snapshot")
    if not isinstance(raw_snapshot, dict):
        raise ValueError("semantic snapshot envelope must contain an object snapshot")
    checksum = hashlib.sha256(
        canonical_json(raw_snapshot).encode("utf-8")
    ).hexdigest()
    if envelope.get("checksum") != checksum:
        raise ValueError("semantic snapshot checksum mismatch")
    # from_dict also verifies the deterministic ASS snapshot identifier.
    return AtlasSemanticSnapshot.from_dict(raw_snapshot), len(raw_bytes)


def _synthetic_snapshot(project_count: int) -> AtlasSemanticSnapshot:
    if not 1 <= project_count <= MAX_SYNTHETIC_PROJECTS:
        raise ValueError(
            "synthetic project count must be between 1 and "
            f"{MAX_SYNTHETIC_PROJECTS}"
        )
    projects = [
        {
            "name": "synthetic" if index == 0 else f"module-{index:04d}",
            "path": "." if index == 0 else f"modules/module-{index:04d}",
            "files": 40 + index % 11,
            "size": 4_096 + index * 17,
            "build_systems": ["Maven"],
        }
        for index in range(project_count)
    ]
    graph_nodes = [
        KnowledgeNode(
            "repository:synthetic",
            KnowledgeKind.REPOSITORY,
            "synthetic",
            qualified_name="synthetic",
        )
    ]
    graph_nodes.extend(
        KnowledgeNode(
            f"project:module-{index:04d}",
            KnowledgeKind.PROJECT,
            project["name"],
            qualified_name=project["name"],
            project_id=project["name"],
        )
        for index, project in enumerate(projects)
    )
    graph_edges = [
        KnowledgeEdge(
            f"project:module-{index:04d}",
            "repository:synthetic",
            KnowledgeRelation.BELONGS_TO,
            ("synthetic-project-ownership",),
        )
        for index in range(project_count)
    ]
    graph_edges.extend(
        KnowledgeEdge(
            f"project:module-{index:04d}",
            f"project:module-{index - 1:04d}",
            KnowledgeRelation.DEPENDS_ON,
            ("synthetic-project-dependency",),
        )
        for index in range(1, project_count)
    )
    graph = KnowledgeGraph(graph_nodes, graph_edges)
    total_files = sum(int(project["files"]) for project in projects)
    total_bytes = sum(int(project["size"]) for project in projects)
    context = WorkspaceSemanticContext({
        "schema_version": 1,
        "workspace": {
            "root": ".",
            "projects": [
                {
                    "name": project["name"],
                    "path": project["path"],
                    "dependencies": (
                        [] if index == 0 else [projects[index - 1]["name"]]
                    ),
                }
                for index, project in enumerate(projects)
            ],
        },
        "repository_summary": {
            "schema_version": 1,
            "root": ".",
            "project_count": project_count,
            "projects": projects,
            "inventoried_file_count": total_files,
            "inventoried_file_bytes": total_bytes,
            "inventoried_file_size_error_count": 0,
            "classified_non_test_source_files": total_files * 3 // 4,
            "classified_test_source_files": total_files // 4,
            "classified_generated_files": 0,
            "language_file_counts": {
                "Java": total_files * 9 // 10,
                "XML": total_files - total_files * 9 // 10,
            },
            "build_systems": ["Maven"],
            "frameworks": [],
            "entry_points": ["synthetic:src/main/java/example/Main.java"],
            "module_hierarchy": [
                {
                    "project": project["name"],
                    "parent": None if index == 0 else "synthetic",
                }
                for index, project in enumerate(projects)
            ],
            "declared_dependency_count_by_ecosystem": {
                "maven": max(0, project_count - 1),
            },
            "dependency_manifest_count_by_ecosystem": {
                "maven": project_count,
            },
            "total_declared_dependency_records": max(0, project_count - 1),
        },
        "semantic_graph": graph.to_dict(),
    })
    return AtlasSemanticSnapshot.create(
        context,
        workspace_fingerprint="synthetic-pr133-workspace-v1",
        analyzer_version="benchmark-pr133/1",
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _prepare_graph(
    context: Mapping[str, object],
) -> tuple[KnowledgeGraph | None, str | None]:
    existing_digest = ""
    for key in ("repository_report", "risk_analysis", "reachability"):
        candidate = str(_mapping(context.get(key)).get("graph_digest") or "").strip()
        if candidate:
            existing_digest = candidate
            break
    raw_graph = context.get("semantic_graph")
    graph = KnowledgeGraph.from_dict(raw_graph) if isinstance(raw_graph, Mapping) else None
    if graph is not None:
        canonical_digest = graph.stable_digest()
        if existing_digest and existing_digest != canonical_digest:
            raise ValueError(
                "persisted graph digest does not match the canonical semantic graph"
            )
        existing_digest = existing_digest or canonical_digest
    return graph, existing_digest or None


def _project_snapshot(
    source: AtlasSemanticSnapshot,
    semantic_context: Mapping[str, object],
) -> AtlasSemanticSnapshot:
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(dict(semantic_context)),
        workspace_fingerprint=source.workspace_fingerprint,
        analyzer_version=source.analyzer_version,
        history_reference=source.history_reference,
    )


def benchmark(
    snapshot_path: Path | None = None,
    *,
    synthetic_projects: int = DEFAULT_SYNTHETIC_PROJECTS,
    token_budget: int = RepositoryReportContextSelector.DEFAULT_TOKEN_BUDGET,
    repeats: int = DEFAULT_REPEATS,
    measure_memory: bool = False,
) -> dict[str, object]:
    if token_budget <= 0:
        raise ValueError("token budget must be positive")
    if repeats < 2:
        raise ValueError("benchmark repeats must be at least two")
    if snapshot_path is None:
        snapshot = _synthetic_snapshot(synthetic_projects)
        original_snapshot_bytes = len(_snapshot_bytes(snapshot))
        mode = "synthetic"
        input_name = "synthetic-pr127-pr129"
    else:
        snapshot, original_snapshot_bytes = _load_snapshot(snapshot_path)
        mode = "snapshot-replay"
        input_name = snapshot_path.name

    original_context = dict(snapshot.semantic_context)
    graph, graph_digest = _prepare_graph(original_context)
    baseline_context = dict(original_context)
    baseline_context.pop("repository_report", None)

    service = RepositoryReportService()
    selector = RepositoryReportContextSelector()
    build_durations: list[float] = []
    serialization_durations: list[float] = []
    selection_durations: list[float] = []
    report_payloads: list[bytes] = []
    selected_payloads: list[bytes] = []
    projected_payloads: list[bytes] = []
    reports = []
    selected_reports = []

    for _ in range(repeats):
        started = perf_counter()
        report = service.build(
            baseline_context,
            graph_digest=graph_digest,
            knowledge_graph=graph,
        )
        build_durations.append(perf_counter() - started)

        started = perf_counter()
        report_payload = report.to_json().encode("utf-8")
        serialization_durations.append(perf_counter() - started)

        started = perf_counter()
        selected = selector.select(report, token_budget=token_budget)
        selection_durations.append(perf_counter() - started)
        selected_payload = selected.to_json().encode("utf-8")

        enriched_context = dict(baseline_context)
        enriched_context["repository_report"] = report.to_dict()
        projected = _project_snapshot(snapshot, enriched_context)

        reports.append(report)
        selected_reports.append(selected)
        report_payloads.append(report_payload)
        selected_payloads.append(selected_payload)
        projected_payloads.append(_snapshot_bytes(projected))

    report_hashes = {_digest(payload) for payload in report_payloads}
    selected_hashes = {_digest(payload) for payload in selected_payloads}
    projected_hashes = {_digest(payload) for payload in projected_payloads}
    if not (
        len(report_hashes) == len(selected_hashes) == len(projected_hashes) == 1
    ):
        raise RuntimeError("PR133 output changed across identical benchmark repeats")

    report = reports[0]
    selected = selected_reports[0]
    expected_selected_tokens = selector.estimator.estimate(
        selected_payloads[0].decode("utf-8")
    )
    if selected.selection.estimated_tokens != expected_selected_tokens:
        raise RuntimeError("PR133 selected token estimate is not exact")

    peak_traced_memory_bytes: int | None = None
    if measure_memory:
        tracemalloc.start()
        try:
            measured_report = service.build(
                baseline_context,
                graph_digest=graph_digest,
                knowledge_graph=graph,
            )
            measured_report.to_json()
            selector.select(measured_report, token_budget=token_budget).to_json()
            _, peak_traced_memory_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

    baseline_snapshot = _project_snapshot(snapshot, baseline_context)
    baseline_snapshot_bytes = len(_snapshot_bytes(baseline_snapshot))
    projected_snapshot_bytes = len(projected_payloads[0])
    report_snapshot_bytes = projected_snapshot_bytes - baseline_snapshot_bytes
    growth_percent = (
        report_snapshot_bytes * 100 / baseline_snapshot_bytes
        if baseline_snapshot_bytes
        else 0.0
    )

    return {
        "schema_version": 1,
        "benchmark": "pr133-repository-report",
        "mode": mode,
        "input_name": input_name,
        "input_validation": "envelope-checksum-and-snapshot-id",
        "repeats": repeats,
        "determinism_verified": True,
        "measurement_scope": (
            "report build, canonical serialization, and token-budgeted context "
            "selection; snapshot loading and graph construction excluded"
        ),
        "timings_seconds": {
            "build": [round(value, 6) for value in build_durations],
            "build_median": round(median(build_durations), 6),
            "build_p95": round(_p95(build_durations), 6),
            "serialization": [round(value, 6) for value in serialization_durations],
            "serialization_median": round(median(serialization_durations), 6),
            "serialization_p95": round(_p95(serialization_durations), 6),
            "context_selection": [round(value, 6) for value in selection_durations],
            "context_selection_median": round(median(selection_durations), 6),
            "context_selection_p95": round(_p95(selection_durations), 6),
        },
        "memory_measurement_method": (
            "tracemalloc-peak-after-snapshot-and-graph-load"
            if measure_memory else "not-requested"
        ),
        "peak_traced_memory_bytes": peak_traced_memory_bytes,
        "process_peak_rss_bytes": _process_peak_rss_bytes(),
        "original_snapshot_bytes": original_snapshot_bytes,
        "baseline_without_report_bytes": baseline_snapshot_bytes,
        "projected_with_report_bytes": projected_snapshot_bytes,
        "projected_report_snapshot_bytes": report_snapshot_bytes,
        "projected_snapshot_increase_percent": round(growth_percent, 6),
        "report_bytes": len(report_payloads[0]),
        "selected_context_bytes": len(selected_payloads[0]),
        "report_item_count": len(report.items),
        "report_evidence_count": len(report.evidence_index),
        "selected_item_count": len(selected.items),
        "selected_evidence_count": len(selected.evidence_index),
        "selected_omitted_item_count": selected.selection.omitted_item_count,
        "token_budget": token_budget,
        "selected_token_count": selected.selection.estimated_tokens,
        "graph_digest": report.graph_digest,
        "canonical_graph_node_count": len(graph.nodes) if graph is not None else 0,
        "canonical_graph_edge_count": len(graph.edges) if graph is not None else 0,
        "input_snapshot_id": snapshot.snapshot_id,
        "report_hash": next(iter(report_hashes)),
        "selected_context_hash": next(iter(selected_hashes)),
        "projected_snapshot_hash": next(iter(projected_hashes)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "snapshot",
        nargs="?",
        type=Path,
        help="Path to an Atlas latest.ass snapshot; omit for bounded synthetic mode.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=DEFAULT_REPEATS,
        help="Repeated deterministic timing samples (minimum 2).",
    )
    parser.add_argument(
        "--measure-memory",
        action="store_true",
        help="Measure peak traced Python allocations for build/serialize/select.",
    )
    parser.add_argument(
        "--synthetic-projects",
        type=int,
        default=DEFAULT_SYNTHETIC_PROJECTS,
        help=(
            "Synthetic project count when no snapshot is supplied "
            f"(1-{MAX_SYNTHETIC_PROJECTS})."
        ),
    )
    parser.add_argument(
        "--token-budget",
        type=int,
        default=RepositoryReportContextSelector.DEFAULT_TOKEN_BUDGET,
    )
    arguments = parser.parse_args()
    result = benchmark(
        arguments.snapshot,
        synthetic_projects=arguments.synthetic_projects,
        token_budget=arguments.token_budget,
        repeats=arguments.repeats,
        measure_memory=arguments.measure_memory,
    )
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
