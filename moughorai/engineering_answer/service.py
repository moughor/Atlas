"""Deterministic synthesis over authoritative PR159 Java code impact."""

from __future__ import annotations

from dataclasses import dataclass

from moughorai.code_intelligence import (
    CodeIntelligenceConfiguration,
    CodePathConfidence,
    JavaCodeIntelligenceReport,
    JavaCodeIntelligenceService,
)
from moughorai.measurement import MeasurementSession
from moughorai.semantic_snapshot import AtlasSemanticSnapshot

from .models import (
    EngineeringAnswer,
    EngineeringAnswerItem,
    EngineeringAnswerSection,
    EngineeringAnswerSubject,
    EngineeringAnswerSynthesis,
    EngineeringAnswerTraceability,
    EngineeringInspectItem,
    EngineeringTraversalSummary,
)


_UNCERTAINTY_CATEGORIES = (
    "unresolved_sites",
    "external_sites",
    "unsupported_sites",
    "ambiguous_candidates",
    "possible_dispatch_candidates",
    "method_references",
)


@dataclass(frozen=True, slots=True)
class EngineeringAnswerConfiguration:
    max_depth: int = 8
    max_nodes: int = 4_096
    max_representatives_per_section: int = 8
    max_limitation_representatives: int = 3
    max_candidates_per_call_site: int = 3
    max_resolution_candidates: int = 12
    max_inspect_items: int = 12

    def __post_init__(self) -> None:
        for name in (
            "max_depth",
            "max_nodes",
            "max_representatives_per_section",
            "max_limitation_representatives",
            "max_candidates_per_call_site",
            "max_resolution_candidates",
            "max_inspect_items",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


class EngineeringAnswerService:
    """Build concise answers without adding evidence or traversing a new graph."""

    def __init__(
        self,
        code_intelligence: JavaCodeIntelligenceService,
        *,
        measurement: MeasurementSession | None = None,
    ) -> None:
        if not isinstance(code_intelligence, JavaCodeIntelligenceService):
            raise TypeError("engineering answers require Java code intelligence")
        self.code_intelligence = code_intelligence
        self.measurement = measurement or MeasurementSession()

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AtlasSemanticSnapshot,
        *,
        measurement: MeasurementSession | None = None,
    ) -> EngineeringAnswerService:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError("engineering answers require a semantic snapshot")
        return cls(
            JavaCodeIntelligenceService.from_snapshot(snapshot),
            measurement=measurement,
        )

    def query(
        self,
        subject: str,
        *,
        kind: str | None = None,
        project: str | None = None,
        configuration: EngineeringAnswerConfiguration | None = None,
    ) -> EngineeringAnswerSynthesis:
        selected = configuration or EngineeringAnswerConfiguration()
        result = self.code_intelligence.query(
            subject,
            kind=kind,
            project=project,
            configuration=CodeIntelligenceConfiguration(
                max_depth=selected.max_depth,
                max_nodes=selected.max_nodes,
                max_direct_relationships=(
                    selected.max_representatives_per_section
                ),
                max_paths_per_section=(
                    selected.max_representatives_per_section
                ),
                max_limitation_representatives=(
                    selected.max_limitation_representatives
                ),
                max_resolution_candidates=selected.max_resolution_candidates,
                max_candidates_per_call_site=(
                    selected.max_candidates_per_call_site
                ),
            ),
        )
        resolution = result.resolution
        if result.report is None:
            return EngineeringAnswerSynthesis(
                resolution.query,
                resolution.status.value,
                result.snapshot_id,
                candidates=tuple(
                    _answer_subject(item) for item in resolution.candidates
                ),
                total_candidate_count=resolution.total_candidate_count,
                omitted_candidate_count=resolution.omitted_candidate_count,
                limitations=tuple(sorted({
                    *result.limitations,
                    *resolution.limitations,
                })),
            )
        answer = self.synthesize(
            result.report,
            max_inspect_items=selected.max_inspect_items,
        )
        return EngineeringAnswerSynthesis(
            resolution.query,
            resolution.status.value,
            result.snapshot_id,
            answer=answer,
            limitations=result.limitations,
        )

    def synthesize(
        self,
        report: JavaCodeIntelligenceReport,
        *,
        max_inspect_items: int = 12,
    ) -> EngineeringAnswer:
        if not isinstance(report, JavaCodeIntelligenceReport):
            raise TypeError("engineering synthesis requires a PR159 report")
        if (
            isinstance(max_inspect_items, bool)
            or not isinstance(max_inspect_items, int)
            or max_inspect_items < 1
        ):
            raise ValueError("max_inspect_items must be positive")
        with self.measurement.scope(
            "engineering_answer.synthesis",
            consumer="engineering-answer",
            sample_key=report.input_fingerprint,
        ) as scope:
            answer = _synthesize(report, max_inspect_items=max_inspect_items)
            scope.add_units(sum((
                report.direct_callers_high_confidence.total_count,
                report.direct_caller_conservative_groups.call_site_count,
                report.upstream_direct.total_count,
                report.upstream_transitive.total_count,
                report.direct_callees_high_confidence.total_count,
                report.direct_callee_conservative_groups.call_site_count,
                report.direct_test_callers.total_count,
                report.high_confidence_test_paths.total_count,
                report.possible_test_paths.total_count,
            )))
            scope.add_objects_produced(1)
            scope.set_objects_retained(1)
            return answer


def _answer_subject(subject) -> EngineeringAnswerSubject:
    return EngineeringAnswerSubject(
        subject.canonical_id,
        subject.normalized_key,
        subject.kind.value,
        subject.project,
        subject.source_classification.value,
        subject.source.compact,
    )


def _relationship_item(item, category: str, canonical_reference: str):
    return EngineeringAnswerItem(
        canonical_reference,
        category,
        item.confidence.value,
        item.location.compact,
        (item.producer_evidence_id,),
        item.canonical_source,
        item.canonical_target,
        item.edge_kind.value,
    )


def _relationship_section(section_id: str, section, *, reference: str):
    return EngineeringAnswerSection(
        section_id,
        section.total_count,
        tuple(
            _relationship_item(item, section_id, getattr(item, reference))
            for item in section.items
        ),
    )


def _group_section(section_id: str, section):
    return EngineeringAnswerSection(
        section_id,
        section.call_site_count,
        tuple(
            EngineeringAnswerItem(
                item.canonical_source,
                section_id,
                item.confidence.value,
                item.location.compact,
                (item.producer_evidence_id,),
                item.canonical_source,
                relationship_kind=(
                    ",".join(kind.value for kind in item.edge_kinds)
                ),
                total_candidate_count=item.total_candidate_count,
                candidate_target_ids=item.included_candidate_ids,
            )
            for item in section.items
        ),
        section.candidate_projection_count,
    )


def _path_section(section_id: str, section):
    return EngineeringAnswerSection(
        section_id,
        section.total_count,
        tuple(
            EngineeringAnswerItem(
                item.consumer_subject_id,
                section_id,
                item.confidence.value,
                (
                    item.steps[0].location.compact
                    if item.steps else item.subject_id
                ),
                item.producer_evidence_ids,
                item.consumer_subject_id,
                item.subject_id,
                relationship_kind=item.traversal_direction.value,
                depth=item.depth,
            )
            for item in section.items
        ),
    )


def _uncertainty_sections(report) -> tuple[EngineeringAnswerSection, ...]:
    by_category = {item.category: item for item in report.limitations}
    ordered = (*_UNCERTAINTY_CATEGORIES, *sorted(
        set(by_category) - set(_UNCERTAINTY_CATEGORIES)
    ))
    sections = []
    for category in ordered:
        summary = by_category.get(category)
        if summary is None:
            sections.append(EngineeringAnswerSection(category, 0))
            continue
        sections.append(EngineeringAnswerSection(
            category,
            summary.total_count,
            tuple(
                EngineeringAnswerItem(
                    item.caller_subject_id,
                    category,
                    "limitation_evidence",
                    item.location.compact,
                    (item.producer_evidence_id,),
                    canonical_source=item.caller_subject_id,
                    relationship_kind=item.invocation_kind,
                )
                for item in summary.representatives
            ),
        ))
    sections.append(EngineeringAnswerSection(
        "traversal_truncation",
        1 if report.traversal.truncated else 0,
    ))
    return tuple(sections)


def _inspect_first(
    caller_high: EngineeringAnswerSection,
    direct_tests: EngineeringAnswerSection,
    upstream_direct: EngineeringAnswerSection,
    upstream_transitive: EngineeringAnswerSection,
    conservative_callers: EngineeringAnswerSection,
    conservative_callees: EngineeringAnswerSection,
    uncertainty: tuple[EngineeringAnswerSection, ...],
    maximum: int,
) -> tuple[EngineeringInspectItem, ...]:
    prioritized: list[tuple[str, EngineeringAnswerItem]] = []
    prioritized.extend(
        ("Direct high-confidence represented caller", item)
        for item in caller_high.items
    )
    prioritized.extend(
        ("Direct represented TEST caller", item)
        for item in direct_tests.items
    )
    prioritized.extend(
        ("High-confidence represented upstream path", item)
        for item in (*upstream_direct.items, *upstream_transitive.items)
        if item.confidence
        == CodePathConfidence.HIGH_CONFIDENCE_REPRESENTED_PATH.value
    )
    prioritized.extend(
        (
            "Conservative represented caller site; candidate targets remain unproven",
            item,
        )
        for item in conservative_callers.items
    )
    prioritized.extend(
        (
            'Conservative represented dependency call site; candidate targets remain unproven',
            item,
        )
        for item in conservative_callees.items
    )
    for section in uncertainty:
        if section.section_id not in {"unresolved_sites", "unsupported_sites"}:
            continue
        prioritized.extend(
            (f"{section.section_id} hotspot limits call certainty", item)
            for item in section.items
        )
    return tuple(
        EngineeringInspectItem(
            priority,
            reason,
            item.canonical_reference,
            item.source_ref,
            item.evidence_ids,
        )
        for priority, (reason, item) in enumerate(
            prioritized[:maximum], start=1,
        )
    )


def _synthesize(
    report: JavaCodeIntelligenceReport,
    *,
    max_inspect_items: int,
) -> EngineeringAnswer:
    caller_high = _relationship_section(
        "direct_callers_high_confidence",
        report.direct_callers_high_confidence,
        reference="canonical_source",
    )
    caller_groups = _group_section(
        "direct_caller_conservative_sites",
        report.direct_caller_conservative_groups,
    )
    caller_references = _relationship_section(
        "direct_caller_method_references",
        report.direct_caller_method_references,
        reference="canonical_source",
    )
    upstream_direct = _path_section("upstream_direct", report.upstream_direct)
    upstream_transitive = _path_section(
        "upstream_transitive", report.upstream_transitive,
    )
    callee_high = _relationship_section(
        "direct_callees_high_confidence",
        report.direct_callees_high_confidence,
        reference="canonical_target",
    )
    callee_groups = _group_section(
        "direct_callee_conservative_sites",
        report.direct_callee_conservative_groups,
    )
    callee_references = _relationship_section(
        "direct_callee_method_references",
        report.direct_callee_method_references,
        reference="canonical_target",
    )
    direct_tests = _relationship_section(
        "direct_test_callers",
        report.direct_test_callers,
        reference="canonical_source",
    )
    high_tests = _path_section(
        "high_confidence_test_paths", report.high_confidence_test_paths,
    )
    possible_tests = _path_section(
        "possible_test_paths", report.possible_test_paths,
    )
    uncertainty = _uncertainty_sections(report)
    traversal = EngineeringTraversalSummary(
        report.traversal.traversal_direction.value,
        report.traversal.configured_max_depth,
        report.traversal.configured_max_nodes,
        report.traversal.visited_node_count,
        report.traversal.visited_edge_count,
        report.traversal.depth_histogram,
        report.traversal.truncated,
    )
    direct = upstream_direct.total_count
    transitive = upstream_transitive.total_count
    summary = [
        f"Changing this {report.subject.kind.value} may affect {direct} direct "
        f"represented upstream consumer(s) and {transitive} transitive "
        "represented upstream consumer(s).",
        "This is represented source evidence, not a complete runtime blast radius.",
    ]
    if traversal.truncated:
        summary.insert(
            1,
            f"At least {direct + transitive} represented upstream consumer(s) "
            "were found before the configured traversal bound.",
        )
    inspect = _inspect_first(
        caller_high,
        direct_tests,
        upstream_direct,
        upstream_transitive,
        caller_groups,
        callee_groups,
        uncertainty,
        max_inspect_items,
    )
    trace = report.traceability
    return EngineeringAnswer(
        _answer_subject(report.subject),
        tuple(summary),
        caller_high,
        caller_groups,
        caller_references,
        upstream_direct,
        upstream_transitive,
        callee_high,
        callee_groups,
        callee_references,
        direct_tests,
        high_tests,
        possible_tests,
        uncertainty,
        traversal,
        inspect,
        report.general_limitations,
        EngineeringAnswerTraceability(
            trace.snapshot_id,
            report.input_fingerprint,
            trace.callable_index_fingerprint,
            trace.code_graph_fingerprint,
            trace.test_evidence_fingerprint,
            trace.reachability_fingerprint,
        ),
    )
