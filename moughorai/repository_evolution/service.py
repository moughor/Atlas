from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import itertools
import json
import re

from moughorai.knowledge_graph import KnowledgeGraph, KnowledgeNode, KnowledgeRelation
from moughorai.measurement import MeasurementSession
from moughorai.risk_analysis import RiskAnalysisReport, RiskCapability, RiskMetricKind
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
    REPOSITORY_METADATA_RELIABILITY,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import (
    CanonicalSubjectResolver,
    SubjectCandidate,
    SubjectMatchBasis,
)

from .models import (
    REPOSITORY_EVOLUTION_PRODUCER,
    EvolutionCapability,
    EvolutionCapabilityKind,
    EvolutionChangeKind,
    EvolutionSnapshotReference,
    EvolutionState,
    NodeEvolution,
    RelationEvolution,
    RepositoryEvolutionRequest,
    RepositoryEvolutionResponse,
    repository_evolution_fingerprint,
)


_GIT_OBJECT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_PR132_GIT_PRODUCERS = {
    RiskMetricKind.CHANGE_FREQUENCY: "git-context.history.v1",
    RiskMetricKind.OWNERSHIP_CONCENTRATION: (
        "git-context.change-author-concentration.v1"
    ),
}
_ABSENCE_LIMITATION = (
    "Absence means absent from the canonical snapshot projection; it does not "
    "prove source deletion, runtime unreachability, or developer intent."
)
_MODIFICATION_LIMITATION = (
    "A changed canonical projection does not establish the source change, "
    "runtime effect, compatibility impact, or developer intent that caused it."
)
_COMMIT_LIMITATION = (
    "The Git head comes from bounded PR132 analysis evidence; snapshot capture "
    "did not prove a clean worktree or commit ancestry, so association is partial."
)
_PRODUCER_COMPARABILITY_LIMITATION = (
    "Matching analyzer versions do not prove identical configuration, language "
    "capabilities, producer inputs, or semantic coverage."
)


@dataclass(frozen=True, slots=True)
class _CommitObservation:
    head: str | None
    state: EvolutionState
    source_refs: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PreparedSnapshot:
    snapshot: AtlasSemanticSnapshot
    resolver: CanonicalSubjectResolver
    graph: KnowledgeGraph | None
    commit: _CommitObservation


class RepositoryEvolutionService:
    """Compare two verified semantic snapshots without inventing continuity."""

    def __init__(
        self,
        *,
        measurement: MeasurementSession | None = None,
    ) -> None:
        self._measurement = measurement or MeasurementSession()
        self._confidence = ConfidenceCalculator()

    def compare(
        self,
        base_snapshot: AtlasSemanticSnapshot,
        head_snapshot: AtlasSemanticSnapshot,
        request: RepositoryEvolutionRequest | None = None,
    ) -> RepositoryEvolutionResponse:
        selected_request = request or RepositoryEvolutionRequest()
        if not isinstance(selected_request, RepositoryEvolutionRequest):
            raise TypeError("repository evolution request is invalid")
        base = self._verify_snapshot(base_snapshot, "base")
        head = self._verify_snapshot(head_snapshot, "head")

        with self._measurement.scope(
            "repository_evolution.prepare",
            consumer="repository-evolution",
            sample_key=f"{base.snapshot_id}:{head.snapshot_id}",
        ) as scope:
            prepared_base = self._prepare(base)
            prepared_head = self._prepare(head)
            scope.add_units(2)
            scope.add_objects_produced(2)

        base_ref = self._reference(prepared_base)
        head_ref = self._reference(prepared_head)
        evidence = EvidenceIndex()
        snapshot_evidence = self._snapshot_evidence(prepared_base, prepared_head, evidence)
        commit_capability = self._commit_capability(
            prepared_base,
            prepared_head,
            evidence,
        )

        compatibility, compatibility_limitations = self._compatibility(
            prepared_base,
            prepared_head,
        )
        graph_evidence: tuple[str, ...] = ()
        if prepared_base.graph is not None and prepared_head.graph is not None:
            graph_evidence = self._graph_evidence(prepared_base, prepared_head, evidence)

        node_changes: tuple[NodeEvolution, ...] = ()
        relation_changes: tuple[RelationEvolution, ...] = ()
        total_nodes = omitted_nodes = unchanged_nodes = 0
        total_relations = omitted_relations = unchanged_relations = 0

        if compatibility in {EvolutionState.AVAILABLE, EvolutionState.PARTIAL}:
            with self._measurement.scope(
                "repository_evolution.compare_nodes",
                consumer="repository-evolution",
                sample_key=f"{base_ref.graph_digest}:{head_ref.graph_digest}",
            ) as scope:
                (
                    node_changes,
                    total_nodes,
                    omitted_nodes,
                    unchanged_nodes,
                ) = self._compare_nodes(
                    prepared_base,
                    prepared_head,
                    selected_request.maximum_node_changes,
                    evidence,
                )
                scope.add_units(total_nodes + unchanged_nodes)
                scope.add_objects_produced(len(node_changes))
                scope.set_objects_retained(len(node_changes))
            with self._measurement.scope(
                "repository_evolution.compare_relations",
                consumer="repository-evolution",
                sample_key=f"{base_ref.graph_digest}:{head_ref.graph_digest}",
            ) as scope:
                (
                    relation_changes,
                    total_relations,
                    omitted_relations,
                    unchanged_relations,
                ) = self._compare_relations(
                    prepared_base,
                    prepared_head,
                    selected_request.maximum_relation_changes,
                    evidence,
                )
                scope.add_units(total_relations + unchanged_relations)
                scope.add_objects_produced(len(relation_changes))
                scope.set_objects_retained(len(relation_changes))

        core_state = compatibility
        if core_state is EvolutionState.AVAILABLE and (
            prepared_base.resolver.limitations or prepared_head.resolver.limitations
        ):
            core_state = EvolutionState.PARTIAL
        core_limitations = tuple(sorted({
            *compatibility_limitations,
            *prepared_base.resolver.limitations,
            *prepared_head.resolver.limitations,
        }))
        if omitted_nodes:
            core_limitations = tuple(sorted({
                *core_limitations,
                f"{omitted_nodes} canonical node change(s) were omitted by the request bound.",
            }))
        if omitted_relations:
            core_limitations = tuple(sorted({
                *core_limitations,
                f"{omitted_relations} canonical relation change(s) were omitted by the request bound.",
            }))
        if core_state is EvolutionState.AVAILABLE and (omitted_nodes or omitted_relations):
            core_state = EvolutionState.PARTIAL

        capabilities = self._capabilities(
            snapshot_evidence,
            graph_evidence,
            core_state,
            core_limitations,
            commit_capability,
        )
        limitations = tuple(sorted({
            *core_limitations,
            *commit_capability.limitations,
            "Node removal plus node addition is not interpreted as rename or move continuity.",
            "PR141 does not infer API breakage, security causality, architecture drift, runtime behavior, ownership, migration safety, or developer intent.",
        }))
        if base.snapshot_id == head.snapshot_id:
            overall_state = EvolutionState.INSUFFICIENT
            limitations = tuple(sorted({
                *limitations,
                "Base and head are the same semantic snapshot; no evolution interval exists.",
            }))
        elif compatibility in {EvolutionState.UNAVAILABLE, EvolutionState.INCOMPATIBLE}:
            overall_state = compatibility
        else:
            # A clean snapshot-to-commit binding is not produced by current snapshots.
            # The roadmap slice therefore remains explicitly partial even when the
            # canonical pairwise comparison itself is exact.
            overall_state = EvolutionState.PARTIAL

        response = RepositoryEvolutionResponse(
            selected_request,
            base_ref,
            head_ref,
            overall_state,
            capabilities,
            node_changes,
            relation_changes,
            total_nodes,
            omitted_nodes,
            unchanged_nodes,
            total_relations,
            omitted_relations,
            unchanged_relations,
            evidence,
            repository_evolution_fingerprint(selected_request, base_ref, head_ref),
            limitations=limitations,
        )
        return response

    @staticmethod
    def _verify_snapshot(
        snapshot: AtlasSemanticSnapshot,
        side: str,
    ) -> AtlasSemanticSnapshot:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError(f"repository evolution {side} snapshot is invalid")
        # AtlasSemanticSnapshot is shallowly immutable for legacy compatibility.
        # Recompute its identity before trusting nested data.
        try:
            return AtlasSemanticSnapshot.from_dict(snapshot.to_dict())
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"repository evolution {side} snapshot failed integrity validation"
            ) from exc

    def _prepare(self, snapshot: AtlasSemanticSnapshot) -> _PreparedSnapshot:
        resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
        graph = resolver.graph
        return _PreparedSnapshot(
            snapshot,
            resolver,
            graph,
            self._commit_observation(snapshot, resolver.graph_digest),
        )

    @staticmethod
    def _reference(prepared: _PreparedSnapshot) -> EvolutionSnapshotReference:
        return EvolutionSnapshotReference(
            prepared.snapshot.snapshot_id,
            prepared.resolver.graph_digest,
            prepared.snapshot.analyzer_version,
            prepared.commit.head,
        )

    @staticmethod
    def _compatibility(
        base: _PreparedSnapshot,
        head: _PreparedSnapshot,
    ) -> tuple[EvolutionState, tuple[str, ...]]:
        if base.graph is None or head.graph is None:
            return EvolutionState.UNAVAILABLE, (
                "Both snapshots require a supported PR129 canonical graph.",
            )
        base_root = RepositoryEvolutionService._workspace_root(base.snapshot)
        head_root = RepositoryEvolutionService._workspace_root(head.snapshot)
        if base_root is None or head_root is None:
            return EvolutionState.UNAVAILABLE, (
                "Both snapshots require a persisted workspace root for pair identity.",
            )
        if base_root != head_root:
            return EvolutionState.INCOMPATIBLE, (
                "Snapshot workspace roots differ; cross-repository identity is unavailable.",
            )
        if base.snapshot.analyzer_version != head.snapshot.analyzer_version:
            return EvolutionState.INCOMPATIBLE, (
                "Analyzer versions differ; producer changes cannot be separated from repository evolution.",
            )
        if base.resolver.limitations or head.resolver.limitations:
            return EvolutionState.PARTIAL, tuple(sorted({
                *base.resolver.limitations,
                *head.resolver.limitations,
            }))
        return EvolutionState.AVAILABLE, (_PRODUCER_COMPARABILITY_LIMITATION,)

    @staticmethod
    def _workspace_root(snapshot: AtlasSemanticSnapshot) -> str | None:
        workspace = snapshot.semantic_context.get("workspace")
        if not isinstance(workspace, Mapping):
            return None
        root = workspace.get("root")
        if not isinstance(root, str) or not root.strip():
            return None
        return root.strip().replace("\\", "/").rstrip("/") or "/"

    @staticmethod
    def _snapshot_evidence(
        base: _PreparedSnapshot,
        head: _PreparedSnapshot,
        evidence: EvidenceIndex,
    ) -> tuple[str, str]:
        result = []
        for side, prepared in (("base", base), ("head", head)):
            record = EvidenceRecord.create(
                EvidenceKind.ANALYSIS_RESULT,
                "repository-evolution:snapshot-pair",
                REPOSITORY_EVOLUTION_PRODUCER,
                prepared.snapshot.snapshot_id,
                source_refs=(f"snapshot:{prepared.snapshot.snapshot_id}",),
                detail={
                    "side": side,
                    "snapshot_schema": prepared.snapshot.schema_version,
                },
                reliability=1.0,
                specificity=1.0,
            )
            result.append(evidence.add(record))
        return result[0], result[1]

    @staticmethod
    def _graph_evidence(
        base: _PreparedSnapshot,
        head: _PreparedSnapshot,
        evidence: EvidenceIndex,
    ) -> tuple[str, str]:
        result = []
        for side, prepared in (("base", base), ("head", head)):
            graph = prepared.graph
            if graph is None:  # pragma: no cover - caller guards both graphs
                raise RuntimeError("graph evidence requires a canonical graph")
            record = EvidenceRecord.create(
                EvidenceKind.ANALYSIS_RESULT,
                "repository-evolution:canonical-graph",
                REPOSITORY_EVOLUTION_PRODUCER,
                prepared.snapshot.snapshot_id,
                source_refs=(f"canonical-graph:{prepared.resolver.graph_digest}",),
                detail={
                    "side": side,
                    "graph_digest": prepared.resolver.graph_digest,
                    "node_count": len(graph.nodes),
                    "relation_count": sum(
                        1
                        for _item in RepositoryEvolutionService._relation_groups(graph)
                    ),
                },
                limitations=prepared.resolver.limitations,
                reliability=1.0,
                specificity=1.0,
            )
            result.append(evidence.add(record))
        return result[0], result[1]

    def _compare_nodes(
        self,
        base: _PreparedSnapshot,
        head: _PreparedSnapshot,
        limit: int,
        evidence: EvidenceIndex,
    ) -> tuple[tuple[NodeEvolution, ...], int, int, int]:
        base_items = self._node_payloads(base)
        head_items = self._node_payloads(head)
        selected: list[NodeEvolution] = []
        total = unchanged = 0
        left = right = 0
        while left < len(base_items) or right < len(head_items):
            before = base_items[left] if left < len(base_items) else None
            after = head_items[right] if right < len(head_items) else None
            before_id = before.id if before is not None else None
            after_id = after.id if after is not None else None
            if before is not None and (after is None or before_id < after_id):
                change = EvolutionChangeKind.REMOVED
                left += 1
                selected_before, selected_after = before, None
            elif after is not None and (before is None or after_id < before_id):
                change = EvolutionChangeKind.ADDED
                right += 1
                selected_before, selected_after = None, after
            else:
                if before == after:
                    unchanged += 1
                    left += 1
                    right += 1
                    continue
                change = EvolutionChangeKind.MODIFIED
                left += 1
                right += 1
                selected_before, selected_after = before, after
            total += 1
            if len(selected) >= limit:
                continue
            selected.append(self._node_change(
                base,
                head,
                selected_before,
                selected_after,
                change,
                evidence,
            ))
        return tuple(selected), total, total - len(selected), unchanged

    @staticmethod
    def _node_payloads(prepared: _PreparedSnapshot) -> tuple[KnowledgeNode, ...]:
        return prepared.graph.nodes if prepared.graph is not None else ()

    def _node_change(
        self,
        base: _PreparedSnapshot,
        head: _PreparedSnapshot,
        before_node: KnowledgeNode | None,
        after_node: KnowledgeNode | None,
        change: EvolutionChangeKind,
        evidence: EvidenceIndex,
    ) -> NodeEvolution:
        selected_payload = (
            before_node
            if change is EvolutionChangeKind.REMOVED
            else after_node
        )
        if selected_payload is None:  # pragma: no cover - merge logic supplies it
            raise RuntimeError("canonical node change has no selected projection")
        graph_id = selected_payload.id
        before = self._candidate(base, graph_id) if before_node is not None else None
        after = self._candidate(head, graph_id) if after_node is not None else None
        candidate = after or before
        if candidate is None:  # pragma: no cover - restored graph owns each node
            raise RuntimeError("canonical node has no subject projection")
        before_payload = self._node_projection(before_node)
        after_payload = self._node_projection(after_node)
        before_digest = self._projection_digest(before_payload)
        after_digest = self._projection_digest(after_payload)
        changed_fields = (
            tuple(sorted({*before_payload, *after_payload} - {
                key for key in {*before_payload, *after_payload}
                if before_payload.get(key) == after_payload.get(key)
            }))
            if before_payload is not None and after_payload is not None
            else ()
        )
        evidence_ids = self._change_evidence(
            evidence,
            EvidenceKind.GRAPH_NODE,
            candidate.canonical_id,
            base,
            head,
            before_digest,
            after_digest,
            change,
            before_count=int(before_payload is not None),
            after_count=int(after_payload is not None),
            changed_fields=changed_fields,
        )
        confidence = self._change_confidence(evidence_ids, base, head, evidence)
        limitations = (
            (_ABSENCE_LIMITATION,)
            if change in {EvolutionChangeKind.ADDED, EvolutionChangeKind.REMOVED}
            else (_MODIFICATION_LIMITATION,)
        )
        return NodeEvolution(
            change,
            before,
            after,
            before_digest,
            after_digest,
            changed_fields,
            evidence_ids,
            confidence,
            limitations,
        )

    def _compare_relations(
        self,
        base: _PreparedSnapshot,
        head: _PreparedSnapshot,
        limit: int,
        evidence: EvidenceIndex,
    ) -> tuple[tuple[RelationEvolution, ...], int, int, int]:
        base_groups = iter(self._relation_groups(base.graph))
        head_groups = iter(self._relation_groups(head.graph))
        selected: list[RelationEvolution] = []
        total = unchanged = 0
        before = next(base_groups, None)
        after = next(head_groups, None)
        while before is not None or after is not None:
            before_key = before[0] if before is not None else None
            after_key = after[0] if after is not None else None
            if before is not None and (after is None or before_key < after_key):
                change = EvolutionChangeKind.REMOVED
                selected_before, selected_after = before, None
                before = next(base_groups, None)
            elif after is not None and (before is None or after_key < before_key):
                change = EvolutionChangeKind.ADDED
                selected_before, selected_after = None, after
                after = next(head_groups, None)
            else:
                if before[1] == after[1]:
                    unchanged += 1
                    before = next(base_groups, None)
                    after = next(head_groups, None)
                    continue
                change = EvolutionChangeKind.MODIFIED
                selected_before, selected_after = before, after
                before = next(base_groups, None)
                after = next(head_groups, None)
            total += 1
            if len(selected) >= limit:
                continue
            selected.append(self._relation_change(
                base,
                head,
                selected_before,
                selected_after,
                change,
                evidence,
            ))
        return tuple(selected), total, total - len(selected), unchanged

    @staticmethod
    def _relation_groups(
        graph: KnowledgeGraph | None,
    ):
        if graph is None:
            return

        def key(edge):
            return edge.source, edge.target, edge.relation.value

        for group_key, group in itertools.groupby(graph.edges, key=key):
            evidence: set[str] = set()
            for edge in group:
                evidence.update(edge.evidence)
            yield group_key, tuple(sorted(evidence))

    def _relation_change(
        self,
        base: _PreparedSnapshot,
        head: _PreparedSnapshot,
        before: tuple[tuple[str, str, str], tuple[str, ...]] | None,
        after: tuple[tuple[str, str, str], tuple[str, ...]] | None,
        change: EvolutionChangeKind,
        evidence: EvidenceIndex,
    ) -> RelationEvolution:
        key = (after or before)[0]
        source_id, target_id, raw_relation = key
        selected_snapshot = base if change is EvolutionChangeKind.REMOVED else head
        source = self._candidate(selected_snapshot, source_id)
        target = self._candidate(selected_snapshot, target_id)
        relation = KnowledgeRelation(raw_relation)
        before_refs = before[1] if before is not None else None
        after_refs = after[1] if after is not None else None
        before_digest = self._projection_digest(before_refs)
        after_digest = self._projection_digest(after_refs)
        subject_id = self._relation_subject_id(source, target, relation)
        evidence_ids = self._change_evidence(
            evidence,
            EvidenceKind.GRAPH_EDGE,
            subject_id,
            base,
            head,
            before_digest,
            after_digest,
            change,
            before_count=len(before_refs or ()),
            after_count=len(after_refs or ()),
            extra_refs=(
                f"canonical-subject:{source.canonical_id}",
                f"canonical-subject:{target.canonical_id}",
                f"canonical-relation-kind:{relation.value}",
            ),
        )
        confidence = self._change_confidence(evidence_ids, base, head, evidence)
        limitations = (
            (_ABSENCE_LIMITATION,)
            if change in {EvolutionChangeKind.ADDED, EvolutionChangeKind.REMOVED}
            else (
                "Only the structured evidence projection changed; the canonical relationship remains present.",
            )
        )
        return RelationEvolution(
            change,
            relation,
            source,
            target,
            before_digest,
            after_digest,
            len(before_refs or ()),
            len(after_refs or ()),
            evidence_ids,
            confidence,
            limitations,
        )

    @staticmethod
    def _candidate(prepared: _PreparedSnapshot, graph_id: str) -> SubjectCandidate:
        candidate = prepared.resolver.candidate_for_graph_id(
            graph_id,
            match_basis=SubjectMatchBasis.CANONICAL_ID,
        )
        if candidate is None:
            raise RuntimeError("canonical relationship endpoint is unavailable")
        return candidate

    @staticmethod
    def _projection_digest(value: object | None) -> str | None:
        if value is None:
            return None
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _node_projection(node: KnowledgeNode | None) -> dict[str, object] | None:
        if node is None:
            return None
        return {
            "id": node.id,
            "kind": node.kind.value,
            "name": node.name,
            "symbol_id": str(node.symbol_id) if node.symbol_id is not None else None,
            "metadata": dict(node.metadata),
            "qualified_name": node.qualified_name,
            "project_id": node.project_id,
            "language": node.language,
        }

    @staticmethod
    def _relation_subject_id(
        source: SubjectCandidate,
        target: SubjectCandidate,
        relation: KnowledgeRelation,
    ) -> str:
        digest = hashlib.sha256(json.dumps(
            {
                "relation": relation.value,
                "source": source.canonical_id,
                "target": target.canonical_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")).hexdigest()
        return f"canonical-relation:{digest}"

    @staticmethod
    def _change_evidence(
        evidence: EvidenceIndex,
        kind: EvidenceKind,
        subject_id: str,
        base: _PreparedSnapshot,
        head: _PreparedSnapshot,
        before_digest: str | None,
        after_digest: str | None,
        change: EvolutionChangeKind,
        *,
        before_count: int,
        after_count: int,
        extra_refs: tuple[str, ...] = (),
        changed_fields: tuple[str, ...] | None = None,
    ) -> tuple[str, str]:
        result = []
        for side, prepared, digest, count in (
            ("base", base, before_digest, before_count),
            ("head", head, after_digest, after_count),
        ):
            present = digest is not None
            limitations = (_ABSENCE_LIMITATION,) if not present else ()
            detail = {
                "side": side,
                "change": change.value,
                "presence": "present" if present else "absent",
                "projection_digest": digest or "absent",
                "evidence_count": count,
            }
            if changed_fields is not None:
                detail["changed_fields"] = ",".join(changed_fields) or "none"
            record = EvidenceRecord.create(
                kind,
                subject_id,
                REPOSITORY_EVOLUTION_PRODUCER,
                prepared.snapshot.snapshot_id,
                source_refs=(
                    f"canonical-graph:{prepared.resolver.graph_digest}",
                    f"snapshot:{prepared.snapshot.snapshot_id}",
                    *extra_refs,
                ),
                detail=detail,
                limitations=limitations,
                reliability=1.0,
                specificity=1.0,
            )
            result.append(evidence.add(record))
        return result[0], result[1]

    def _change_confidence(
        self,
        evidence_ids: tuple[str, str],
        base: _PreparedSnapshot,
        head: _PreparedSnapshot,
        evidence: EvidenceIndex,
    ):
        return self._confidence.calculate(
            (
                EvidenceRole(
                    "base_projection",
                    tuple(
                        item for item in evidence_ids
                        if evidence.get(item).snapshot_id == base.snapshot.snapshot_id
                    ),
                ),
                EvidenceRole(
                    "head_projection",
                    tuple(
                        item for item in evidence_ids
                        if evidence.get(item).snapshot_id == head.snapshot.snapshot_id
                    ),
                ),
            ),
            evidence,
        )

    @staticmethod
    def _commit_observation(
        snapshot: AtlasSemanticSnapshot,
        graph_digest: str,
    ) -> _CommitObservation:
        raw = snapshot.semantic_context.get("risk_analysis")
        if not isinstance(raw, Mapping):
            return _CommitObservation(
                None,
                EvolutionState.UNAVAILABLE,
                (),
                ("Compatible PR132 Git-head evidence is absent from this snapshot.",),
            )
        try:
            report = RiskAnalysisReport.from_dict(raw)
        except (KeyError, TypeError, ValueError, OverflowError):
            return _CommitObservation(
                None,
                EvolutionState.INCOMPATIBLE,
                (),
                ("PR132 risk evidence could not be validated for commit association.",),
            )
        if report.producer_version != "atlas-pr132/1" or report.schema_version != 1:
            return _CommitObservation(
                None,
                EvolutionState.INCOMPATIBLE,
                (),
                ("PR132 risk producer or schema is incompatible with commit association.",),
            )
        if graph_digest == "unavailable" or report.graph_digest != graph_digest:
            return _CommitObservation(
                None,
                EvolutionState.INCOMPATIBLE,
                (),
                ("PR132 Git evidence is not bound to this snapshot's canonical graph.",),
            )
        records = {
            record.evidence_id: record for record in report.evidence_index.records
        }
        target_references: dict[
            str, set[tuple[str, RiskMetricKind, str]]
        ] = {}
        for hotspot in report.hotspots:
            for factor in hotspot.factors:
                metric = factor.metric.metric
                if metric not in _PR132_GIT_PRODUCERS:
                    continue
                for evidence_id in factor.metric.evidence_ids:
                    target_references.setdefault(evidence_id, set()).add(
                        ("factor", metric, hotspot.subject_id)
                    )
        capabilities = {
            capability.metric: capability for capability in report.capabilities
        }
        for capability in report.capabilities:
            if capability.metric not in _PR132_GIT_PRODUCERS:
                continue
            for evidence_id in capability.evidence_ids:
                record = records[evidence_id]
                if record.subject_id == f"risk-capability:{capability.metric.value}":
                    target_references.setdefault(evidence_id, set()).add(
                        ("capability", capability.metric, record.subject_id)
                    )
        for heatmap in report.heatmaps:
            if heatmap.metric not in _PR132_GIT_PRODUCERS:
                continue
            for evidence_id in heatmap.evidence_ids:
                target_references.setdefault(evidence_id, set()).add(
                    ("heatmap", heatmap.metric, f"risk-heatmap:{heatmap.metric.value}")
                )
        heads: set[str] = set()
        source_records: set[str] = set()
        capability_records: set[str] = set()
        malformed = False
        for record in report.evidence_index.records:
            contracts = target_references.get(record.evidence_id)
            if not contracts:
                # Risk reports may retain canonical evidence outside the bounded
                # findings/capabilities.  Such records cannot establish a commit
                # association merely by containing a Git-looking source reference.
                continue
            references = tuple(
                reference
                for reference in record.source_refs
                if reference.startswith("git-head:")
            )
            if not references:
                continue
            if record.snapshot_id != report.lineage:
                malformed = True
                continue
            detail = dict(record.detail)
            valid_contracts = {
                contract
                for contract in contracts
                if RepositoryEvolutionService._valid_pr132_git_contract(
                    record,
                    contract,
                    report,
                    capabilities,
                    detail,
                )
            }
            if not valid_contracts:
                malformed = True
                continue
            for reference in record.source_refs:
                if not reference.startswith("git-head:"):
                    continue
                candidate = reference.removeprefix("git-head:")
                if not _GIT_OBJECT.fullmatch(candidate):
                    malformed = True
                    continue
                heads.add(candidate)
                source_records.add(record.evidence_id)
                if any(contract[0] == "capability" for contract in valid_contracts):
                    capability_records.add(record.evidence_id)
        if heads and not capability_records:
            malformed = True
        if malformed or len(heads) > 1:
            return _CommitObservation(
                None,
                EvolutionState.INCOMPATIBLE,
                tuple(sorted(source_records)),
                ("PR132 evidence contains malformed or conflicting Git heads.",),
            )
        if not heads:
            return _CommitObservation(
                None,
                EvolutionState.UNAVAILABLE,
                (),
                ("PR132 analysis contains no Git-head evidence for this snapshot.",),
            )
        return _CommitObservation(
            next(iter(heads)),
            EvolutionState.PARTIAL,
            tuple(sorted(source_records)),
            (_COMMIT_LIMITATION,),
        )

    @staticmethod
    def _valid_pr132_git_contract(
        record: EvidenceRecord,
        contract: tuple[str, RiskMetricKind, str],
        report: RiskAnalysisReport,
        capabilities: Mapping[RiskMetricKind, RiskCapability],
        detail: Mapping[str, str],
    ) -> bool:
        owner, metric, subject_id = contract
        expected_producer = _PR132_GIT_PRODUCERS[metric]
        if detail.get("metric") != metric.value or record.subject_id != subject_id:
            return False
        capability = capabilities.get(metric)
        if capability is None or expected_producer not in capability.producers:
            return False
        if owner == "factor":
            return (
                record.kind is EvidenceKind.SEMANTIC_FACT
                and record.producer == expected_producer
            )
        if owner not in {"capability", "heatmap"}:
            return False
        return (
            record.kind is EvidenceKind.ANALYSIS_RESULT
            and record.producer == report.producer_version
            and detail.get("input_fingerprint")
            == report.lineage.removeprefix("risk-analysis:")
        )

    @staticmethod
    def _commit_capability(
        base: _PreparedSnapshot,
        head: _PreparedSnapshot,
        evidence: EvidenceIndex,
    ) -> EvolutionCapability:
        evidence_ids = []
        for side, prepared in (("base", base), ("head", head)):
            observation = prepared.commit
            if observation.head is None:
                continue
            record = EvidenceRecord.create(
                EvidenceKind.REPOSITORY_METADATA,
                "repository-evolution:commit-association",
                REPOSITORY_EVOLUTION_PRODUCER,
                prepared.snapshot.snapshot_id,
                source_refs=(
                    f"git-head:{observation.head}",
                    *observation.source_refs,
                ),
                detail={
                    "side": side,
                    "association": "analysis-time-head",
                    "graph_digest": prepared.resolver.graph_digest,
                },
                limitations=observation.limitations,
                reliability=REPOSITORY_METADATA_RELIABILITY,
                specificity=0.7,
            )
            evidence_ids.append(evidence.add(record))
        observations = (base.commit, head.commit)
        limitations = tuple(sorted({
            *(item for observation in observations for item in observation.limitations),
        }))
        if any(item.state is EvolutionState.INCOMPATIBLE for item in observations):
            state = EvolutionState.INCOMPATIBLE
        elif base.commit.head is None or head.commit.head is None:
            state = EvolutionState.UNAVAILABLE
        elif base.commit.head == head.commit.head:
            state = EvolutionState.INSUFFICIENT
            limitations = tuple(sorted({
                *limitations,
                "Both snapshots reference the same analysis-time Git head; no distinct commit interval is proven.",
            }))
        else:
            state = EvolutionState.PARTIAL
        return EvolutionCapability(
            EvolutionCapabilityKind.COMMIT_ALIGNMENT,
            state,
            tuple(evidence_ids),
            limitations,
        )

    @staticmethod
    def _capabilities(
        snapshot_evidence: tuple[str, str],
        graph_evidence: tuple[str, ...],
        core_state: EvolutionState,
        core_limitations: tuple[str, ...],
        commit: EvolutionCapability,
    ) -> tuple[EvolutionCapability, ...]:
        graph_limitations = core_limitations
        if core_state is not EvolutionState.AVAILABLE and not graph_limitations:
            graph_limitations = ("Canonical comparison is not fully available.",)
        return (
            EvolutionCapability(
                EvolutionCapabilityKind.SNAPSHOT_PAIR,
                EvolutionState.AVAILABLE,
                snapshot_evidence,
            ),
            EvolutionCapability(
                EvolutionCapabilityKind.CANONICAL_NODES,
                core_state,
                graph_evidence,
                graph_limitations,
            ),
            EvolutionCapability(
                EvolutionCapabilityKind.CANONICAL_RELATIONS,
                core_state,
                graph_evidence,
                graph_limitations,
            ),
            commit,
            EvolutionCapability(
                EvolutionCapabilityKind.RENAME_TRACKING,
                EvolutionState.UNAVAILABLE,
                limitations=(
                    "Stable identity absence and presence do not prove rename or move continuity.",
                ),
            ),
            EvolutionCapability(
                EvolutionCapabilityKind.API_COMPATIBILITY,
                EvolutionState.UNAVAILABLE,
                limitations=(
                    "No authoritative API or ABI before/after producer is available in PR141.",
                ),
            ),
            EvolutionCapability(
                EvolutionCapabilityKind.SECURITY_EVOLUTION,
                EvolutionState.UNAVAILABLE,
                limitations=(
                    "PR138 findings are current-state observations and cannot prove introduced or fixed security issues.",
                ),
            ),
            EvolutionCapability(
                EvolutionCapabilityKind.ARCHITECTURAL_DRIFT,
                EvolutionState.UNAVAILABLE,
                limitations=(
                    "Architectural drift is owned by PR143 and is not inferred from graph deltas.",
                ),
            ),
        )
