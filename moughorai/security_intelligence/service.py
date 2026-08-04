"""Deterministic PR138 orchestration over existing security producer reports."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import replace
import heapq
from typing import TYPE_CHECKING

from moughorai.knowledge_graph import KnowledgeGraph, KnowledgeRelation
from moughorai.measurement import MeasurementSession
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
)
if TYPE_CHECKING:
    from moughorai.semantic_snapshot import AtlasSemanticSnapshot
    from moughorai.subject_resolution import CanonicalSubjectResolver, SubjectCandidate

from .models import (
    SECURITY_INTELLIGENCE_PRODUCER,
    SECURITY_INTELLIGENCE_SNAPSHOT_KEY,
    SecurityCapability,
    SecurityCapabilityState,
    SecurityCategory,
    SecurityIntelligenceFinding,
    SecurityIntelligenceReport,
    SecurityIntelligenceRequest,
    SecurityProducerFinding,
    SecurityProducerReport,
    SecurityScope,
    SecuritySeverity,
    legacy_confidence_rank,
    security_capability_evidence_identity,
    security_evidence_reliability,
    security_finding_sort_key,
    security_intelligence_finding_id,
    security_priority_for_finding,
    security_severity_rank,
    stable_security_digest,
)


_PUBLISHED_FINDING_LIMIT = 10_000
_PRODUCER_REPORT_LIMIT = 10_000
_PRODUCER_REPORT_INPUT_LIMIT = 100_000
_PRODUCER_FINDING_WORK_LIMIT = 100_000
_MERGED_TRACE_LIMIT = 256
_CALL_LIMITATION = (
    "Interprocedural call evidence is unavailable; findings are limited to the "
    "existing producer evidence."
)
_CROSS_MODULE_LIMITATION = (
    "Cross-project and cross-module taint propagation is not performed by PR138."
)
_IMPACT_LIMITATION = (
    "PR136 impact analysis was not supplied; priority does not include blast radius."
)
_EXPOSURE_LIMITATION = (
    "Runtime exposure evidence is unavailable; priority does not infer exploitability."
)
_XSS_LIMITATION = (
    "No existing Atlas producer provides structured XSS findings."
)


class _UnavailableResolver:
    """Minimal unavailable view; avoids importing snapshot-backed resolution."""

    graph = None
    graph_digest = "unavailable"
    limitations = ("Canonical PR129 graph is unavailable.",)


class SecurityIntelligenceService:
    """Integrate authoritative producer findings without scanning source again."""

    def __init__(
        self,
        resolver: CanonicalSubjectResolver | None,
        *,
        snapshot_id: str = "unavailable",
        analyzer_version: str | None = None,
        measurement: MeasurementSession | None = None,
        published_report: SecurityIntelligenceReport | None = None,
        limitations: Iterable[str] = (),
        unavailable_state: SecurityCapabilityState = SecurityCapabilityState.NOT_ANALYZED,
    ) -> None:
        del analyzer_version  # accepted for compatibility with sibling services
        if resolver is None:
            resolver = _UnavailableResolver()
        self._resolver = resolver
        self._snapshot_id = str(snapshot_id).strip() or "unavailable"
        self._measurement = measurement or MeasurementSession()
        self._published_report = published_report
        self._limitations = tuple(sorted({str(item).strip() for item in limitations if str(item).strip()}))
        self._unavailable_state = (
            unavailable_state
            if isinstance(unavailable_state, SecurityCapabilityState)
            else SecurityCapabilityState(unavailable_state)
        )
        with self._measurement.scope(
            "security_intelligence.subject_index",
            consumer="security-intelligence",
            sample_key=self._resolver.graph_digest,
        ) as scope:
            self._path_index, self._suffix_index = self._build_path_indexes()
            graph = self._resolver.graph
            scope.add_units(len(graph.nodes) if graph is not None else 0)
            scope.set_objects_retained(
                sum(len(items) for items in self._path_index.values())
                + sum(len(items) for items in self._suffix_index.values())
            )

    @property
    def resolver(self) -> CanonicalSubjectResolver:
        return self._resolver

    @property
    def published_report(self) -> SecurityIntelligenceReport | None:
        return self._published_report

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AtlasSemanticSnapshot,
        measurement: MeasurementSession | None = None,
    ) -> SecurityIntelligenceService:
        from moughorai.semantic_snapshot import AtlasSemanticSnapshot
        from moughorai.subject_resolution import CanonicalSubjectResolver

        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError("security intelligence snapshot is invalid")
        session = measurement or MeasurementSession()
        with session.scope(
            "security_intelligence.resolver_index",
            consumer="security-intelligence",
            sample_key=snapshot.snapshot_id,
        ) as scope:
            resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
            graph = resolver.graph
            scope.add_units(
                len(graph.nodes) + len(graph.edges) if graph is not None else 0
            )
            scope.set_objects_retained(
                len(graph.nodes) if graph is not None else 0
            )
        if SECURITY_INTELLIGENCE_SNAPSHOT_KEY not in snapshot.semantic_context:
            return cls(
                resolver,
                snapshot_id=snapshot.snapshot_id,
                analyzer_version=snapshot.analyzer_version,
                measurement=session,
                limitations=(
                    "Security intelligence is unavailable in this older or partial snapshot.",
                ),
            )
        raw = snapshot.semantic_context.get(SECURITY_INTELLIGENCE_SNAPSHOT_KEY)
        if not isinstance(raw, Mapping):
            return cls(
                resolver,
                snapshot_id=snapshot.snapshot_id,
                analyzer_version=snapshot.analyzer_version,
                measurement=session,
                limitations=("Security intelligence snapshot data is incompatible.",),
                unavailable_state=SecurityCapabilityState.INCOMPATIBLE,
            )
        try:
            report = SecurityIntelligenceReport.from_dict(raw)
        except (KeyError, TypeError, ValueError, OverflowError):
            return cls(
                resolver,
                snapshot_id=snapshot.snapshot_id,
                analyzer_version=snapshot.analyzer_version,
                measurement=session,
                limitations=("Security intelligence snapshot data is incompatible.",),
                unavailable_state=SecurityCapabilityState.INCOMPATIBLE,
            )
        raw_graph = snapshot.semantic_context.get("semantic_graph")
        try:
            source_graph_digest = KnowledgeGraph.stable_payload_digest(raw_graph)
        except (TypeError, ValueError, OverflowError):
            source_graph_digest = "unavailable"
        if (
            resolver.graph_digest == "unavailable"
            or source_graph_digest == "unavailable"
            or report.graph_digest != source_graph_digest
        ):
            return cls(
                resolver,
                snapshot_id=snapshot.snapshot_id,
                analyzer_version=snapshot.analyzer_version,
                measurement=session,
                limitations=(
                    "Security intelligence graph lineage cannot be verified against "
                    "the canonical snapshot graph.",
                ),
                unavailable_state=SecurityCapabilityState.INCOMPATIBLE,
            )
        canonical_request = SecurityIntelligenceRequest(
            limit=_PUBLISHED_FINDING_LIMIT,
        )
        if (
            report.snapshot_id
            != f"semantic-graph:{source_graph_digest}"
            or report.request != canonical_request
        ):
            return cls(
                resolver,
                snapshot_id=snapshot.snapshot_id,
                analyzer_version=snapshot.analyzer_version,
                measurement=session,
                limitations=(
                    "Security intelligence publication lineage or request scope "
                    "is incompatible with the canonical snapshot graph.",
                ),
                unavailable_state=SecurityCapabilityState.INCOMPATIBLE,
            )
        if not cls._canonical_subjects_match(report, resolver):
            return cls(
                resolver,
                snapshot_id=snapshot.snapshot_id,
                analyzer_version=snapshot.analyzer_version,
                measurement=session,
                limitations=(
                    "Security intelligence canonical subjects cannot be "
                    "revalidated against the snapshot graph.",
                ),
                unavailable_state=SecurityCapabilityState.INCOMPATIBLE,
            )
        return cls(
            resolver,
            snapshot_id=snapshot.snapshot_id,
            analyzer_version=snapshot.analyzer_version,
            measurement=session,
            published_report=report,
        )

    @staticmethod
    def _canonical_subjects_match(
        report: SecurityIntelligenceReport,
        resolver: CanonicalSubjectResolver,
    ) -> bool:
        """Revalidate retained public identities through the indexed PR129 resolver."""

        from moughorai.knowledge_graph import KnowledgeKind
        from moughorai.subject_resolution import ResolutionStatus, SubjectQuery

        identities = tuple(sorted({
            (
                finding.canonical_subject_id,
                finding.canonical_subject_kind,
                finding.canonical_subject_name,
                finding.project_id,
                finding.language,
            )
            for finding in report.findings
            if finding.canonical_subject_id is not None
        }))
        for canonical_id, kind_value, name, project_id, language in identities:
            try:
                kind = KnowledgeKind(kind_value)
                resolution = resolver.resolve(SubjectQuery(
                    canonical_id,
                    kind=kind,
                    project=project_id,
                    language=language,
                ))
            except (TypeError, ValueError):
                return False
            subject = resolution.subject
            if (
                resolution.status is not ResolutionStatus.RESOLVED
                or subject is None
                or subject.canonical_id != canonical_id
                or subject.kind is not kind
                or subject.qualified_name != name
                or subject.language.casefold() != language
            ):
                return False
        return True

    def analyze(
        self,
        request: SecurityIntelligenceRequest,
        producer_reports: Iterable[SecurityProducerReport] = (),
    ) -> SecurityIntelligenceReport:
        if not isinstance(request, SecurityIntelligenceRequest):
            raise TypeError("security intelligence request is invalid")
        reports, omitted_report_count, supplied_report_count = (
            self._bounded_reports(producer_reports, request=request)
        )
        with self._measurement.scope(
            "security_intelligence.query",
            consumer="security-intelligence",
            sample_key=self._resolver.graph_digest,
        ) as scope:
            if supplied_report_count:
                result = self._analyze_reports(
                    request, reports, omitted_report_count,
                )
            elif self._published_report is not None:
                result = self._select_published(request, self._published_report)
            else:
                result = self._unavailable_report(request)
            scope.add_units(result.total_finding_count)
            scope.add_objects_produced(result.total_finding_count)
            scope.set_objects_retained(len(result.findings))
            return result

    @classmethod
    def _bounded_reports(
        cls,
        reports: Iterable[SecurityProducerReport],
        *,
        request: SecurityIntelligenceRequest,
    ) -> tuple[tuple[SecurityProducerReport, ...], int, int]:
        """Validate bounded input and retain the selected deterministic prefix."""

        input_count = 0
        selected_count = 0
        selected_keys: set[tuple[str, str, str, str, str]] = set()

        def entries():
            nonlocal input_count, selected_count
            for report in reports:
                if input_count >= _PRODUCER_REPORT_INPUT_LIMIT:
                    raise ValueError(
                        "security producer report input exceeds the deterministic "
                        f"work bound of {_PRODUCER_REPORT_INPUT_LIMIT} reports"
                    )
                input_count += 1
                if not isinstance(report, SecurityProducerReport):
                    raise TypeError("security producer reports are invalid")
                if not cls._report_selected(report, request):
                    continue
                key = cls._report_sort_key(report)
                if key in selected_keys:
                    continue
                selected_keys.add(key)
                selected_count += 1
                yield key, report

        retained = tuple(
            item[1]
            for item in heapq.nsmallest(
                _PRODUCER_REPORT_LIMIT,
                entries(),
                key=lambda item: item[0],
            )
        )
        return (
            retained,
            max(0, selected_count - len(retained)),
            input_count,
        )

    def build_published_report(
        self,
        producer_reports: Iterable[SecurityProducerReport],
    ) -> SecurityIntelligenceReport:
        """Build the unfiltered snapshot artifact at the documented safe bound."""

        return self.analyze(
            SecurityIntelligenceRequest(limit=_PUBLISHED_FINDING_LIMIT),
            producer_reports,
        )

    def _build_path_indexes(self) -> tuple[
        dict[str, tuple[SubjectCandidate, ...]],
        dict[tuple[str, str, str], tuple[SubjectCandidate, ...]],
    ]:
        graph = self._resolver.graph
        if graph is None:
            return {}, {}
        by_path: dict[str, dict[str, SubjectCandidate]] = defaultdict(dict)
        by_suffix: dict[
            tuple[str, str, str], dict[str, SubjectCandidate]
        ] = defaultdict(dict)
        for node in graph.nodes:
            candidate = self._resolver.candidate_for_graph_id(node.id)
            if candidate is not None and candidate.path is not None:
                by_path[candidate.path][candidate.canonical_id] = candidate
                scopes = set(candidate.project_scopes)
                if candidate.project:
                    scopes.add(candidate.project)
                basename = candidate.path.rsplit("/", 1)[-1]
                for project in scopes:
                    by_suffix[(
                        project,
                        candidate.language.casefold(),
                        basename,
                    )][candidate.canonical_id] = candidate
        exact = {
            path: tuple(sorted(values.values(), key=lambda item: (
                item.kind.value, item.qualified_name, item.project or "",
                item.language, item.canonical_id,
            )))
            for path, values in sorted(by_path.items())
        }
        suffix = {
            key: tuple(sorted(values.values(), key=lambda item: (
                item.path or "", item.kind.value, item.qualified_name,
                item.project or "", item.language, item.canonical_id,
            )))
            for key, values in sorted(by_suffix.items())
        }
        return exact, suffix

    def _candidate(
        self,
        report: SecurityProducerReport,
        finding: SecurityProducerFinding,
    ) -> tuple[SubjectCandidate | None, tuple[str, ...]]:
        basename = finding.location.path.rsplit("/", 1)[-1]
        possible = {
            item.canonical_id: item
            for item in (
                *self._path_index.get(finding.location.path, ()),
                *self._suffix_index.get((
                    report.project_id,
                    report.language.casefold(),
                    basename,
                ), ()),
            )
        }
        candidates = tuple(
            item
            for item in possible.values()
            if item.language.casefold() == report.language.casefold()
            if (
                item.project == report.project_id
                or report.project_id in item.project_scopes
            )
            if item.path == finding.location.path
            or (
                item.path is not None
                and item.path.endswith("/" + finding.location.path)
            )
        )
        unique = {item.canonical_id: item for item in candidates}
        if len(unique) == 1:
            return next(iter(unique.values())), ()
        if not unique:
            return None, (
                "No unique canonical subject matched the exact project, language, and relative path.",
            )
        return None, (
            "The exact project, language, and relative path matched multiple canonical subjects.",
        )

    def _analyze_reports(
        self,
        request: SecurityIntelligenceRequest,
        reports: tuple[SecurityProducerReport, ...],
        omitted_report_count: int = 0,
    ) -> SecurityIntelligenceReport:
        reports = tuple(sorted(reports, key=self._report_sort_key))
        eligible = tuple(item for item in reports if self._report_selected(item, request))
        finding_work = sum(len(item.findings) for item in eligible)
        if finding_work > _PRODUCER_FINDING_WORK_LIMIT:
            raise ValueError(
                "security producer input exceeds the deterministic consolidation "
                f"bound of {_PRODUCER_FINDING_WORK_LIMIT} findings"
            )
        selected_categories = request.categories or tuple(SecurityCategory)
        raw_groups: dict[
            tuple[str, str, SecurityCategory, str, str, int, int],
            list[tuple[SecurityProducerReport, SecurityProducerFinding]],
        ] = defaultdict(list)
        for report in eligible:
            for finding in report.findings:
                if finding.category not in selected_categories:
                    continue
                if request.severities and finding.severity not in request.severities:
                    continue
                key = (
                    report.project_id, report.language, finding.category,
                    finding.rule_id,
                    finding.location.path, finding.location.line, finding.location.column,
                )
                raw_groups[key].append((report, finding))

        coverage_by_category = {
            category: self._coverage_counts(category, eligible, request)
            for category in selected_categories
        }
        evidence = EvidenceIndex()
        findings = []
        for key in sorted(raw_groups, key=lambda item: (
            item[2].value, item[0].casefold(), item[0], item[1],
            item[4], item[5], item[6], item[3],
        )):
            merged = self._merge_group(
                key,
                tuple(raw_groups[key]),
                evidence,
                coverage_by_category[key[2]],
            )
            if request.scope is SecurityScope.SYMBOL and (
                merged.canonical_subject_id not in request.canonical_subject_ids
            ):
                continue
            findings.append(merged)
        findings.sort(key=security_finding_sort_key)
        total = len(findings)
        selected = tuple(findings[:request.limit])
        capabilities = self._capabilities(
            request,
            eligible,
            selected_categories,
            tuple(findings),
            omitted_report_count,
        )
        limitations = self._report_limitations(
            eligible, capabilities, omitted_report_count,
        )
        fingerprint = stable_security_digest({
            "request": request.to_dict(),
            "reports": [item.to_dict() for item in reports],
            "graph_digest": self._resolver.graph_digest,
            "snapshot_id": self._snapshot_id,
            "omitted_report_count": omitted_report_count,
        })
        report_refs = tuple(
            stable_security_digest(report.to_dict()) for report in eligible
        )
        capabilities = tuple(
            self._capability_with_evidence(
                capability,
                request,
                evidence,
                lineage_input={
                    "category": capability.category.value,
                    "report_refs": report_refs,
                    "omitted_report_count": omitted_report_count,
                },
                report_limitations=limitations,
                report_fingerprint=fingerprint,
                graph_digest=self._resolver.graph_digest,
            )
            for capability in capabilities
        )
        selected_evidence = self._evidence_subset(
            evidence,
            selected,
            capabilities,
        )
        omitted = total - len(selected)
        return SecurityIntelligenceReport(
            request, selected, capabilities, selected_evidence, fingerprint,
            self._resolver.graph_digest, self._snapshot_id, total, omitted,
            omitted > 0, limitations,
        )

    @staticmethod
    def _report_sort_key(
        item: SecurityProducerReport,
    ) -> tuple[str, str, str, str, str]:
        return (
            item.project_id.casefold(), item.project_id, item.language,
            item.producer_version, stable_security_digest(item.to_dict()),
        )

    @staticmethod
    def _report_selected(
        report: SecurityProducerReport,
        request: SecurityIntelligenceRequest,
    ) -> bool:
        if request.projects and report.project_id not in request.projects:
            return False
        if request.languages and report.language.casefold() not in request.languages:
            return False
        return True

    def _merge_group(
        self,
        key: tuple[str, str, SecurityCategory, str, str, int, int],
        entries: tuple[tuple[SecurityProducerReport, SecurityProducerFinding], ...],
        evidence: EvidenceIndex,
        coverage: tuple[int, int],
    ) -> SecurityIntelligenceFinding:
        project_id, language, category, rule_id, path, line, column = key
        ordered = tuple(sorted(entries, key=lambda item: (
            item[0].producer_version, item[0].language,
            item[1].legacy_fingerprint, item[1].severity.value,
        )))
        candidate, candidate_limitations = self._candidate(*ordered[0])
        coverage_observed, coverage_eligible = coverage
        all_trace_locations = tuple(sorted({
            location
            for _, item in ordered
            for location in item.trace_locations
        }))
        trace_locations = all_trace_locations[:_MERGED_TRACE_LIMIT]
        omitted_trace_count = len(all_trace_locations) - len(trace_locations)
        trace_ref = stable_security_digest(
            [location.to_dict() for location in trace_locations]
        )
        legacy_values = {item.legacy_confidence for _, item in ordered}
        producer_limitation_count = sum(
            len(report.limitations) for report, _ in ordered
        )
        finding_limitations = set(candidate_limitations)
        if producer_limitation_count:
            finding_limitations.add(
                f"{producer_limitation_count} source-free producer limitation(s) "
                "apply; producer prose is excluded from merged findings."
            )
        if omitted_trace_count:
            finding_limitations.add(
                f"Merged producer traces exceeded the {_MERGED_TRACE_LIMIT}-"
                f"location bound; omitted {omitted_trace_count} location(s)."
            )
        if len({item.severity for _, item in ordered}) > 1:
            finding_limitations.add(
                "Merged producer findings disagree on severity; the highest "
                "supplied severity is retained."
            )
        if len(legacy_values) > 1:
            finding_limitations.add(
                "Merged producer findings use different legacy confidence labels; "
                "each producer retains its structured evidence reliability."
            )
        normalized_finding_limitations = tuple(sorted(finding_limitations))
        finding_limitations_ref = stable_security_digest(
            list(normalized_finding_limitations)
        )
        evidence_ids = []
        for report, finding in ordered:
            location_ref = stable_security_digest(finding.location.to_dict())
            record = EvidenceRecord.create(
                EvidenceKind.ANALYSIS_RESULT,
                candidate.canonical_id if candidate is not None else f"project:{stable_security_digest(project_id)}",
                report.producer_version,
                self._snapshot_id,
                source_refs=(f"security-finding:{stable_security_digest(finding.to_dict())}",),
                scope="project",
                language=report.language,
                detail={
                    "category": category.value,
                    "rule_id": rule_id,
                    "project_id_ref": stable_security_digest(project_id),
                    "location_ref": location_ref,
                    "trace_location_count": len(trace_locations),
                    "merged_trace_ref": trace_ref,
                    "finding_limitations_ref": finding_limitations_ref,
                    "severity": finding.severity.value,
                    "legacy_confidence": finding.legacy_confidence.value,
                    "legacy_fingerprint": finding.legacy_fingerprint,
                    "cwe": finding.cwe,
                    "owasp": finding.owasp,
                    "coverage_observed": coverage_observed,
                    "coverage_eligible": coverage_eligible,
                },
                limitations=candidate_limitations,
                reliability=security_evidence_reliability(
                    finding.legacy_confidence
                ),
                specificity=1.0 if candidate is not None else 0.8,
            )
            evidence_ids.append(evidence.add(record))
        canonical_evidence_id = None
        if candidate is not None:
            canonical = EvidenceRecord.create(
                EvidenceKind.GRAPH_NODE,
                candidate.canonical_id,
                "atlas-pr129/1",
                self._snapshot_id,
                source_refs=(f"semantic_graph.node_ref:{stable_security_digest(candidate.canonical_id)}",),
                scope="project",
                language=candidate.language.casefold(),
                detail={
                    "match": "exact_project_language_relative_path",
                    "subject_kind": candidate.kind.value,
                    "subject_name_ref": stable_security_digest(
                        candidate.qualified_name
                    ),
                },
                reliability=1.0,
                specificity=1.0,
            )
            canonical_evidence_id = evidence.add(canonical)
            evidence_ids.append(canonical_evidence_id)

        producer_evidence_ids = tuple(sorted(set(
            evidence_ids[:len(ordered)]
        )))
        evidence_severities = tuple(
            SecuritySeverity(dict(record.detail)["severity"])
            for evidence_id in producer_evidence_ids
            if (record := evidence.get(evidence_id)) is not None
        )
        severity_counts = {
            severity: sum(
                1 for value in evidence_severities if value is severity
            )
            for severity in set(evidence_severities)
        }
        agreement = round(
            max(severity_counts.values()) / len(evidence_severities), 4
        )
        confidence = ConfidenceCalculator().calculate(
            (
                EvidenceRole("producer_finding", producer_evidence_ids, True),
                EvidenceRole("canonical_subject", (canonical_evidence_id,) if canonical_evidence_id else (), False),
            ),
            evidence,
            coverage=round(coverage_observed / coverage_eligible, 4),
            agreement=agreement,
        )
        severity = max(
            (item.severity for _, item in ordered), key=security_severity_rank
        )
        legacy_confidence = max(
            (item.legacy_confidence for _, item in ordered),
            key=legacy_confidence_rank,
        )
        priority = security_priority_for_finding(
            severity,
            producer_evidence_ids,
            trace_locations,
            canonical_evidence_id,
        )
        producer_versions = tuple(sorted({
            report.producer_version for report, _ in ordered
        }))
        finding_id = security_intelligence_finding_id(
            project_id=project_id,
            language=language,
            category=category,
            rule_id=rule_id,
            location=ordered[0][1].location,
            producer_versions=producer_versions,
            snapshot_id=self._snapshot_id,
            canonical_subject_id=(
                candidate.canonical_id if candidate is not None else None
            ),
            evidence_ids=evidence_ids,
        )
        return SecurityIntelligenceFinding(
            finding_id, category, rule_id,
            tuple(sorted({item.legacy_fingerprint for _, item in ordered})),
            severity, legacy_confidence,
            tuple(sorted({item.cwe for _, item in ordered})),
            tuple(sorted({item.owasp for _, item in ordered})),
            project_id, language, ordered[0][1].location,
            trace_locations,
            candidate.canonical_id if candidate is not None else None,
            candidate.kind.value if candidate is not None else None,
            candidate.qualified_name if candidate is not None else None,
            producer_versions,
            confidence, priority, tuple(evidence_ids),
            normalized_finding_limitations,
        )

    @staticmethod
    def _coverage_counts(
        category: SecurityCategory,
        reports: tuple[SecurityProducerReport, ...],
        request: SecurityIntelligenceRequest,
    ) -> tuple[int, int]:
        analyzed = tuple(
            report for report in reports
            if category in report.analyzed_categories
        )
        if request.projects and request.languages:
            eligible_scopes = {
                (project, language)
                for project in request.projects
                for language in request.languages
            }
            observed_scopes = {
                (report.project_id, report.language)
                for report in analyzed
                if (report.project_id, report.language) in eligible_scopes
            }
        elif request.projects:
            eligible_scopes = set(request.projects)
            observed_scopes = {
                report.project_id for report in analyzed
                if report.project_id in eligible_scopes
            }
        elif request.languages:
            eligible_scopes = set(request.languages)
            observed_scopes = {
                report.language for report in analyzed
                if report.language in eligible_scopes
            }
        else:
            return len(analyzed), len(reports)
        return len(observed_scopes), len(eligible_scopes)

    def _capability_with_evidence(
        self,
        capability: SecurityCapability,
        request: SecurityIntelligenceRequest,
        evidence: EvidenceIndex,
        *,
        lineage_input: object,
        snapshot_id: str | None = None,
        report_limitations: tuple[str, ...] = (),
        report_fingerprint: str,
        graph_digest: str,
    ) -> SecurityCapability:
        """Attach one replayable aggregate record to a capability conclusion."""

        provisional = replace(capability, evidence_ids=())
        subject_id, detail = security_capability_evidence_identity(
            provisional,
            request,
            report_limitations,
            report_fingerprint,
            graph_digest,
        )
        record = EvidenceRecord.create(
            EvidenceKind.ANALYSIS_RESULT,
            subject_id,
            SECURITY_INTELLIGENCE_PRODUCER,
            snapshot_id or self._snapshot_id,
            source_refs=(
                "security-capability-input:"
                + stable_security_digest(lineage_input),
            ),
            scope=request.scope.value,
            language="unknown",
            detail=detail,
            reliability=1.0,
            specificity=1.0,
        )
        return replace(provisional, evidence_ids=(evidence.add(record),))

    def _capabilities(
        self,
        request: SecurityIntelligenceRequest,
        eligible: tuple[SecurityProducerReport, ...],
        categories: tuple[SecurityCategory, ...],
        findings: tuple[SecurityIntelligenceFinding, ...],
        omitted_report_count: int = 0,
    ) -> tuple[SecurityCapability, ...]:
        result = []
        for category in categories:
            analyzed = tuple(item for item in eligible if category in item.analyzed_categories)
            category_findings = tuple(item for item in findings if item.category is category)
            if not eligible or not analyzed:
                limitations = {_XSS_LIMITATION} if category is SecurityCategory.XSS else {
                    "No compatible producer report analyzed this category in the requested scope."
                }
                state = SecurityCapabilityState.NOT_ANALYZED
                if omitted_report_count:
                    state = SecurityCapabilityState.PARTIAL
                    limitations.add(
                        f"{omitted_report_count} producer report(s) were omitted; "
                        "category execution cannot be determined exactly."
                    )
                if request.languages and any(language != "java" for language in request.languages):
                    limitations.add("Existing built-in security producers are Java-only.")
                capability = SecurityCapability(
                    category, state,
                    finding_count=len(category_findings), limitations=tuple(limitations),
                )
                result.append(capability)
                continue
            observed, known = self._coverage_counts(category, eligible, request)
            state = (
                SecurityCapabilityState.ANALYZED
                if observed == known
                else SecurityCapabilityState.PARTIAL
            )
            producer_limitation_count = sum(
                len(report.limitations) for report in analyzed
            )
            limitations: set[str] = set()
            if producer_limitation_count:
                limitations.add(
                    f"{producer_limitation_count} source-free producer "
                    "limitation(s) apply; producer prose is excluded from "
                    "capability summaries."
                )
            if state is SecurityCapabilityState.PARTIAL:
                limitations.add("Only part of the requested project and language scope analyzed this category.")
            numerator = sum(item.source_files for item in analyzed)
            coverage: float | None = round(observed / known, 4)
            if request.projects:
                covered_projects = {
                    item.project_id for item in analyzed
                    if item.project_id in request.projects
                }
                missing_projects = set(request.projects).difference(
                    covered_projects
                )
                if missing_projects:
                    state = SecurityCapabilityState.PARTIAL
                    limitations.add(
                        f"No compatible producer report covered {len(missing_projects)} "
                        "requested project(s) for this category."
                    )
            if request.languages:
                covered_languages = {
                    item.language for item in analyzed
                    if item.language in request.languages
                }
                missing_languages = set(request.languages).difference(
                    covered_languages
                )
                if missing_languages:
                    state = SecurityCapabilityState.PARTIAL
                    limitations.add(
                        f"No compatible producer report covered {len(missing_languages)} "
                        "requested language(s) for this category."
                    )
            warning_count = sum(item.warning_count for item in analyzed)
            if warning_count:
                state = SecurityCapabilityState.PARTIAL
                coverage = None
                limitations.add(
                    f"Contributing producer reports contained {warning_count} warning(s)."
                )
            if producer_limitation_count:
                state = SecurityCapabilityState.PARTIAL
                coverage = None
            if coverage is not None and coverage < 1.0:
                state = SecurityCapabilityState.PARTIAL
                limitations.add("Producer coverage is incomplete for the requested scope.")
            if request.scope is SecurityScope.SYMBOL:
                state = SecurityCapabilityState.PARTIAL
                coverage = None
                limitations.add(
                    "Producer coverage cannot be established exactly for the "
                    "requested canonical symbol scope."
                )
            if limitations:
                state = SecurityCapabilityState.PARTIAL
            if omitted_report_count:
                state = SecurityCapabilityState.PARTIAL
                coverage = None
                limitations.add(
                    f"{omitted_report_count} producer report(s) were omitted at "
                    "the deterministic repository bound."
                )
            capability = SecurityCapability(
                category, state,
                tuple(sorted({item.language for item in analyzed})),
                tuple(sorted({item.project_id for item in analyzed})),
                numerator, len(category_findings), coverage,
                tuple(sorted({item.producer_version for item in analyzed})),
                tuple(limitations),
            )
            result.append(capability)
        return tuple(result)

    def _report_limitations(
        self,
        reports: tuple[SecurityProducerReport, ...],
        capabilities: tuple[SecurityCapability, ...],
        omitted_report_count: int = 0,
    ) -> tuple[str, ...]:
        limitations = set(self._limitations)
        limitations.update(self._resolver.limitations)
        limitations.update({_CROSS_MODULE_LIMITATION, _IMPACT_LIMITATION, _EXPOSURE_LIMITATION})
        graph = self._resolver.graph
        has_calls = bool(graph is not None and any(
            edge.relation is KnowledgeRelation.CALLS and edge.evidence
            for edge in graph.edges
        ))
        if not has_calls:
            limitations.add(_CALL_LIMITATION)
        if any(report.warning_count for report in reports):
            limitations.add(
                f"Producer reports contained {sum(report.warning_count for report in reports)} warning(s); warning prose is intentionally excluded."
            )
        if any(item.category is SecurityCategory.XSS and item.state is not SecurityCapabilityState.ANALYZED for item in capabilities):
            limitations.add(_XSS_LIMITATION)
        if any(report.language != "java" for report in reports):
            limitations.add("Non-Java coverage is limited to explicitly supplied compatible producer reports.")
        if omitted_report_count:
            limitations.add(
                f"Omitted {omitted_report_count} producer report(s) at the "
                "deterministic repository bound."
            )
        return tuple(sorted(limitations))

    @staticmethod
    def _evidence_subset(
        evidence: EvidenceIndex,
        findings: tuple[SecurityIntelligenceFinding, ...],
        capabilities: tuple[SecurityCapability, ...] = (),
    ) -> EvidenceIndex:
        ids = {evidence_id for item in findings for evidence_id in item.evidence_ids}
        ids.update(
            evidence_id
            for capability in capabilities
            for evidence_id in capability.evidence_ids
        )
        ids.update(
            evidence_id
            for item in findings
            for component in item.priority.components
            for evidence_id in component.evidence_ids
        )
        return EvidenceIndex(
            tuple(record for evidence_id in sorted(ids) if (record := evidence.get(evidence_id)) is not None),
            frozen=True,
        )

    def _select_published(
        self,
        request: SecurityIntelligenceRequest,
        report: SecurityIntelligenceReport,
    ) -> SecurityIntelligenceReport:
        projection_evidence = EvidenceIndex()
        candidates = tuple(
            item for item in report.findings
            if not request.projects or item.project_id in request.projects
            if not request.languages or item.language in request.languages
            if not request.categories or item.category in request.categories
            if not request.severities or item.severity in request.severities
            if request.scope is not SecurityScope.SYMBOL
            or item.canonical_subject_id in request.canonical_subject_ids
        )
        selected = candidates[:request.limit]
        selected_categories = request.categories or tuple(SecurityCategory)
        exact_published_counts = not (
            request.projects
            or request.languages
            or request.severities
            or request.scope is SecurityScope.SYMBOL
        )
        aggregate_scope_is_inexact = bool(
            request.projects
            or request.languages
            or request.scope is SecurityScope.SYMBOL
        )
        combined_project_language_scope = bool(
            request.projects and request.languages
        )
        capabilities_list = []
        capability_lineage: dict[SecurityCategory, object] = {}
        for item in report.capabilities:
            if item.category not in selected_categories:
                continue
            state = item.state
            limitations = set(item.limitations)
            source_files = item.source_files
            coverage = item.coverage
            selected_projects = tuple(
                value for value in item.project_ids
                if not request.projects or value in request.projects
            )
            selected_languages = tuple(
                value for value in item.languages
                if not request.languages or value in request.languages
            )
            scope_has_no_producer = (
                (bool(request.projects) and not selected_projects)
                or (bool(request.languages) and not selected_languages)
            )
            retained_category_findings = sum(
                1 for finding in candidates
                if finding.category is item.category
            )
            category_findings = tuple(
                finding for finding in candidates
                if finding.category is item.category
            )
            selected_producers = item.producer_versions
            if aggregate_scope_is_inexact:
                source_files = 0
                coverage = None
                if category_findings:
                    selected_projects = tuple(sorted({
                        finding.project_id for finding in category_findings
                    }))
                    selected_languages = tuple(sorted({
                        finding.language for finding in category_findings
                    }))
                    selected_producers = tuple(sorted({
                        producer
                        for finding in category_findings
                        for producer in finding.producer_versions
                    }))
                    scope_has_no_producer = False
                elif request.scope is SecurityScope.SYMBOL:
                    selected_projects = ()
                    selected_languages = ()
                    selected_producers = ()
                if scope_has_no_producer:
                    if state is not SecurityCapabilityState.INCOMPATIBLE:
                        state = SecurityCapabilityState.NOT_ANALYZED
                    limitations.add(
                        "No compatible published producer report covered the "
                        "requested project and language scope."
                    )
                elif state is SecurityCapabilityState.ANALYZED:
                    state = SecurityCapabilityState.PARTIAL
                limitations.add(
                    "Published aggregate source-file coverage cannot be recalculated "
                    "exactly for the requested project, language, or symbol scope."
                )
            if combined_project_language_scope:
                if retained_category_findings:
                    if state is not SecurityCapabilityState.INCOMPATIBLE:
                        state = SecurityCapabilityState.PARTIAL
                else:
                    if state is not SecurityCapabilityState.INCOMPATIBLE:
                        state = SecurityCapabilityState.NOT_ANALYZED
                    selected_projects = ()
                    selected_languages = ()
                    selected_producers = ()
                source_files = 0
                coverage = None
                limitations.add(
                    "The published aggregate does not retain project-language "
                    "producer pairing; combined-scope coverage is unavailable."
                )
            projected_capability = replace(
                item,
                state=state,
                finding_count=(
                    item.finding_count
                    if exact_published_counts
                    else retained_category_findings
                ),
                project_ids=selected_projects,
                languages=selected_languages,
                source_files=source_files,
                coverage=coverage,
                producer_versions=(
                    () if scope_has_no_producer else selected_producers
                ),
                limitations=tuple(limitations),
                evidence_ids=(),
            )
            capabilities_list.append(projected_capability)
            capability_lineage[item.category] = {
                "published_report": report.input_fingerprint,
                "previous_capability_evidence": list(item.evidence_ids),
            }
        capabilities = tuple(capabilities_list)
        present_categories = {item.category for item in capabilities}
        for category in selected_categories:
            if category in present_categories:
                continue
            missing = SecurityCapability(
                category, SecurityCapabilityState.NOT_ANALYZED,
                limitations=("This category is unavailable in the published security report.",),
            )
            capabilities += (missing,)
            capability_lineage[category] = {
                "published_report": report.input_fingerprint,
                "missing_category": category.value,
            }
        finding_evidence = self._evidence_subset(
            report.evidence_index,
            selected,
        )
        for record in finding_evidence.records:
            projection_evidence.add(record)
        known_total = (
            sum(item.finding_count for item in capabilities)
            if exact_published_counts else len(candidates)
        )
        omitted = known_total - len(selected)
        limitations = set(report.limitations)
        limitations.update(self._limitations)
        limitations.update(self._resolver.limitations)
        if report.truncated and not exact_published_counts:
            limitations.add(
                "The published security report was already truncated; filtered "
                "counts cover retained findings only."
            )
        report_limitations = tuple(sorted(limitations))
        fingerprint = stable_security_digest({
            "published": report.input_fingerprint,
            "request": request.to_dict(),
        })
        capabilities = tuple(
            self._capability_with_evidence(
                capability,
                request,
                projection_evidence,
                lineage_input=capability_lineage[capability.category],
                snapshot_id=report.snapshot_id,
                report_limitations=report_limitations,
                report_fingerprint=fingerprint,
                graph_digest=report.graph_digest,
            )
            for capability in capabilities
        )
        evidence = projection_evidence.freeze()
        return SecurityIntelligenceReport(
            request, selected, capabilities, evidence, fingerprint,
            report.graph_digest, report.snapshot_id, known_total, omitted,
            omitted > 0, report_limitations,
        )

    def _unavailable_report(
        self,
        request: SecurityIntelligenceRequest,
    ) -> SecurityIntelligenceReport:
        categories = request.categories or tuple(SecurityCategory)
        default_limitation = (
            "Security intelligence snapshot data is incompatible."
            if self._unavailable_state is SecurityCapabilityState.INCOMPATIBLE
            else "No security producer report is available in the requested scope."
        )
        limitations = tuple(sorted(set(self._limitations))) or (
            default_limitation,
        )
        fingerprint = stable_security_digest({
            "request": request.to_dict(),
            "state": self._unavailable_state.value,
        })
        evidence = EvidenceIndex()
        capabilities_list = []
        for category in categories:
            capability = SecurityCapability(
                category,
                self._unavailable_state,
                limitations=tuple(sorted({
                    *(
                        limitations
                        if (
                            category is not SecurityCategory.XSS
                            or self._unavailable_state
                            is SecurityCapabilityState.INCOMPATIBLE
                        )
                        else ()
                    ),
                    *((_XSS_LIMITATION,) if category is SecurityCategory.XSS else ()),
                })),
            )
            capabilities_list.append(self._capability_with_evidence(
                capability,
                request,
                evidence,
                lineage_input={
                    "state": self._unavailable_state.value,
                    "category": category.value,
                    "limitations": list(capability.limitations),
                },
                report_limitations=limitations,
                report_fingerprint=fingerprint,
                graph_digest=self._resolver.graph_digest,
            ))
        capabilities = tuple(capabilities_list)
        return SecurityIntelligenceReport(
            request, (), capabilities, evidence.freeze(),
            fingerprint,
            self._resolver.graph_digest, self._snapshot_id, 0, limitations=limitations,
        )


__all__ = ["SecurityIntelligenceService"]
