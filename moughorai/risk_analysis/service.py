from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, OrderedDict, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import heapq
import json
import math
from pathlib import PurePosixPath
from threading import RLock

from moughorai.ai_git_context import GitHistoryWindow
from moughorai.knowledge_graph import (
    KnowledgeDegreeSummary,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.project_inventory.classifier import (
    GENERATED_DIRECTORY_NAMES,
    is_test_source_path,
)
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
    REPOSITORY_METADATA_RELIABILITY,
    REPRODUCIBLE_HEURISTIC_RELIABILITY,
    RESOLVED_SEMANTIC_FACT_RELIABILITY,
    STRUCTURED_ANALYZER_RELIABILITY,
)

from .models import (
    RiskAnalysisReport,
    RiskAvailability,
    RiskCapability,
    RiskConfiguration,
    RiskFactor,
    RiskHeatmap,
    RiskHeatmapBin,
    RiskHeatmapCohort,
    RiskHotspot,
    RiskMetric,
    RiskMetricInput,
    RiskMetricKind,
    RiskScope,
    RiskTrend,
)


@dataclass(frozen=True, slots=True)
class _Subject:
    node: KnowledgeNode
    display_name: str
    project: str
    language: str
    scope: RiskScope
    cohort: str


@dataclass(frozen=True, slots=True)
class _MetricSeed:
    subject_id: str
    metric: RiskMetricKind
    value: float
    unit: str
    window: str
    producer: str
    coverage: float
    status: RiskAvailability
    evidence_kind: EvidenceKind
    source_refs: tuple[str, ...]
    detail: tuple[tuple[str, str], ...]
    limitations: tuple[str, ...]
    reliability: float
    specificity: float


@dataclass(frozen=True, slots=True)
class _NormalizedSeed:
    seed: _MetricSeed
    normalized: float
    normalization: str
    cohort: str


@dataclass(frozen=True, slots=True)
class _ScoredSubject:
    subject: _Subject
    score: float
    factors: tuple[_NormalizedSeed, ...]
    missing: tuple[RiskMetricKind, ...]


class RiskAnalysisService:
    """Evidence-backed PR132 risk ranking over the canonical PR129 graph."""

    PRODUCER_VERSION = "atlas-pr132/1"
    SCHEMA_VERSION = 1
    _OUTPUT_PRECISION = 6
    _HEATMAP_COHORT_LIMIT = 50
    _CAPABILITY_PRODUCER_LIMIT = 32
    _AGGREGATE_SOURCE_REF_LIMIT = 32
    _FAILED_PROJECT_LIMIT = 20
    _SYMBOL_DEGREE_SPECIFICITY = 0.6
    _PROJECT_DEGREE_SPECIFICITY = 0.8
    _SIZE_SPECIFICITY = 1.0
    _CHANGE_FREQUENCY_SPECIFICITY = 1.0
    _OWNERSHIP_PROXY_SPECIFICITY = 0.7
    _HEATMAP_LABELS = (
        "0.00-0.20",
        "0.20-0.40",
        "0.40-0.60",
        "0.60-0.80",
        "0.80-1.00",
    )
    _SYMBOL_KINDS = frozenset({
        KnowledgeKind.SYMBOL,
        KnowledgeKind.PACKAGE,
        KnowledgeKind.TYPE,
        KnowledgeKind.METHOD,
        KnowledgeKind.FIELD,
    })
    _SYMBOL_RELATIONS = frozenset({
        KnowledgeRelation.IMPORTS,
        KnowledgeRelation.INHERITS,
        KnowledgeRelation.COMPOSES,
        KnowledgeRelation.CALLS,
        KnowledgeRelation.OVERRIDES,
    })
    _PROJECT_RELATIONS = frozenset({KnowledgeRelation.DEPENDS_ON})
    _PROJECT_NEIGHBORS = frozenset({
        KnowledgeKind.PROJECT,
        KnowledgeKind.DEPENDENCY,
        KnowledgeKind.FRAMEWORK,
    })
    _METRIC_SPECIFICATIONS: Mapping[
        RiskMetricKind, tuple[str, tuple[tuple[float, float], ...]]
    ] = {
        RiskMetricKind.COMPLEXITY: (
            "cyclomatic_complexity",
            ((1.0, 0.0), (5.0, 0.25), (10.0, 0.5), (20.0, 0.75),
             (math.inf, 1.0)),
        ),
        RiskMetricKind.FAN_IN: (
            "distinct_neighbors",
            ((0.0, 0.0), (1.0, 0.25), (3.0, 0.5), (7.0, 0.75),
             (math.inf, 1.0)),
        ),
        RiskMetricKind.FAN_OUT: (
            "distinct_neighbors",
            ((0.0, 0.0), (1.0, 0.25), (3.0, 0.5), (7.0, 0.75),
             (math.inf, 1.0)),
        ),
        RiskMetricKind.CHANGE_FREQUENCY: (
            "commits",
            ((0.0, 0.0), (1.0, 0.25), (3.0, 0.5), (7.0, 0.75),
             (math.inf, 1.0)),
        ),
        RiskMetricKind.OWNERSHIP_CONCENTRATION: (
            "ratio",
            ((0.25, 0.0), (0.50, 0.25), (0.75, 0.5), (0.90, 0.75),
             (math.inf, 1.0)),
        ),
        RiskMetricKind.LOW_TEST_DENSITY: (
            "risk_ratio",
            ((0.10, 0.0), (0.25, 0.25), (0.50, 0.5), (0.75, 0.75),
             (math.inf, 1.0)),
        ),
        RiskMetricKind.SIZE: (
            "bytes",
            ((100_000.0, 0.0), (1_000_000.0, 0.25),
             (10_000_000.0, 0.5), (100_000_000.0, 0.75),
             (math.inf, 1.0)),
        ),
    }

    def __init__(
        self,
        configuration: RiskConfiguration | None = None,
        *,
        cache_size: int = 4,
    ) -> None:
        if cache_size <= 0:
            raise ValueError("risk cache size must be positive")
        self.configuration = configuration or RiskConfiguration()
        self._weights = dict(self.configuration.weights)
        self._confidence = ConfidenceCalculator()
        self._cache_size = cache_size
        self._cache: OrderedDict[str, RiskAnalysisReport] = OrderedDict()
        self._cache_lock = RLock()

    def analyze(
        self,
        graph: KnowledgeGraph,
        *,
        repository_summary: Mapping[str, object] | None = None,
        symbol_metadata: Sequence[Mapping[str, object]] = (),
        git_history: GitHistoryWindow | None = None,
        metric_inputs: Sequence[RiskMetricInput] = (),
        previous_report: RiskAnalysisReport | None = None,
        failed_projects: Sequence[str] = (),
    ) -> RiskAnalysisReport:
        summary = repository_summary or {}
        if (
            git_history is not None
            and git_history.commit_limit != self.configuration.git_commit_limit
        ):
            raise ValueError(
                "Git history commit limit does not match RiskConfiguration"
            )
        graph_digest = graph.stable_digest()
        relevant_subject_ids = self._relevant_subject_ids(graph, metric_inputs)
        metadata = self._metadata(symbol_metadata, relevant_subject_ids)
        configuration_fingerprint = self._digest(self.configuration.to_dict())
        fingerprint = self._fingerprint(
            graph_digest,
            summary,
            metadata,
            git_history,
            metric_inputs,
            previous_report,
            failed_projects,
            configuration_fingerprint,
        )
        with self._cache_lock:
            cached = self._cache.get(fingerprint)
            if cached is not None:
                self._cache.move_to_end(fingerprint)
                return cached

        lineage = f"risk-analysis:{fingerprint}"
        subjects = self._subjects(
            graph, summary, metadata, relevant_subject_ids
        )
        seeds: dict[tuple[str, RiskMetricKind], _MetricSeed] = {}
        self._degree_seeds(graph, graph_digest, subjects, seeds)
        self._size_seeds(summary, subjects, seeds)
        git_limitations = self._git_seeds(git_history, summary, subjects, seeds)
        self._external_seeds(metric_inputs, subjects, seeds)
        normalized, normalization_limitations = self._normalize(seeds, subjects)
        selected = tuple(heapq.nsmallest(
            self.configuration.top_k,
            self._score(subjects, normalized),
            key=lambda item: (-item.score, item.subject.node.id),
        ))

        evidence = EvidenceIndex()
        hotspots = self._materialize_hotspots(
            selected,
            evidence,
            lineage,
            previous_report,
        )
        capabilities = self._capabilities(
            seeds,
            normalized,
            subjects,
            hotspots,
            evidence,
            lineage,
        )
        heatmaps = self._heatmaps(
            normalized,
            subjects,
            capabilities,
            evidence,
            lineage,
        )
        scope_counts = Counter(subject.scope.value for subject in subjects.values())
        excluded_scope_counts = Counter(
            subject.scope.value
            for subject in subjects.values()
            if not self._included(subject.scope)
        )
        limitations = {
            "Risk scores are deterministic risk indicators, not bug or defect findings.",
            "Missing metrics are excluded from the score and reduce confidence; they are never treated as zero.",
            "PR129 ownership relationships describe structural containment, not contributor ownership.",
            "Canonical call relationships are not populated by the normal production pipeline.",
            "Complexity and resolved symbol-to-test density remain unavailable without structured producers.",
            "Symbol scope may use conventional source-root paths when explicit source classification metadata is absent.",
            *git_limitations,
            *normalization_limitations,
        }
        if failed_projects:
            unique_failed_projects = sorted(set(map(str, failed_projects)))
            selected_failed_projects = unique_failed_projects[
                : self._FAILED_PROJECT_LIMIT
            ]
            omitted_failed_projects = (
                len(unique_failed_projects) - len(selected_failed_projects)
            )
            omitted_suffix = (
                f"; {omitted_failed_projects} additional failed project(s) omitted"
                if omitted_failed_projects
                else ""
            )
            limitations.add(
                "Risk evidence is partial because these projects failed: "
                + ", ".join(selected_failed_projects)
                + omitted_suffix
            )
        report = RiskAnalysisReport(
            hotspots,
            capabilities,
            heatmaps,
            evidence,
            fingerprint,
            graph_digest,
            configuration_fingerprint,
            lineage,
            self.configuration,
            len({seed.subject_id for seed in seeds.values()}),
            sum(self._included(subject.scope) for subject in subjects.values()),
            tuple(scope_counts.items()),
            tuple(excluded_scope_counts.items()),
            tuple(limitations),
            self.PRODUCER_VERSION,
            self.SCHEMA_VERSION,
        )
        with self._cache_lock:
            existing = self._cache.get(fingerprint)
            if existing is not None:
                self._cache.move_to_end(fingerprint)
                return existing
            self._cache[fingerprint] = report
            self._cache.move_to_end(fingerprint)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return report

    def _degree_seeds(
        self,
        graph: KnowledgeGraph,
        graph_digest: str,
        subjects: Mapping[str, _Subject],
        result: dict[tuple[str, RiskMetricKind], _MetricSeed],
    ) -> None:
        symbol_summaries = graph.degree_summaries(
            relations=self._SYMBOL_RELATIONS,
            subject_kinds=self._SYMBOL_KINDS,
            neighbor_kinds=self._SYMBOL_KINDS,
            subject_ids=subjects,
            include_zero=False,
        )
        project_summaries = graph.degree_summaries(
            relations=self._PROJECT_RELATIONS,
            subject_kinds=(KnowledgeKind.PROJECT,),
            neighbor_kinds=self._PROJECT_NEIGHBORS,
            subject_ids=subjects,
            include_zero=False,
        )
        self._degree_group(
            symbol_summaries,
            graph_digest,
            subjects,
            result,
            project=False,
        )
        self._degree_group(
            project_summaries,
            graph_digest,
            subjects,
            result,
            project=True,
        )

    def _degree_group(
        self,
        summaries: Sequence[KnowledgeDegreeSummary],
        graph_digest: str,
        subjects: Mapping[str, _Subject],
        result: dict[tuple[str, RiskMetricKind], _MetricSeed],
        *,
        project: bool,
    ) -> None:
        base_limitations = [
            "Only positive, traceable canonical relationships are measured; absent relationships remain unknown rather than zero.",
        ]
        if not project:
            base_limitations.append(
                "Call fan-in and fan-out remain unavailable unless a canonical call relationship is actually present for the subject."
            )
        if project:
            base_limitations.append(
                "Project fan-out counts declared project, dependency, and framework relationships; it is not call fan-out."
            )
        for summary in summaries:
            subject = subjects.get(summary.node_id)
            if subject is None:
                continue
            for metric, value in (
                (RiskMetricKind.FAN_IN, summary.incoming),
                (RiskMetricKind.FAN_OUT, summary.outgoing),
            ):
                if value <= 0:
                    continue
                incoming = metric is RiskMetricKind.FAN_IN
                applicable = tuple(
                    item for item in summary.relations
                    if (item.incoming if incoming else item.outgoing) > 0
                )
                breakdown = ",".join(
                    f"{item.relation.value}:"
                    f"{item.incoming if incoming else item.outgoing}"
                    for item in applicable
                )
                detail = (
                    ("graph_digest", graph_digest),
                    ("direction", "incoming" if incoming else "outgoing"),
                    ("positive_relation_degrees", breakdown),
                )
                self._add_seed(result, _MetricSeed(
                    summary.node_id,
                    metric,
                    float(value),
                    "distinct_neighbors",
                    "current-semantic-graph",
                    "knowledge-graph.v1",
                    1.0,
                    RiskAvailability.PARTIAL,
                    EvidenceKind.ANALYSIS_RESULT,
                    (summary.node_id, f"knowledge-graph:{graph_digest}"),
                    detail,
                    tuple(base_limitations),
                    RESOLVED_SEMANTIC_FACT_RELIABILITY,
                    (
                        self._PROJECT_DEGREE_SPECIFICITY
                        if project
                        else self._SYMBOL_DEGREE_SPECIFICITY
                    ),
                ))

    def _size_seeds(
        self,
        summary: Mapping[str, object],
        subjects: Mapping[str, _Subject],
        result: dict[tuple[str, RiskMetricKind], _MetricSeed],
    ) -> None:
        project_subjects = {
            subject.node.name: subject
            for subject in subjects.values()
            if subject.node.kind is KnowledgeKind.PROJECT
        }
        for item in self._projects(summary):
            name = str(item.get("name", ""))
            subject = project_subjects.get(name)
            if subject is None:
                continue
            has_structured_bytes = "inventoried_file_bytes" in item
            raw = item.get("inventoried_file_bytes", item.get("size"))
            value = self._finite_non_negative(raw)
            if value is None:
                continue
            error_count = self._integer(
                item.get("inventoried_file_size_error_count")
            )
            complete_structured_observation = (
                has_structured_bytes and error_count == 0
            )
            structured_completeness_unknown = (
                has_structured_bytes and error_count is None
            )
            unavailable = has_structured_bytes and not complete_structured_observation
            path = str(item.get("path", "."))
            self._add_seed(result, _MetricSeed(
                subject.node.id,
                RiskMetricKind.SIZE,
                value,
                "bytes",
                "current-workspace-inventory",
                "repository-summary.v1",
                0.0 if unavailable else 1.0,
                (
                    RiskAvailability.AVAILABLE
                    if complete_structured_observation
                    else RiskAvailability.UNAVAILABLE
                    if unavailable
                    else RiskAvailability.PARTIAL
                ),
                EvidenceKind.REPOSITORY_METADATA,
                (subject.node.id, f"repository-summary.project:{name}:{path}"),
                (
                    ("inventoried_file_bytes", str(int(value))),
                    ("inventoried_file_count", str(item.get("inventoried_file_count", item.get("files", "unknown")))),
                    (
                        "inventoried_file_size_error_count",
                        "unknown" if error_count is None else str(error_count),
                    ),
                ),
                (
                    "Size is project inventory bytes, not lines of code or symbol size.",
                    *(
                        (
                            "Size is unavailable because one or more inventoried file sizes could not be read; missing bytes were not treated as zero risk.",
                        )
                        if error_count is not None and error_count > 0
                        else (
                            "Size is unavailable because this snapshot predates file-size completeness metadata.",
                        )
                        if structured_completeness_unknown
                        else (
                            "Legacy repository-summary 'size' was used because inventoried_file_bytes was absent.",
                        )
                        if not has_structured_bytes
                        else ()
                    ),
                ),
                (
                    REPOSITORY_METADATA_RELIABILITY
                    if has_structured_bytes
                    else REPRODUCIBLE_HEURISTIC_RELIABILITY
                ),
                self._SIZE_SPECIFICITY,
            ))

    def _git_seeds(
        self,
        history: GitHistoryWindow | None,
        summary: Mapping[str, object],
        subjects: Mapping[str, _Subject],
        result: dict[tuple[str, RiskMetricKind], _MetricSeed],
    ) -> tuple[str, ...]:
        if history is None:
            return ("Git change frequency and contributor concentration are unavailable for this analysis.",)
        if history.commits_scanned == 0:
            return ("Git history contains no commits in the configured window.",)
        project_subjects = {
            subject.node.name: subject
            for subject in subjects.values()
            if subject.node.kind is KnowledgeKind.PROJECT
        }
        projects_by_path: dict[str, set[str]] = defaultdict(set)
        for item in self._projects(summary):
            name = str(item.get("name", ""))
            if name not in project_subjects:
                continue
            path = self._normalize_project_path(str(item.get("path", ".")))
            projects_by_path[path].add(name)
        project_path_index = {
            path: tuple(sorted(names))
            for path, names in projects_by_path.items()
        }

        project_commits: dict[str, dict[str, str]] = defaultdict(dict)
        line_changes: Counter[str] = Counter()
        binary_changes: Counter[str] = Counter()
        ambiguous = 0
        unmapped = 0
        for change in history.changes:
            matches = self._projects_for_history_path(
                change.path,
                project_path_index,
            )
            if not matches:
                unmapped += 1
                continue
            if len(matches) != 1:
                ambiguous += 1
                continue
            project = matches[0]
            project_commits[project][change.commit] = change.contributor_id
            if change.additions is None or change.deletions is None:
                binary_changes[project] += 1
            else:
                line_changes[project] += change.additions + change.deletions

        parsed = len(history.changes)
        mapped = max(0, parsed - ambiguous - unmapped)
        denominator = parsed + history.ignored_records
        coverage = mapped / denominator if denominator else 1.0
        limitations = []
        if history.limit_reached:
            limitations.append(
                "Git evidence is intentionally bounded to the configured commit window; older history is excluded."
            )
        if history.shallow:
            limitations.append(
                "The Git repository is shallow, so history before the clone boundary is unavailable."
            )
        limitations.extend((
            "Merge commits are excluded from the Git history window to avoid ambiguous combined diffs.",
            "Git changes are mapped by discovered project path; project include/exclude globs are not reapplied.",
        ))
        status = (
            RiskAvailability.AVAILABLE
            if coverage == 1.0 and not ambiguous and not history.shallow
            else RiskAvailability.PARTIAL
        )
        if history.ignored_records:
            limitations.append(f"{history.ignored_records} Git history records could not be parsed.")
        if ambiguous:
            limitations.append(f"{ambiguous} Git path changes matched multiple projects and were excluded.")
        if unmapped:
            limitations.append(f"{unmapped} Git path changes did not map to a discovered project.")
        window = (
            f"last-up-to-{history.commit_limit}-repository-commits"
            f"@{history.head[:12]}"
        )
        history_digest = self._digest(history.to_dict())
        if denominator and coverage == 0.0:
            limitations.append(
                "No Git path change mapped reliably to a discovered project; Git metrics remain unavailable."
            )
            return tuple(limitations)
        metric_limitations = tuple(limitations)
        report_limitations = list(limitations)
        for name, subject in sorted(project_subjects.items()):
            commits = project_commits.get(name, {})
            commit_count = len(commits)
            refs = (
                subject.node.id,
                f"git-head:{history.head}",
                f"git-window:{history.commits_scanned}:{history.commit_limit}",
                f"git-history:{history_digest}",
            )
            detail = (
                ("commits_touching_project", str(commit_count)),
                ("contributors", str(len(set(commits.values())))),
                ("parsed_path_changes", str(parsed)),
                ("text_line_changes", str(line_changes[name])),
                ("binary_path_changes", str(binary_changes[name])),
            )
            self._add_seed(result, _MetricSeed(
                subject.node.id,
                RiskMetricKind.CHANGE_FREQUENCY,
                float(commit_count),
                "commits",
                window,
                "git-context.history.v1",
                coverage,
                status,
                EvidenceKind.SEMANTIC_FACT,
                refs,
                detail,
                metric_limitations,
                STRUCTURED_ANALYZER_RELIABILITY,
                self._CHANGE_FREQUENCY_SPECIFICITY,
            ))
            if not commits:
                continue
            contributor_counts = Counter(commits.values())
            unknown_contributors = contributor_counts.pop("", 0)
            if unknown_contributors:
                report_limitations.append(
                    f"Contributor concentration is unavailable for {name}: "
                    f"{unknown_contributors} touching commits lack a contributor identity."
                )
                continue
            top_contributor_commits = max(contributor_counts.values())
            concentration = top_contributor_commits / commit_count
            ownership_detail = tuple((*detail, (
                "measurement", "change_author_concentration_proxy"
            ), (
                "top_contributor_commit_count", str(top_contributor_commits)
            )))
            self._add_seed(result, _MetricSeed(
                subject.node.id,
                RiskMetricKind.OWNERSHIP_CONCENTRATION,
                concentration,
                "ratio",
                window,
                "git-context.change-author-concentration.v1",
                coverage,
                status,
                EvidenceKind.SEMANTIC_FACT,
                refs,
                ownership_detail,
                tuple((
                    *metric_limitations,
                    "This is a bounded change-author concentration proxy, not blame ownership, CODEOWNERS, bus factor, or developer performance.",
                    "Contributor identifiers are pseudonymous hashes kept out of PR132 output and are not ranked.",
                )),
                STRUCTURED_ANALYZER_RELIABILITY,
                self._OWNERSHIP_PROXY_SPECIFICITY,
            ))
        return tuple(report_limitations)

    @staticmethod
    def _projects_for_history_path(
        path: str,
        projects_by_path: Mapping[str, tuple[str, ...]],
    ) -> tuple[str, ...]:
        """Return projects at the deepest matching workspace-relative path."""

        parts = PurePosixPath(path).parts
        for depth in range(len(parts), 0, -1):
            candidate = PurePosixPath(*parts[:depth]).as_posix()
            matches = projects_by_path.get(candidate, ())
            if matches:
                return matches
        return projects_by_path.get(".", ())

    def _external_seeds(
        self,
        values: Sequence[RiskMetricInput],
        subjects: Mapping[str, _Subject],
        result: dict[tuple[str, RiskMetricKind], _MetricSeed],
    ) -> None:
        for item in sorted(values, key=lambda value: (
            value.subject_id, value.metric.value, value.producer, value.unit,
        )):
            if item.subject_id not in subjects:
                raise ValueError(f"risk metric subject is not in the canonical graph: {item.subject_id}")
            expected_unit = self._METRIC_SPECIFICATIONS[item.metric][0]
            if item.unit != expected_unit:
                raise ValueError(
                    f"unsupported unit for {item.metric.value}: {item.unit!r}; "
                    f"expected {expected_unit!r}"
                )
            if item.metric in {
                RiskMetricKind.OWNERSHIP_CONCENTRATION,
                RiskMetricKind.LOW_TEST_DENSITY,
            } and item.value > 1.0:
                raise ValueError(f"{item.metric.value} must be a ratio between 0 and 1")
            status = (
                RiskAvailability.AVAILABLE
                if item.coverage == 1.0
                else RiskAvailability.PARTIAL
                if item.coverage > 0.0
                else RiskAvailability.UNAVAILABLE
            )
            reliability = sum(
                record.reliability for record in item.evidence_records
            ) / len(item.evidence_records)
            specificity = sum(
                record.specificity for record in item.evidence_records
            ) / len(item.evidence_records)
            upstream_limitation_count = sum(
                len(record.limitations) for record in item.evidence_records
            ) + len(item.limitations)
            evidence_limitations = (
                (
                    "The structured producer reported one or more limitations; "
                    "inspect the referenced upstream evidence IDs."
                ),
            ) if upstream_limitation_count else ()
            upstream_ids = tuple(
                record.evidence_id for record in item.evidence_records
            )
            self._add_seed(result, _MetricSeed(
                item.subject_id,
                item.metric,
                item.value,
                item.unit,
                item.window,
                item.producer,
                item.coverage,
                status,
                EvidenceKind.ANALYSIS_RESULT,
                upstream_ids,
                (
                    ("raw_value", str(item.value)),
                    ("unit", item.unit),
                    ("upstream_evidence_ids", ",".join(upstream_ids)),
                    ("upstream_limitation_count", str(upstream_limitation_count)),
                ),
                evidence_limitations,
                reliability,
                specificity,
            ))

    @staticmethod
    def _add_seed(
        result: dict[tuple[str, RiskMetricKind], _MetricSeed],
        seed: _MetricSeed,
    ) -> None:
        key = (seed.subject_id, seed.metric)
        existing = result.get(key)
        if existing is not None and existing != seed:
            raise ValueError(
                f"conflicting risk metric producers for {seed.subject_id}:{seed.metric.value}"
            )
        result[key] = seed

    def _normalize(
        self,
        seeds: Mapping[tuple[str, RiskMetricKind], _MetricSeed],
        subjects: Mapping[str, _Subject],
    ) -> tuple[dict[tuple[str, RiskMetricKind], _NormalizedSeed], tuple[str, ...]]:
        groups: dict[
            tuple[RiskMetricKind, str, str, str, str], list[_MetricSeed]
        ] = defaultdict(list)
        for seed in seeds.values():
            if seed.status is RiskAvailability.UNAVAILABLE or seed.coverage == 0.0:
                continue
            subject = subjects[seed.subject_id]
            groups[(
                seed.metric,
                subject.cohort,
                seed.unit,
                seed.producer,
                seed.window,
            )].append(seed)
        result: dict[tuple[str, RiskMetricKind], _NormalizedSeed] = {}
        limitation_counts: Counter[tuple[RiskMetricKind, str]] = Counter()
        for (metric, cohort, unit, producer, window), values in sorted(
            groups.items(), key=lambda item: (
                item[0][0].value, item[0][1], item[0][2], item[0][3], item[0][4]
            )
        ):
            ordered = sorted(values, key=lambda item: (item.value, item.subject_id))
            raw_values = [item.value for item in ordered]
            normalization_cohort = (
                f"{cohort}|producer={producer}|window={window}|unit={unit}"
            )
            if (
                len(ordered) >= self.configuration.percentile_cohort_minimum
                and raw_values[0] != raw_values[-1]
            ):
                for seed in ordered:
                    lower = bisect_left(raw_values, seed.value)
                    upper = bisect_right(raw_values, seed.value)
                    average_rank = lower + (upper - lower - 1) / 2
                    normalized = average_rank / (len(ordered) - 1)
                    result[(seed.subject_id, metric)] = _NormalizedSeed(
                        seed,
                        normalized,
                        f"deterministic-midrank-percentile:n={len(ordered)}",
                        normalization_cohort,
                    )
                continue
            expected_unit, bands = self._METRIC_SPECIFICATIONS[metric]
            if unit != expected_unit:
                limitation_counts[(metric, "unsupported-unit")] += 1
                continue
            if len(ordered) < self.configuration.percentile_cohort_minimum:
                limitation_counts[(metric, "small-cohort")] += 1
                basis = "small-cohort"
            else:
                limitation_counts[(metric, "no-variance")] += 1
                basis = "no-variance"
            for seed in ordered:
                normalized = next(score for upper, score in bands if seed.value <= upper)
                result[(seed.subject_id, metric)] = _NormalizedSeed(
                    seed,
                    normalized,
                    f"absolute-bands-{basis}:{self.configuration.normalization_version}",
                    normalization_cohort,
                )
        limitations = []
        for (metric, reason), count in sorted(
            limitation_counts.items(),
            key=lambda item: (item[0][0].value, item[0][1]),
        ):
            if reason == "small-cohort":
                limitations.append(
                    f"{count} {metric.value} cohort(s) had fewer than "
                    f"{self.configuration.percentile_cohort_minimum} subjects; "
                    "documented absolute bands were used."
                )
            elif reason == "no-variance":
                limitations.append(
                    f"{count} {metric.value} cohort(s) had no variance; documented "
                    "absolute bands replaced a fabricated percentile spread."
                )
            else:
                limitations.append(
                    f"{count} {metric.value} cohort(s) used an unsupported unit and "
                    "were excluded from normalization."
                )
        return result, tuple(limitations)

    def _score(
        self,
        subjects: Mapping[str, _Subject],
        values: Mapping[tuple[str, RiskMetricKind], _NormalizedSeed],
    ) -> Iterator[_ScoredSubject]:
        by_subject: dict[str, list[_NormalizedSeed]] = defaultdict(list)
        for (subject_id, _), item in values.items():
            by_subject[subject_id].append(item)
        active_metrics = {
            metric for metric, weight in self.configuration.weights if weight > 0
        }
        for subject_id, factors in by_subject.items():
            subject = subjects[subject_id]
            if not self._included(subject.scope):
                continue
            ordered = tuple(sorted(
                (
                    item for item in factors
                    if self._weights[item.seed.metric] > 0
                ),
                key=lambda item: item.seed.metric.value,
            ))
            weight_total = sum(
                self._weights[item.seed.metric] for item in ordered
            )
            if weight_total <= 0:
                continue
            score = sum(
                self._weights[item.seed.metric] * item.normalized
                for item in ordered
            ) / weight_total
            present = {item.seed.metric for item in ordered}
            yield _ScoredSubject(
                subject,
                score,
                ordered,
                tuple(sorted(active_metrics - present, key=lambda item: item.value)),
            )

    def _materialize_hotspots(
        self,
        selected: Sequence[_ScoredSubject],
        evidence: EvidenceIndex,
        lineage: str,
        previous: RiskAnalysisReport | None,
    ) -> tuple[RiskHotspot, ...]:
        previous_by_subject = (
            {item.subject_id: item for item in previous.hotspots}
            if previous is not None
            and previous.configuration_fingerprint == self._digest(self.configuration.to_dict())
            and previous.producer_version == self.PRODUCER_VERSION
            else {}
        )
        total_weight = sum(weight for _, weight in self.configuration.weights)
        hotspots = []
        for rank, candidate in enumerate(selected, 1):
            published_score = round(candidate.score, self._OUTPUT_PRECISION)
            available_weight = sum(
                self._weights[item.seed.metric] for item in candidate.factors
            )
            factors = []
            evidence_ids = []
            limitations = set()
            roles = []
            coverage_numerator = 0.0
            for item in candidate.factors:
                seed = item.seed
                record = EvidenceRecord.create(
                    seed.evidence_kind,
                    seed.subject_id,
                    seed.producer,
                    lineage,
                    source_refs=seed.source_refs,
                    scope=f"{candidate.subject.scope.value}:{candidate.subject.project}",
                    language=candidate.subject.language,
                    detail={
                        **dict(seed.detail),
                        "metric": seed.metric.value,
                        "raw_value": seed.value,
                        "unit": seed.unit,
                        "window": seed.window,
                        "normalization": item.normalization,
                    },
                    limitations=seed.limitations,
                    reliability=seed.reliability,
                    specificity=seed.specificity,
                )
                evidence_id = evidence.add(record)
                evidence_ids.append(evidence_id)
                roles.append(EvidenceRole(seed.metric.value, (evidence_id,)))
                configured_weight = self._weights[seed.metric]
                effective_weight = configured_weight / available_weight
                contribution = effective_weight * item.normalized
                coverage_numerator += configured_weight * seed.coverage
                metric_limitations = set(seed.limitations)
                if item.normalization.startswith("absolute-bands-small-cohort"):
                    metric_limitations.add(
                        "Low-coverage cohort: absolute bands replaced percentile normalization."
                    )
                elif item.normalization.startswith("absolute-bands-no-variance"):
                    metric_limitations.add(
                        "The comparable cohort had no variance, so absolute bands replaced a fabricated percentile spread."
                    )
                limitations.update(metric_limitations)
                factors.append(RiskFactor(
                    RiskMetric(
                        seed.metric,
                        seed.status,
                        seed.value,
                        round(item.normalized, self._OUTPUT_PRECISION),
                        seed.unit,
                        seed.window,
                        item.cohort,
                        seed.producer,
                        seed.coverage,
                        item.normalization,
                        (evidence_id,),
                        tuple(metric_limitations),
                    ),
                    configured_weight,
                    round(effective_weight, self._OUTPUT_PRECISION),
                    round(contribution, self._OUTPUT_PRECISION),
                ))
            confidence = self._confidence.calculate(
                tuple(roles),
                evidence,
                coverage=round(
                    coverage_numerator / total_weight,
                    self._OUTPUT_PRECISION,
                ),
            )
            trend = RiskTrend.UNAVAILABLE
            prior = previous_by_subject.get(candidate.subject.node.id)
            if prior is not None and self._comparable_trend(candidate, factors, prior):
                trend = (
                    RiskTrend.INCREASING
                    if published_score > prior.score
                    else RiskTrend.DECREASING
                    if published_score < prior.score
                    else RiskTrend.STABLE
                )
            if trend is RiskTrend.UNAVAILABLE:
                limitations.add(
                    "Trend is unavailable without a compatible prior PR132 report containing this subject."
                )
            hotspots.append(RiskHotspot(
                rank,
                candidate.subject.node.id,
                candidate.subject.display_name,
                candidate.subject.project,
                candidate.subject.node.kind.value,
                candidate.subject.language,
                candidate.subject.scope,
                candidate.subject.cohort,
                published_score,
                confidence,
                tuple(factors),
                tuple(evidence_ids),
                candidate.missing,
                trend,
                (
                    f"Risk indicator based on {len(factors)} available structured metric"
                    f"{'s' if len(factors) != 1 else ''}; this is not a bug or defect finding."
                ),
                tuple(limitations),
            ))
        return tuple(hotspots)

    @staticmethod
    def _comparable_trend(
        candidate: _ScoredSubject,
        factors: Sequence[RiskFactor],
        prior: RiskHotspot,
    ) -> bool:
        if (
            prior.cohort != candidate.subject.cohort
            or prior.project != candidate.subject.project
            or prior.kind != candidate.subject.node.kind.value
            or prior.language != candidate.subject.language
            or prior.scope is not candidate.subject.scope
        ):
            return False
        current = {
            item.metric.metric: RiskAnalysisService._trend_factor_identity(item)
            for item in factors
        }
        previous = {
            item.metric.metric: RiskAnalysisService._trend_factor_identity(item)
            for item in prior.factors
        }
        return current == previous

    @staticmethod
    def _trend_factor_identity(factor: RiskFactor) -> tuple[str, str, str, str]:
        metric = factor.metric
        window = metric.window
        if (
            metric.metric in {
                RiskMetricKind.CHANGE_FREQUENCY,
                RiskMetricKind.OWNERSHIP_CONCENTRATION,
            }
            and metric.producer.startswith("git-context.")
        ):
            window = window.partition("@")[0]
        return (
            metric.unit,
            window,
            metric.normalization,
            metric.producer,
        )

    def _capabilities(
        self,
        seeds: Mapping[tuple[str, RiskMetricKind], _MetricSeed],
        normalized: Mapping[tuple[str, RiskMetricKind], _NormalizedSeed],
        subjects: Mapping[str, _Subject],
        hotspots: Sequence[RiskHotspot],
        evidence: EvidenceIndex,
        lineage: str,
    ) -> tuple[RiskCapability, ...]:
        result = []
        evidence_by_metric: dict[RiskMetricKind, set[str]] = defaultdict(set)
        for hotspot in hotspots:
            for factor in hotspot.factors:
                evidence_by_metric[factor.metric.metric].update(factor.metric.evidence_ids)
        for metric in RiskMetricKind:
            values = [seed for seed in seeds.values() if seed.metric is metric]
            eligible = [
                seed for seed in values
                if self._included(subjects[seed.subject_id].scope)
            ]
            scored = [
                item for item in normalized.values()
                if item.seed.metric is metric
                and self._included(subjects[item.seed.subject_id].scope)
            ]
            if not eligible or not scored:
                status = RiskAvailability.UNAVAILABLE
            elif len(scored) < len(eligible) or any(
                item.status is not RiskAvailability.AVAILABLE for item in eligible
            ):
                status = RiskAvailability.PARTIAL
            else:
                status = RiskAvailability.AVAILABLE
            limitations = set(self._capability_limitations(metric, values))
            limitations.update(
                limitation for seed in values for limitation in seed.limitations
            )
            producers = sorted({seed.producer for seed in values})
            selected_producers = tuple(
                producers[: self._CAPABILITY_PRODUCER_LIMIT]
            )
            omitted_producers = len(producers) - len(selected_producers)
            if omitted_producers:
                limitations.add(
                    f"{omitted_producers} additional metric producer(s) were omitted from the bounded capability summary."
                )
            if values:
                source_refs, omitted_refs = self._aggregate_source_refs(values, lineage)
                aggregate = EvidenceRecord.create(
                    EvidenceKind.ANALYSIS_RESULT,
                    f"risk-capability:{metric.value}",
                    self.PRODUCER_VERSION,
                    lineage,
                    source_refs=source_refs,
                    detail={
                        "metric": metric.value,
                        "status": status.value,
                        "observation_count": len(values),
                        "scored_subject_count": len(scored),
                        "omitted_source_reference_count": omitted_refs,
                        "input_fingerprint": lineage.removeprefix("risk-analysis:"),
                    },
                    limitations=tuple(limitations),
                    reliability=STRUCTURED_ANALYZER_RELIABILITY,
                    specificity=1.0,
                )
                evidence_by_metric[metric].add(evidence.add(aggregate))
            result.append(RiskCapability(
                metric,
                status,
                len(values),
                len(scored),
                tuple(subjects[seed.subject_id].scope.value for seed in values),
                tuple(seed.unit for seed in values),
                selected_producers,
                tuple(evidence_by_metric[metric]),
                tuple(limitations),
                omitted_producers,
            ))
        return tuple(result)

    @classmethod
    def _aggregate_source_refs(
        cls,
        values: Sequence[_MetricSeed],
        lineage: str,
    ) -> tuple[tuple[str, ...], int]:
        refs = sorted({reference for seed in values for reference in seed.source_refs})
        selected = tuple((
            f"risk-input:{lineage}",
            *refs[: cls._AGGREGATE_SOURCE_REF_LIMIT],
        ))
        return selected, max(0, len(refs) - cls._AGGREGATE_SOURCE_REF_LIMIT)

    def _heatmaps(
        self,
        values: Mapping[tuple[str, RiskMetricKind], _NormalizedSeed],
        subjects: Mapping[str, _Subject],
        capabilities: Sequence[RiskCapability],
        evidence: EvidenceIndex,
        lineage: str,
    ) -> tuple[RiskHeatmap, ...]:
        status_by_metric = {item.metric: item.status for item in capabilities}
        grouped: dict[tuple[RiskMetricKind, str], list[float]] = defaultdict(list)
        for (subject_id, metric), item in values.items():
            if not self._included(subjects[subject_id].scope):
                continue
            grouped[(metric, item.cohort)].append(item.normalized)
        result = []
        for metric in RiskMetricKind:
            all_cohorts = []
            for (candidate_metric, cohort), normalized in sorted(
                grouped.items(), key=lambda item: (item[0][0].value, item[0][1])
            ):
                if candidate_metric is not metric:
                    continue
                counts = [0, 0, 0, 0, 0]
                for value in normalized:
                    counts[min(int(value * 5), 4)] += 1
                all_cohorts.append(RiskHeatmapCohort(
                    cohort,
                    len(normalized),
                    tuple(
                        RiskHeatmapBin(label, count)
                        for label, count in zip(
                            self._HEATMAP_LABELS,
                            counts,
                            strict=True,
                        )
                    ),
                ))
            selected_cohorts = sorted(
                all_cohorts,
                key=lambda item: (-item.subject_count, item.cohort),
            )[: self._HEATMAP_COHORT_LIMIT]
            omitted_cohort_count = len(all_cohorts) - len(selected_cohorts)
            omitted_subject_count = sum(
                item.subject_count
                for item in all_cohorts
                if item not in selected_cohorts
            )
            limitations = list(self._heatmap_limitations(
                metric,
                selected_cohorts,
                next(item for item in capabilities if item.metric is metric),
            ))
            if omitted_cohort_count:
                limitations.append(
                    f"{omitted_cohort_count} additional cohort(s) containing "
                    f"{omitted_subject_count} subject(s) were omitted from the bounded heatmap."
                )
            heatmap_limitations = tuple(limitations)
            evidence_ids: tuple[str, ...] = ()
            if selected_cohorts:
                metric_values = [
                    item.seed
                    for (subject_id, candidate_metric), item in values.items()
                    if candidate_metric is metric
                    and self._included(subjects[subject_id].scope)
                ]
                source_refs, omitted_refs = self._aggregate_source_refs(
                    metric_values, lineage
                )
                record = EvidenceRecord.create(
                    EvidenceKind.ANALYSIS_RESULT,
                    f"risk-heatmap:{metric.value}",
                    self.PRODUCER_VERSION,
                    lineage,
                    source_refs=source_refs,
                    detail={
                        "metric": metric.value,
                        "cohort_count": len(all_cohorts),
                        "included_cohort_count": len(selected_cohorts),
                        "omitted_cohort_count": omitted_cohort_count,
                        "subject_count": sum(item.subject_count for item in all_cohorts),
                        "omitted_subject_count": omitted_subject_count,
                        "omitted_source_reference_count": omitted_refs,
                        "input_fingerprint": lineage.removeprefix("risk-analysis:"),
                    },
                    limitations=heatmap_limitations,
                    reliability=STRUCTURED_ANALYZER_RELIABILITY,
                    specificity=1.0,
                )
                evidence_ids = (evidence.add(record),)
            result.append(RiskHeatmap(
                metric,
                status_by_metric[metric],
                tuple(selected_cohorts),
                evidence_ids,
                heatmap_limitations,
                omitted_cohort_count,
                omitted_subject_count,
            ))
        return tuple(result)

    @staticmethod
    def _heatmap_limitations(
        metric: RiskMetricKind,
        cohorts: Sequence[RiskHeatmapCohort],
        capability: RiskCapability,
    ) -> tuple[str, ...]:
        if cohorts:
            return (
                "Heatmap bins contain normalized risk indicators within comparable cohorts.",
            )
        if metric is RiskMetricKind.COMPLEXITY and capability.observation_count == 0:
            return (
                "Complexity heatmap is unavailable because no structured complexity producer ran.",
            )
        return ("Heatmap is unavailable because this metric has no normalized observations.",)

    @staticmethod
    def _capability_limitations(
        metric: RiskMetricKind,
        values: Sequence[_MetricSeed],
    ) -> tuple[str, ...]:
        if metric is RiskMetricKind.COMPLEXITY:
            base = (
                "No production complexity producer is currently connected to semantic snapshots.",
                "Runtime profiling, names, graph degree, and LLM output are not code complexity evidence.",
            )
            return base if not values else (
                "Complexity observations came from explicit structured producers; Atlas has no built-in snapshot complexity producer yet.",
            )
        if metric in {RiskMetricKind.FAN_IN, RiskMetricKind.FAN_OUT}:
            return (
                "Containment ownership and member_of relationships are excluded from coupling degree.",
                "Missing canonical call relationships are not counted as zero calls.",
            )
        if metric is RiskMetricKind.CHANGE_FREQUENCY:
            if not values:
                return ("Bounded Git history was unavailable; change frequency is unknown, not zero.",)
            return (
                "The score uses commits touching a project; text line churn is retained only as evidence detail.",
            )
        if metric is RiskMetricKind.OWNERSHIP_CONCENTRATION:
            if not values:
                return (
                "Contributor concentration is unavailable without bounded Git history.",
                "PR129 containment ownership is not developer ownership.",
            )
            return (
                "The built-in Git metric is a bounded change-author concentration proxy, not blame ownership or developer performance.",
                "PR129 containment ownership is never used as contributor ownership.",
            )
        if metric is RiskMetricKind.LOW_TEST_DENSITY:
            return (
                "Resolved production-symbol-to-test mapping is unavailable.",
                "Project test-file counts are not treated as test coverage or resolved test density.",
            ) if not values else (
                "Low-test-density observations came from explicit structured evidence, not project test-file counts.",
            )
        if metric is RiskMetricKind.SIZE:
            return ("Size is available only as inventoried project bytes, not symbol LOC.",)
        return ()

    def _subjects(
        self,
        graph: KnowledgeGraph,
        summary: Mapping[str, object],
        metadata: Mapping[str, Mapping[str, object]],
        relevant_subject_ids: frozenset[str],
    ) -> dict[str, _Subject]:
        projects = {
            str(item.get("name", "")): item
            for item in self._projects(summary)
        }
        result = {}
        for node_id in sorted(relevant_subject_ids):
            node = graph.get(node_id)
            if node is None:
                continue
            if node.kind is KnowledgeKind.PROJECT:
                project = node.name
                item = projects.get(project, {})
                scope = self._project_scope(item)
                language = self._primary_language(item)
            elif node.kind in self._SYMBOL_KINDS:
                item = metadata.get(node.id, {})
                scope = self._symbol_scope(item)
                project = node.project_id or str(item.get("project_id") or "repository")
                raw_metadata = item.get("metadata", {})
                nested = raw_metadata if isinstance(raw_metadata, Mapping) else {}
                fallback_language = item.get("language") or nested.get("language")
                if not fallback_language:
                    source = item.get("source")
                    if isinstance(source, str):
                        fallback_language = {
                            ".java": "java", ".py": "python", ".pyi": "python",
                            ".ts": "typescript", ".tsx": "typescript",
                        }.get(PurePosixPath(source).suffix.casefold())
                language = str(
                    node.language
                    if node.language not in {"", "unknown"}
                    else fallback_language or "unknown"
                ).casefold()
            else:
                continue
            display_name = node.qualified_name or node.name or node.id
            cohort = f"language={language}|kind={node.kind.value}|scope={scope.value}"
            result[node.id] = _Subject(
                node,
                display_name,
                project,
                language,
                scope,
                cohort,
            )
        return result

    @classmethod
    def _project_scope(cls, value: Mapping[str, object]) -> RiskScope:
        production = cls._integer(value.get(
            "classified_non_test_source_files", value.get("production_files")
        ))
        tests = cls._integer(value.get(
            "classified_test_source_files", value.get("test_files")
        ))
        generated = cls._integer(value.get(
            "classified_generated_files", value.get("generated_files")
        ))
        if production and production > 0:
            return RiskScope.PRODUCTION
        if tests and tests > 0:
            return RiskScope.TEST
        if generated and generated > 0:
            return RiskScope.GENERATED
        return RiskScope.UNKNOWN

    @classmethod
    def _symbol_scope(cls, value: Mapping[str, object]) -> RiskScope:
        raw_metadata = value.get("metadata", {})
        metadata = raw_metadata if isinstance(raw_metadata, Mapping) else {}
        explicit = str(metadata.get("source_classification", "")).casefold()
        if explicit in {item.value for item in RiskScope}:
            return RiskScope(explicit)
        if explicit:
            return RiskScope.UNKNOWN
        source = value.get("source")
        if not isinstance(source, str) or not source:
            return RiskScope.UNKNOWN
        parts = tuple(
            part.casefold()
            for part in PurePosixPath(source.replace("\\", "/")).parts[:-1]
        )
        if set(parts) & GENERATED_DIRECTORY_NAMES:
            return RiskScope.GENERATED
        if is_test_source_path(PurePosixPath(source.replace("\\", "/"))):
            return RiskScope.TEST
        return RiskScope.PRODUCTION

    @staticmethod
    def _primary_language(value: Mapping[str, object]) -> str:
        raw = value.get("language_file_counts", value.get("languages", {}))
        if not isinstance(raw, Mapping) or not raw:
            return "unknown"
        candidates = []
        for language, count in raw.items():
            parsed = RiskAnalysisService._integer(count)
            if parsed is not None:
                candidates.append((parsed, str(language).casefold()))
        return (
            sorted(candidates, key=lambda item: (-item[0], item[1]))[0][1]
            if candidates
            else "unknown"
        )

    def _included(self, scope: RiskScope) -> bool:
        return (
            scope is RiskScope.PRODUCTION
            or scope is RiskScope.TEST and self.configuration.include_test
            or scope is RiskScope.GENERATED and self.configuration.include_generated
            or scope is RiskScope.UNKNOWN and self.configuration.include_unknown
        )

    @staticmethod
    def _metadata(
        values: Sequence[Mapping[str, object]],
        selected_ids: frozenset[str],
    ) -> dict[str, Mapping[str, object]]:
        result: dict[str, Mapping[str, object]] = {}
        for item in values:
            if not isinstance(item, Mapping) or item.get("id") is None:
                continue
            subject_id = str(item.get("id"))
            if subject_id not in selected_ids:
                continue
            existing = result.get(subject_id)
            if existing is not None and existing != item:
                raise ValueError(
                    f"conflicting duplicate symbol metadata for canonical ID: {subject_id}"
                )
            result[subject_id] = item
        return result

    @classmethod
    def _relevant_subject_ids(
        cls,
        graph: KnowledgeGraph,
        metric_inputs: Sequence[RiskMetricInput],
    ) -> frozenset[str]:
        result = {
            node.id for node in graph.nodes if node.kind is KnowledgeKind.PROJECT
        }
        result.update(item.subject_id for item in metric_inputs)
        for edge in graph.edges:
            if edge.relation not in cls._SYMBOL_RELATIONS:
                continue
            source = graph.get(edge.source)
            target = graph.get(edge.target)
            if (
                source is not None
                and target is not None
                and source.kind in cls._SYMBOL_KINDS
                and target.kind in cls._SYMBOL_KINDS
            ):
                result.add(source.id)
                result.add(target.id)
        return frozenset(result)

    @staticmethod
    def _records(value: object) -> tuple[Mapping[str, object], ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(item for item in value if isinstance(item, Mapping))

    @classmethod
    def _projects(
        cls,
        summary: Mapping[str, object],
    ) -> tuple[Mapping[str, object], ...]:
        by_name: dict[str, Mapping[str, object]] = {}
        for item in cls._records(summary.get("projects")):
            name = str(item.get("name", ""))
            existing = by_name.get(name)
            if existing is not None and existing != item:
                raise ValueError(
                    f"conflicting duplicate repository-summary project: {name}"
                )
            by_name[name] = item
        return tuple(
            by_name[name]
            for name in sorted(by_name)
        )

    @staticmethod
    def _normalize_project_path(value: str) -> str:
        normalized = PurePosixPath(value.replace("\\", "/")).as_posix().strip("/")
        return normalized if normalized not in {"", "."} else "."

    @staticmethod
    def _integer(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            result = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return None
        return result if result >= 0 else None

    @staticmethod
    def _finite_non_negative(value: object) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            result = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return None
        return result if math.isfinite(result) and result >= 0 else None

    @classmethod
    def _fingerprint(
        cls,
        graph_digest: str,
        summary: Mapping[str, object],
        metadata: Mapping[str, Mapping[str, object]],
        history: GitHistoryWindow | None,
        metric_inputs: Sequence[RiskMetricInput],
        previous: RiskAnalysisReport | None,
        failed_projects: Sequence[str],
        configuration_fingerprint: str,
    ) -> str:
        selected_projects = [
            {
                key: item.get(key)
                for key in (
                    "name", "path", "languages", "language_file_counts",
                    "files", "size", "inventoried_file_count",
                    "inventoried_file_bytes", "inventoried_file_size_error_count",
                    "production_files", "test_files",
                    "generated_files", "classified_non_test_source_files",
                    "classified_test_source_files", "classified_generated_files",
                )
                if key in item
            }
            for item in cls._projects(summary)
        ]
        selected_projects.sort(key=lambda item: (
            str(item.get("name", "")),
            str(item.get("path", "")),
            json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        ))
        selected_metadata = {
            subject_id: {
                key: item.get(key)
                for key in ("project_id", "source", "metadata")
                if key in item
            }
            for subject_id, item in sorted(metadata.items())
        }
        return cls._digest({
            "producer_version": cls.PRODUCER_VERSION,
            "schema_version": cls.SCHEMA_VERSION,
            "graph_digest": graph_digest,
            "configuration_fingerprint": configuration_fingerprint,
            "projects": selected_projects,
            "symbols": selected_metadata,
            "git_history": None if history is None else history.to_dict(),
            "metric_inputs": [
                item.to_dict()
                for item in sorted(metric_inputs, key=lambda value: (
                    value.subject_id, value.metric.value, value.producer,
                ))
            ],
            "previous_input_fingerprint": (
                None if previous is None else previous.input_fingerprint
            ),
            "failed_projects": sorted(set(map(str, failed_projects))),
        })

    @staticmethod
    def _digest(value: object) -> str:
        return hashlib.sha256(json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")).hexdigest()
