"""Opt-in deterministic scale benchmark for PR132 risk and hotspot analysis."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from statistics import median
import tracemalloc
from time import perf_counter

from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.risk_analysis import RiskAnalysisService


def nearest_rank(values: list[float], percentile: float) -> float:
    """Return the deterministic nearest-rank percentile of non-empty values."""

    if not values:
        raise ValueError("percentile values must not be empty")
    if not 0.0 < percentile <= 1.0:
        raise ValueError("percentile must be greater than zero and at most one")
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1)
    return ordered[index]


def build_graph(nodes: int, shape: str) -> KnowledgeGraph:
    if nodes <= 0:
        raise ValueError("nodes must be positive")
    graph_nodes = tuple(
        KnowledgeNode(
            f"type-{index:07d}",
            KnowledgeKind.TYPE,
            f"Type{index:07d}",
            qualified_name=f"benchmark.Type{index:07d}",
            project_id="benchmark",
            language="java",
        )
        for index in range(nodes)
    )
    if shape == "chain":
        edges = tuple(
            KnowledgeEdge(
                f"type-{index:07d}",
                f"type-{index + 1:07d}",
                KnowledgeRelation.INHERITS,
                ("benchmark-chain",),
            )
            for index in range(nodes - 1)
        )
    elif shape == "high-degree":
        edges = tuple(
            KnowledgeEdge(
                "type-0000000",
                f"type-{index:07d}",
                KnowledgeRelation.CALLS,
                ("benchmark-high-degree",),
            )
            for index in range(1, nodes)
        )
    elif shape == "sparse":
        edges = tuple(
            KnowledgeEdge(
                f"type-{index:07d}",
                f"type-{index + 1:07d}",
                KnowledgeRelation.INHERITS,
                ("benchmark-sparse",),
            )
            for index in range(0, nodes - 1, 10)
        )
    else:
        raise ValueError(f"unsupported graph shape: {shape}")
    return KnowledgeGraph(graph_nodes, edges)


def run(*, nodes: int, shape: str, repeats: int) -> dict[str, object]:
    if repeats <= 0:
        raise ValueError("repeats must be positive")
    graph = build_graph(nodes, shape)
    symbols = tuple(
        {
            "id": item.id,
            "project_id": "benchmark",
            "source": f"src/main/java/benchmark/{item.name}.java",
            "metadata": {},
        }
        for item in graph.nodes
    )
    durations = []
    warm_durations = []
    peaks = []
    hashes = []
    payload_sizes = []
    # Warm-up uses a distinct graph so each measured run includes first-use
    # canonical digest calculation without timing graph or symbol construction.
    RiskAnalysisService().analyze(
        KnowledgeGraph(graph.nodes, graph.edges),
        symbol_metadata=symbols,
    )
    for _ in range(repeats):
        service = RiskAnalysisService()
        iteration_graph = KnowledgeGraph(graph.nodes, graph.edges)
        tracemalloc.start()
        started = perf_counter()
        report = service.analyze(iteration_graph, symbol_metadata=symbols)
        durations.append(perf_counter() - started)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        warm_started = perf_counter()
        cached = service.analyze(iteration_graph, symbol_metadata=symbols)
        warm_durations.append(perf_counter() - warm_started)
        if cached is not report:
            raise RuntimeError("PR132 warm benchmark did not return the cached report")
        payload = json.dumps(
            report.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        peaks.append(peak)
        payload_sizes.append(len(payload))
        hashes.append(hashlib.sha256(payload).hexdigest())
    if len(set(hashes)) != 1:
        raise RuntimeError("PR132 result hash changed across identical benchmark runs")
    # For small repeat counts, nearest-rank p95 intentionally resolves to the
    # slowest observation rather than the first or median observation.
    p95 = nearest_rank(durations, 0.95)
    warm_p95 = nearest_rank(warm_durations, 0.95)
    return {
        "schema_version": 1,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "shape": shape,
        "repeats": repeats,
        "median_seconds": round(median(durations), 6),
        "p95_seconds": round(p95, 6),
        "warm_cache_median_seconds": round(median(warm_durations), 6),
        "warm_cache_p95_seconds": round(warm_p95, 6),
        "warm_cache_identity_preserved": True,
        "measurement_scope": (
            "risk analysis with a cold graph digest; graph and symbol construction excluded"
        ),
        "memory_scope": (
            "incremental Python allocations during risk analysis only; not process RSS"
        ),
        "peak_traced_python_memory_mib": round(max(peaks) / (1024 * 1024), 2),
        "risk_payload_bytes": max(payload_sizes),
        "result_hash": hashes[0],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=10_000)
    parser.add_argument(
        "--shape", choices=("sparse", "chain", "high-degree"), default="sparse"
    )
    parser.add_argument("--repeats", type=int, default=5)
    arguments = parser.parse_args()
    print(json.dumps(run(
        nodes=arguments.nodes,
        shape=arguments.shape,
        repeats=arguments.repeats,
    ), sort_keys=True))


if __name__ == "__main__":
    main()
