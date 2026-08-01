"""Replay PR132 against an existing Atlas semantic snapshot without reanalysis."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median
from time import perf_counter

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.knowledge_graph import KnowledgeGraph
from moughorai.risk_analysis import RiskAnalysisService
from moughorai.semantic_snapshot.models import (
    AtlasSemanticSnapshot,
    SEMANTIC_SNAPSHOT_FORMAT,
    canonical_json,
)


def replay(path: Path, *, repeats: int = 3) -> dict[str, object]:
    if repeats <= 0:
        raise ValueError("repeats must be positive")
    with path.open("r", encoding="utf-8") as stream:
        envelope = json.load(stream)
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
    snapshot = AtlasSemanticSnapshot.from_dict(raw_snapshot)
    context = dict(snapshot.semantic_context)
    if not isinstance(context, dict):
        raise ValueError("snapshot semantic_context must be an object")
    raw_graph = context.get("semantic_graph", {})
    if not isinstance(raw_graph, dict):
        raise ValueError("snapshot semantic_graph must be an object")
    graph = KnowledgeGraph.from_dict(raw_graph)
    summary = context.get("repository_summary", {})
    symbols = context.get("symbols", ())
    if not isinstance(summary, dict) or not isinstance(symbols, list):
        raise ValueError("snapshot lacks repository summary or symbol metadata")

    durations = []
    payloads = []
    for _ in range(repeats):
        iteration_graph = KnowledgeGraph(graph.nodes, graph.edges)
        started = perf_counter()
        report = RiskAnalysisService().analyze(
            iteration_graph,
            repository_summary=summary,
            symbol_metadata=tuple(item for item in symbols if isinstance(item, dict)),
        )
        durations.append(perf_counter() - started)
        payloads.append(json.dumps(
            report.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"))
    hashes = {hashlib.sha256(payload).hexdigest() for payload in payloads}
    if len(hashes) != 1:
        raise RuntimeError("PR132 snapshot replay is not deterministic")
    snapshot_bytes = path.stat().st_size
    payload_bytes = len(payloads[0])

    def serialized_size(semantic_context: dict[str, object]) -> int:
        candidate = AtlasSemanticSnapshot.create(
            WorkspaceSemanticContext(semantic_context),
            workspace_fingerprint=snapshot.workspace_fingerprint,
            analyzer_version=snapshot.analyzer_version,
            history_reference=snapshot.history_reference,
        )
        payload = candidate.to_dict()
        candidate_envelope = {
            "format": SEMANTIC_SNAPSHOT_FORMAT,
            "checksum": hashlib.sha256(
                canonical_json(payload).encode("utf-8")
            ).hexdigest(),
            "snapshot": payload,
        }
        return len((json.dumps(
            candidate_envelope,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n").encode("utf-8"))

    baseline_context = dict(context)
    baseline_context.pop("risk_analysis", None)
    enriched_context = dict(baseline_context)
    enriched_context["risk_analysis"] = json.loads(payloads[0].decode("utf-8"))
    baseline_bytes = serialized_size(baseline_context)
    enriched_bytes = serialized_size(enriched_context)
    feature_bytes = enriched_bytes - baseline_bytes
    return {
        "schema_version": 1,
        "snapshot": str(path.resolve()),
        "snapshot_bytes": snapshot_bytes,
        "graph_nodes": len(graph.nodes),
        "graph_edges": len(graph.edges),
        "repeats": repeats,
        "median_seconds": round(median(durations), 6),
        "measurement_scope": (
            "risk analysis with a cold graph digest; snapshot and graph loading excluded"
        ),
        "risk_payload_bytes": payload_bytes,
        "baseline_without_risk_bytes": baseline_bytes,
        "enriched_with_risk_bytes": enriched_bytes,
        "exact_feature_snapshot_bytes": feature_bytes,
        "exact_feature_snapshot_growth_percent": round(
            feature_bytes * 100 / baseline_bytes, 6
        ),
        "input_validation": "envelope-checksum-and-snapshot-id",
        "result_hash": next(iter(hashes)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    arguments = parser.parse_args()
    print(json.dumps(replay(arguments.snapshot, repeats=arguments.repeats), sort_keys=True))


if __name__ == "__main__":
    main()
