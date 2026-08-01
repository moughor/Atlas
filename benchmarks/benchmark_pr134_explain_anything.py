"""Benchmark PR134 indexed resolution and bounded context selection.

With no snapshot argument, the benchmark uses a deterministic 10K-node graph.
Use ``--nodes 10000 100000 1000000`` for the planned scale matrix, or pass one
or more ``latest.ass`` paths for checksum-verified snapshot replay. Snapshot and
graph loading are reported separately and excluded from resolver/selection times.
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
from typing import Iterable, Mapping

from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.repository_report.safety import contains_absolute_path_text
from moughorai.semantic_evidence import EvidenceIndex, EvidenceKind, EvidenceRecord
from moughorai.semantic_snapshot.models import (
    AtlasSemanticSnapshot,
    SEMANTIC_SNAPSHOT_FORMAT,
    canonical_json,
)
from moughorai.structured_explanation.models import (
    ExplanationAttribute,
    ExplanationAvailability,
    ExplanationCapability,
    ExplanationConfidenceBasis,
    ExplanationFact,
    ExplanationFactKind,
    ExplanationRequest,
    ExplanationSubject,
    StructuredExplanation,
)
from moughorai.structured_explanation.selection import StructuredExplanationSelector
from moughorai.subject_resolution import (
    CanonicalSubjectResolver,
    ResolutionStatus,
    SubjectQuery,
)


DEFAULT_REPEATS = 5
DEFAULT_NODE_COUNT = 10_000
DEFAULT_LOOKUPS = 1_000
DEFAULT_FACT_COUNT = 96
MAXIMUM_NODE_COUNT = 1_000_000
PRODUCER_VERSION = "atlas-pr134/1"


def _digest(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)]


def _process_peak_rss_bytes() -> int | None:
    """Return process peak working set without adding a runtime dependency."""

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
        succeeded = get_memory_info(
            kernel32.GetCurrentProcess(),
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


def _synthetic_graph(node_count: int) -> KnowledgeGraph:
    if not 2 <= node_count <= MAXIMUM_NODE_COUNT:
        raise ValueError(
            f"node count must be between 2 and {MAXIMUM_NODE_COUNT}"
        )
    nodes = [
        KnowledgeNode(
            "repository:synthetic",
            KnowledgeKind.REPOSITORY,
            "synthetic",
            qualified_name="synthetic",
        )
    ]
    nodes.extend(
        KnowledgeNode(
            f"type:synthetic-{index:07d}",
            KnowledgeKind.TYPE,
            f"Synthetic{index:07d}",
            qualified_name=f"benchmark.Synthetic{index:07d}",
            project_id=f"module-{index % 100:03d}",
            language="java",
        )
        for index in range(node_count - 1)
    )
    edges = [
        KnowledgeEdge(
            f"type:synthetic-{index:07d}",
            "repository:synthetic",
            KnowledgeRelation.BELONGS_TO,
            ("benchmark-ownership",),
        )
        for index in range(node_count - 1)
    ]
    edges.extend(
        KnowledgeEdge(
            f"type:synthetic-{index:07d}",
            f"type:synthetic-{index - 1:07d}",
            KnowledgeRelation.RELATED_TO,
            ("benchmark-relation",),
        )
        for index in range(1, node_count - 1)
    )
    return KnowledgeGraph(nodes, edges)


def _load_snapshot(
    path: Path,
) -> tuple[AtlasSemanticSnapshot, KnowledgeGraph, tuple[Mapping[str, object], ...], int]:
    raw = path.read_bytes()
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot decode semantic snapshot: {exc}") from exc
    if (
        not isinstance(envelope, Mapping)
        or envelope.get("format") != SEMANTIC_SNAPSHOT_FORMAT
    ):
        raise ValueError("semantic snapshot envelope is invalid")
    raw_snapshot = envelope.get("snapshot")
    if not isinstance(raw_snapshot, Mapping):
        raise ValueError("semantic snapshot envelope must contain an object snapshot")
    checksum = _digest(canonical_json(raw_snapshot))
    if envelope.get("checksum") != checksum:
        raise ValueError("semantic snapshot checksum mismatch")
    snapshot = AtlasSemanticSnapshot.from_dict(raw_snapshot)
    raw_graph = snapshot.semantic_context.get("semantic_graph")
    if not isinstance(raw_graph, Mapping):
        raise ValueError("semantic snapshot does not contain a canonical graph")
    graph = KnowledgeGraph.from_dict(raw_graph)
    raw_symbols = snapshot.semantic_context.get("symbols", ())
    symbols = (
        tuple(item for item in raw_symbols if isinstance(item, Mapping))
        if isinstance(raw_symbols, list)
        else ()
    )
    return snapshot, graph, symbols, len(raw)


def _query_ids(graph: KnowledgeGraph, count: int) -> tuple[str, ...]:
    safe = tuple(
        node.id
        for node in graph.nodes
        if node.kind not in {KnowledgeKind.REPOSITORY, KnowledgeKind.WORKSPACE}
        and not contains_absolute_path_text(node.id)
    )
    if not safe:
        safe = tuple(
            node.id for node in graph.nodes
            if not contains_absolute_path_text(node.id)
        )
    if not safe:
        raise ValueError("canonical graph has no path-safe subjects to benchmark")
    return tuple(safe[index * len(safe) // count % len(safe)] for index in range(count))


def _explanation_fixture(
    resolver: CanonicalSubjectResolver,
    subject_id: str,
    *,
    snapshot_id: str,
    fact_count: int,
) -> StructuredExplanation:
    resolution = resolver.resolve(SubjectQuery(subject_id))
    if resolution.status is not ResolutionStatus.RESOLVED or resolution.subject is None:
        raise ValueError(f"benchmark subject did not resolve: {subject_id}")
    candidate = resolution.subject
    subject = ExplanationSubject(
        candidate.canonical_id,
        candidate.kind.value,
        candidate.name,
        candidate.qualified_name,
        candidate.project,
        candidate.language,
        candidate.match_basis.value,
    )
    lineage = f"benchmark-lineage:{_digest(snapshot_id + resolver.graph_digest)}"
    records: list[EvidenceRecord] = []
    facts: list[ExplanationFact] = []
    for index in range(fact_count):
        logical_key = f"benchmark-fact:{index:04d}"
        statement = (
            f"{candidate.name} resolves to one canonical subject."
            if index == 0
            else f"Deterministic benchmark fact {index} for {candidate.name}."
        )
        source_refs = (candidate.canonical_id,)
        fact_id = "explanation-fact:" + _digest(canonical_json({
            "logical_key": logical_key,
            "subject_id": candidate.canonical_id,
            "source_refs": source_refs,
            "statement": statement,
        }))
        evidence = EvidenceRecord.create(
            EvidenceKind.GRAPH_NODE if index == 0 else EvidenceKind.SEMANTIC_FACT,
            fact_id,
            PRODUCER_VERSION,
            lineage,
            source_refs=source_refs,
            scope=candidate.canonical_id,
            language=candidate.language,
            detail={
                "benchmark_fact": index,
                "logical_key": logical_key,
                "subject": candidate.canonical_id,
            },
        )
        records.append(evidence)
        facts.append(ExplanationFact(
            fact_id,
            ExplanationFactKind.IDENTITY if index == 0 else ExplanationFactKind.METADATA,
            candidate.canonical_id,
            "Canonical subject identity" if index == 0 else f"Bounded fact {index}",
            statement,
            ExplanationAvailability.AVAILABLE,
            0 if index == 0 else 20 + index,
            (ExplanationAttribute("ordinal", index),),
            None,
            ExplanationConfidenceBasis.NOT_APPLICABLE,
            (PRODUCER_VERSION,),
            (evidence.evidence_id,),
            (),
            (candidate.canonical_id,),
        ))
    return StructuredExplanation(
        ExplanationRequest(candidate.canonical_id, candidate.kind.value),
        ExplanationAvailability.AVAILABLE,
        snapshot_id,
        resolver.graph_digest,
        _digest(f"input:{snapshot_id}:{candidate.canonical_id}"),
        lineage,
        subject,
        (),
        tuple(facts),
        (ExplanationCapability(
            "canonical_subject_resolution",
            ExplanationAvailability.AVAILABLE,
            (PRODUCER_VERSION,),
            1.0,
        ),),
        EvidenceIndex(records).freeze(),
    )


def _benchmark_graph(
    graph: KnowledgeGraph,
    *,
    symbols: Iterable[Mapping[str, object]],
    input_name: str,
    mode: str,
    snapshot_id: str,
    snapshot_bytes: int | None,
    load_seconds: float,
    repeats: int,
    lookup_count: int,
    fact_count: int,
    token_budget: int,
) -> dict[str, object]:
    digest_started = perf_counter()
    graph_digest = graph.stable_digest()
    digest_seconds = perf_counter() - digest_started

    symbol_tuple = tuple(symbols)
    index_durations: list[float] = []
    resolver: CanonicalSubjectResolver | None = None
    for _ in range(repeats):
        started = perf_counter()
        resolver = CanonicalSubjectResolver(
            graph,
            symbols=symbol_tuple,
            graph_digest=graph_digest,
        )
        index_durations.append(perf_counter() - started)
    if resolver is None:
        raise RuntimeError("resolver benchmark did not construct an index")

    bounded_subjects = tuple(
        node.id for node in graph.nodes
        if node.kind in {KnowledgeKind.REPOSITORY, KnowledgeKind.WORKSPACE}
    )
    if not bounded_subjects:
        bounded_subjects = (graph.nodes[0].id,)
    bounded_subject, bounded_total = max(
        (
            (node_id, graph.bounded_incident(node_id, limit=48)[1])
            for node_id in bounded_subjects
        ),
        key=lambda item: (item[1], item[0]),
    )
    bounded_durations: list[float] = []
    bounded_hashes: set[str] = set()
    bounded_selected_count = 0
    for _ in range(repeats):
        started = perf_counter()
        bounded_edges, observed_total = graph.bounded_incident(
            bounded_subject,
            limit=48,
        )
        bounded_durations.append(perf_counter() - started)
        if observed_total != bounded_total:
            raise RuntimeError("bounded incident count changed across repeats")
        bounded_selected_count = len(bounded_edges)
        bounded_hashes.add(_digest(json.dumps([
            {
                "direction": direction,
                "edge": {
                    "source": edge.source,
                    "target": edge.target,
                    "kind": edge.relation.value,
                    "evidence": list(edge.evidence),
                },
            }
            for direction, edge in bounded_edges
        ], ensure_ascii=False, separators=(",", ":"), sort_keys=True)))
    if len(bounded_hashes) != 1:
        raise RuntimeError("bounded incident ordering changed across repeats")

    query_ids = _query_ids(graph, lookup_count)
    lookup_durations: list[float] = []
    lookup_hashes: set[str] = set()
    for _ in range(repeats):
        started = perf_counter()
        results = tuple(resolver.resolve(SubjectQuery(item)) for item in query_ids)
        lookup_durations.append(perf_counter() - started)
        if any(item.status is not ResolutionStatus.RESOLVED for item in results):
            raise RuntimeError("an exact canonical benchmark lookup did not resolve")
        lookup_hashes.add(_digest("\n".join(item.to_json() for item in results)))
    if len(lookup_hashes) != 1:
        raise RuntimeError("PR134 resolver output changed across identical repeats")

    explanation = _explanation_fixture(
        resolver,
        query_ids[len(query_ids) // 2],
        snapshot_id=snapshot_id,
        fact_count=fact_count,
    )
    selector = StructuredExplanationSelector()
    selection_durations: list[float] = []
    selection_hashes: set[str] = set()
    selected = None
    for _ in range(repeats):
        started = perf_counter()
        selected = selector.select(explanation, token_budget=token_budget)
        selection_durations.append(perf_counter() - started)
        selection_hashes.add(_digest(selected.to_json()))
        if StructuredExplanation.from_dict(selected.to_dict()).to_dict() != selected.to_dict():
            raise RuntimeError("PR134 selected context round trip is not exact")
    if len(selection_hashes) != 1:
        raise RuntimeError("PR134 selected context changed across identical repeats")
    if selected is None:
        raise RuntimeError("context-selection benchmark produced no result")

    lookup_per_item = [value / lookup_count for value in lookup_durations]
    return {
        "schema_version": 1,
        "benchmark": "pr134-explain-anything",
        "mode": mode,
        "input_name": input_name,
        "measurement_scope": (
            "cold in-memory resolver index construction, warm exact canonical-ID "
            "lookup, bounded high-degree traversal, and whole-fact context selection; "
            "snapshot/graph loading excluded"
        ),
        "input_validation": (
            "envelope-checksum-and-snapshot-id"
            if mode == "snapshot-replay"
            else "deterministic-synthetic-graph"
        ),
        "repeats": repeats,
        "determinism_verified": True,
        "snapshot_load_seconds": round(load_seconds, 6),
        "graph_digest_seconds": round(digest_seconds, 6),
        "timings_seconds": {
            "resolver_index_build": [round(value, 6) for value in index_durations],
            "resolver_index_build_median": round(median(index_durations), 6),
            "resolver_index_build_p95": round(_p95(index_durations), 6),
            "bounded_incident": [round(value, 6) for value in bounded_durations],
            "bounded_incident_median": round(median(bounded_durations), 6),
            "bounded_incident_p95": round(_p95(bounded_durations), 6),
            "warm_lookup_batch": [round(value, 6) for value in lookup_durations],
            "warm_lookup_batch_median": round(median(lookup_durations), 6),
            "warm_lookup_batch_p95": round(_p95(lookup_durations), 6),
            "warm_lookup_per_subject_median": round(median(lookup_per_item), 9),
            "warm_lookup_per_subject_p95": round(_p95(lookup_per_item), 9),
            "context_selection": [round(value, 6) for value in selection_durations],
            "context_selection_median": round(median(selection_durations), 6),
            "context_selection_p95": round(_p95(selection_durations), 6),
        },
        "canonical_graph_node_count": len(graph.nodes),
        "canonical_graph_edge_count": len(graph.edges),
        "lookup_count_per_repeat": lookup_count,
        "bounded_incident_subject_hash": _digest(bounded_subject),
        "bounded_incident_total_count": bounded_total,
        "bounded_incident_selected_count": bounded_selected_count,
        "fixture_fact_count": fact_count,
        "selected_fact_count": len(selected.facts),
        "omitted_fact_count": selected.selection.omitted_fact_count,
        "selected_evidence_count": len(selected.evidence_index),
        "selected_context_bytes": len(selected.to_json().encode("utf-8")),
        "token_budget": token_budget,
        "selected_token_count": selected.selection.estimated_tokens,
        "snapshot_bytes": snapshot_bytes,
        "persisted_pr134_bytes": 0,
        "persisted_snapshot_increase_percent": 0.0,
        "process_peak_rss_bytes": _process_peak_rss_bytes(),
        "graph_digest": graph_digest,
        "resolution_hash": next(iter(lookup_hashes)),
        "selected_context_hash": next(iter(selection_hashes)),
    }


def benchmark_synthetic(
    node_count: int,
    *,
    repeats: int = DEFAULT_REPEATS,
    lookup_count: int = DEFAULT_LOOKUPS,
    fact_count: int = DEFAULT_FACT_COUNT,
    token_budget: int = StructuredExplanationSelector.DEFAULT_TOKEN_BUDGET,
) -> dict[str, object]:
    started = perf_counter()
    graph = _synthetic_graph(node_count)
    graph_construction_seconds = perf_counter() - started
    result = _benchmark_graph(
        graph,
        symbols=(),
        input_name=f"synthetic-{node_count}-node-graph",
        mode="synthetic",
        snapshot_id=f"benchmark-synthetic-{node_count}",
        snapshot_bytes=None,
        load_seconds=0.0,
        repeats=repeats,
        lookup_count=lookup_count,
        fact_count=fact_count,
        token_budget=token_budget,
    )
    result["synthetic_graph_construction_seconds"] = round(
        graph_construction_seconds, 6
    )
    return result


def benchmark_snapshot(
    path: Path,
    *,
    repeats: int = DEFAULT_REPEATS,
    lookup_count: int = DEFAULT_LOOKUPS,
    fact_count: int = DEFAULT_FACT_COUNT,
    token_budget: int = StructuredExplanationSelector.DEFAULT_TOKEN_BUDGET,
) -> dict[str, object]:
    started = perf_counter()
    snapshot, graph, symbols, snapshot_bytes = _load_snapshot(path)
    load_seconds = perf_counter() - started
    return _benchmark_graph(
        graph,
        symbols=symbols,
        input_name=path.name,
        mode="snapshot-replay",
        snapshot_id=snapshot.snapshot_id,
        snapshot_bytes=snapshot_bytes,
        load_seconds=load_seconds,
        repeats=repeats,
        lookup_count=lookup_count,
        fact_count=fact_count,
        token_budget=token_budget,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "snapshots",
        nargs="*",
        type=Path,
        help="Checksum-verified Atlas latest.ass snapshots to replay.",
    )
    parser.add_argument(
        "--nodes",
        nargs="+",
        type=int,
        help=(
            "Synthetic graph sizes. Suggested matrix: 10000 100000 1000000. "
            "Defaults to 10000 only when no snapshot is supplied."
        ),
    )
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--lookups", type=int, default=DEFAULT_LOOKUPS)
    parser.add_argument("--facts", type=int, default=DEFAULT_FACT_COUNT)
    parser.add_argument(
        "--token-budget",
        type=int,
        default=StructuredExplanationSelector.DEFAULT_TOKEN_BUDGET,
    )
    arguments = parser.parse_args()
    if arguments.repeats < 2:
        raise ValueError("benchmark repeats must be at least two")
    if arguments.lookups <= 0 or arguments.facts <= 0:
        raise ValueError("lookups and facts must be positive")
    if arguments.token_budget <= 0:
        raise ValueError("token budget must be positive")

    node_counts = arguments.nodes or (
        [] if arguments.snapshots else [DEFAULT_NODE_COUNT]
    )
    results = [
        benchmark_synthetic(
            count,
            repeats=arguments.repeats,
            lookup_count=arguments.lookups,
            fact_count=arguments.facts,
            token_budget=arguments.token_budget,
        )
        for count in node_counts
    ]
    results.extend(
        benchmark_snapshot(
            path,
            repeats=arguments.repeats,
            lookup_count=arguments.lookups,
            fact_count=arguments.facts,
            token_budget=arguments.token_budget,
        )
        for path in arguments.snapshots
    )
    print(json.dumps(
        {"schema_version": 1, "results": results},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
