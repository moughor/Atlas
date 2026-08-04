from __future__ import annotations

from dataclasses import dataclass

from moughorai.git_diff import DiffFile, GitDiff
from moughorai.impact_analysis import (
    ImpactCapabilityState,
    ImpactCategory,
    ImpactPredictionRequest,
    ImpactPredictionResponse,
    ImpactPredictionService,
)
from moughorai.measurement import MeasurementSession
from moughorai.refactoring_advisor import (
    RefactoringAdvisorService,
    RefactoringFamily,
    RefactoringRequest,
    RefactoringResponse,
)
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    EvidenceIndex,
    EvidenceRecord,
    EvidenceRole,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import (
    CanonicalSubjectResolver,
    PathSubjectCandidates,
    SubjectCandidate,
    SubjectQuery,
)

from .models import (
    ChangeReviewDiff,
    ChangeReviewDiffMode,
    ChangeReviewRequest,
    ChangeReviewResponse,
    ChangeReviewSection,
    ChangeReviewState,
    ChangedFileReview,
    ChangedFileStatus,
    SnapshotAlignmentState,
    _association_evidence_record,
    _git_evidence_record,
    _mapping_evidence_record,
    change_review_fingerprint,
)


_FILE_ASSOCIATION_LIMITATION = (
    "The snapshot has no declaration source spans; an exact file association "
    "does not prove that a Git hunk changed this subject."
)
_UNTRACKED_LIMITATION = (
    "Git diff collection excludes untracked files; their review state is unknown."
)
_NO_NEGATIVE_TEST_CLAIM = (
    "No evidence-backed targeted test was returned; missing call or test coverage "
    "must not be interpreted as evidence that no tests are required."
)


@dataclass(frozen=True, slots=True)
class _FilePlan:
    diff_file: DiffFile
    path: str
    status: ChangedFileStatus
    candidates: PathSubjectCandidates | None
    limitations: tuple[str, ...]


class ChangeReviewService:
    """Compose existing Atlas evidence into a bounded Git-aware review."""

    def __init__(
        self,
        snapshot: AtlasSemanticSnapshot,
        resolver: CanonicalSubjectResolver,
        *,
        measurement: MeasurementSession | None = None,
    ) -> None:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError("change review requires an Atlas semantic snapshot")
        if not isinstance(resolver, CanonicalSubjectResolver):
            raise TypeError("change review requires the canonical subject resolver")
        self._snapshot = snapshot
        self._resolver = resolver
        self._measurement = measurement or MeasurementSession()

    @property
    def resolver(self) -> CanonicalSubjectResolver:
        return self._resolver

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AtlasSemanticSnapshot,
        *,
        measurement: MeasurementSession | None = None,
    ) -> ChangeReviewService:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError("change review snapshot is invalid")
        session = measurement or MeasurementSession()
        with session.scope(
            "change_review.resolver_index",
            consumer="change-review",
            sample_key=snapshot.snapshot_id,
        ) as scope:
            resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
            graph = resolver.graph
            scope.add_units(
                len(graph.nodes) + len(graph.edges) if graph is not None else 0
            )
            scope.set_objects_retained(len(graph.nodes) if graph is not None else 0)
        return cls(snapshot, resolver, measurement=session)

    def review(
        self,
        diff: GitDiff,
        request: ChangeReviewRequest | None = None,
        *,
        current_workspace_fingerprint: str | None = None,
    ) -> ChangeReviewResponse:
        if not isinstance(diff, GitDiff):
            raise TypeError("change review diff is invalid")
        selected_request = request or ChangeReviewRequest()
        if not isinstance(selected_request, ChangeReviewRequest):
            raise TypeError("change review request is invalid")
        current = (
            current_workspace_fingerprint.strip()
            if current_workspace_fingerprint is not None
            and current_workspace_fingerprint.strip()
            else None
        )
        alignment = self._alignment(selected_request, current)
        semantic_enabled = alignment in {
            SnapshotAlignmentState.CURRENT,
            SnapshotAlignmentState.ASSUMED_CURRENT,
        }

        selected_files = diff.files[: selected_request.maximum_files]
        omitted_files = len(diff.files) - len(selected_files)
        diff_metadata = ChangeReviewDiff(
            self._diff_mode(diff),
            diff.fingerprint,
            diff.base,
            diff.head,
            diff.repository_head,
            diff.base_commit,
            diff.head_commit,
            diff.workspace_prefix,
            len(diff.files),
            len(selected_files),
            omitted_files,
        )

        with self._measurement.scope(
            "change_review.path_association",
            consumer="change-review",
            sample_key=diff.fingerprint,
        ) as scope:
            plans = tuple(
                self._plan_file(
                    item,
                    selected_request.maximum_subjects_per_file,
                    alignment,
                    semantic_enabled,
                )
                for item in selected_files
            )
            selected_candidates = self._round_robin_candidates(
                plans, selected_request.maximum_subjects
            )
            total_subject_count = sum(
                plan.candidates.total_candidate_count
                if plan.candidates is not None else 0
                for plan in plans
            )
            returned_subject_count = sum(len(items) for items in selected_candidates)
            scope.add_units(len(plans) + total_subject_count)
            scope.add_objects_produced(returned_subject_count)
            scope.set_objects_retained(returned_subject_count)

        evidence = EvidenceIndex()
        files: list[ChangedFileReview] = []
        git_evidence_ids: list[str] = []
        mapping_evidence_ids: list[str] = []
        exact_subjects: dict[str, SubjectCandidate] = {}
        architecture_scope_subjects: dict[str, SubjectCandidate] = {}
        for plan, candidates in zip(plans, selected_candidates, strict=True):
            file_record = self._git_evidence(diff, plan)
            evidence.add(file_record)
            git_evidence_ids.append(file_record.evidence_id)
            fallback = bool(plan.candidates and plan.candidates.project_fallback)
            total_for_file = (
                plan.candidates.total_candidate_count
                if plan.candidates is not None else 0
            )
            mapping_record = self._mapping_evidence(
                file_record,
                plan.path,
                total_for_file,
                len(candidates),
                fallback,
                alignment,
            )
            evidence.add(mapping_record)
            mapping_evidence_ids.append(mapping_record.evidence_id)
            evidence_ids = [file_record.evidence_id, mapping_record.evidence_id]
            exact_association_ids: list[str] = []
            candidate_sources = {
                item.canonical_id: item.source_refs
                for item in (
                    plan.candidates.candidate_evidence
                    if plan.candidates is not None else ()
                )
            }
            candidate_evidence = tuple(
                item
                for candidate in candidates
                for item in (
                    plan.candidates.candidate_evidence
                    if plan.candidates is not None else ()
                )
                if item.canonical_id == candidate.canonical_id
            )
            for candidate in candidates:
                association = self._association_evidence(
                    file_record,
                    candidate,
                    plan.path,
                    fallback,
                    candidate_sources[candidate.canonical_id],
                )
                evidence.add(association)
                evidence_ids.append(association.evidence_id)
                mapping_evidence_ids.append(association.evidence_id)
                if not fallback:
                    exact_association_ids.append(association.evidence_id)
                    exact_subjects[candidate.canonical_id] = candidate
                elif candidate.kind.value == "project":
                    # A containing project is not an impact root, but it is a
                    # valid structural scope for PR137's already-proven cycle
                    # seam intersection.
                    architecture_scope_subjects[candidate.canonical_id] = candidate
            limitations = set(plan.limitations)
            if total_for_file > len(candidates):
                limitations.add(
                    "File-associated subjects were deterministically bounded before downstream analysis."
                )
            coverage = (
                len(candidates) / total_for_file if total_for_file else 0.0
            )
            semantic_confidence = ConfidenceCalculator().calculate(
                (
                    EvidenceRole("git_change", (file_record.evidence_id,), True),
                    EvidenceRole(
                        "path_mapping",
                        (mapping_record.evidence_id,),
                        True,
                    ),
                    EvidenceRole(
                        "exact_path_identity",
                        tuple(exact_association_ids),
                        True,
                    ),
                ),
                evidence,
                coverage=coverage,
                ambiguity_penalty=(
                    0.10 if total_for_file > 1 and not fallback else 0.0
                ),
            )
            files.append(ChangedFileReview(
                plan.path,
                plan.diff_file.old_path,
                plan.diff_file.new_path,
                plan.status,
                plan.diff_file.binary,
                len(plan.diff_file.hunks),
                len(plan.diff_file.added_lines),
                len(plan.diff_file.removed_lines),
                candidates,
                candidate_evidence,
                total_for_file,
                total_for_file - len(candidates),
                fallback,
                semantic_confidence,
                tuple(evidence_ids),
                tuple(sorted(limitations)),
            ))

        roots = tuple(sorted(exact_subjects.values(), key=lambda item: item.canonical_id))
        architecture_roots = tuple(sorted(
            {**exact_subjects, **architecture_scope_subjects}.values(),
            key=lambda item: item.canonical_id,
        ))
        impact = self._impact(roots, selected_request) if semantic_enabled else None
        architecture, architecture_states, architecture_limitations = (
            self._architecture(architecture_roots, selected_request)
            if semantic_enabled
            else ((), (), ())
        )
        sections = self._sections(
            alignment,
            diff_metadata,
            tuple(files),
            roots,
            architecture_roots,
            impact,
            architecture,
            architecture_states,
            architecture_limitations,
            tuple(git_evidence_ids),
            tuple(mapping_evidence_ids),
            selected_request,
        )
        limitations = {
            _UNTRACKED_LIMITATION,
            "PR140 reviews current snapshot evidence; it does not compare semantic state before and after the diff.",
        }
        if omitted_files:
            limitations.add(
                f"{omitted_files} changed file(s) were omitted by the deterministic request bound."
            )
        if total_subject_count > returned_subject_count:
            limitations.add(
                f"{total_subject_count - returned_subject_count} file-associated subject(s) were omitted by deterministic bounds."
            )
        if alignment is SnapshotAlignmentState.ASSUMED_CURRENT:
            limitations.add(
                "Snapshot currency was explicitly assumed by the caller and was not independently verified."
            )
        elif alignment is SnapshotAlignmentState.UNKNOWN:
            limitations.add(
                "Snapshot currency is unknown; semantic enrichment was disabled."
            )
        elif alignment is SnapshotAlignmentState.STALE:
            limitations.add(
                "The supplied workspace fingerprint differs from the snapshot; semantic enrichment was disabled."
            )
        if self._resolver.graph is None:
            limitations.add(
                "The canonical PR129 graph is unavailable or incompatible."
            )
        fingerprint = change_review_fingerprint(
            selected_request,
            diff_metadata,
            self._snapshot.snapshot_id,
            self._resolver.graph_digest,
            alignment,
            current,
        )
        with self._measurement.scope(
            "change_review.materialize",
            consumer="change-review",
            sample_key=diff.fingerprint,
        ) as scope:
            response = ChangeReviewResponse(
                selected_request,
                diff_metadata,
                alignment,
                tuple(files),
                sections,
                evidence.freeze(),
                fingerprint,
                self._resolver.graph_digest,
                self._snapshot.snapshot_id,
                self._snapshot.workspace_fingerprint,
                current,
                impact,
                architecture,
                total_subject_count,
                total_subject_count - returned_subject_count,
                tuple(sorted(limitations)),
            )
            scope.add_units(len(files) + len(sections))
            scope.add_objects_produced(
                len(files) + len(sections) + len(evidence)
            )
            scope.set_objects_retained(len(files) + len(evidence))
            return response

    def _alignment(
        self,
        request: ChangeReviewRequest,
        current_workspace_fingerprint: str | None,
    ) -> SnapshotAlignmentState:
        if current_workspace_fingerprint is not None:
            return (
                SnapshotAlignmentState.CURRENT
                if current_workspace_fingerprint == self._snapshot.workspace_fingerprint
                else SnapshotAlignmentState.STALE
            )
        if request.assume_snapshot_current:
            return SnapshotAlignmentState.ASSUMED_CURRENT
        return SnapshotAlignmentState.UNKNOWN

    @staticmethod
    def _diff_mode(diff: GitDiff) -> ChangeReviewDiffMode:
        if diff.staged:
            return ChangeReviewDiffMode.STAGED
        if diff.base is not None and diff.head is not None:
            return ChangeReviewDiffMode.BASE_TO_HEAD
        if diff.base is not None:
            return ChangeReviewDiffMode.BASE_TO_WORKING_TREE
        return ChangeReviewDiffMode.WORKING_TREE

    def _plan_file(
        self,
        item: DiffFile,
        maximum_candidates: int,
        alignment: SnapshotAlignmentState,
        semantic_enabled: bool,
    ) -> _FilePlan:
        path = item.new_path or item.old_path
        if path is None:  # DiffFile already prevents this; retain a defensive guard.
            raise ValueError("change review diff file has no usable path")
        status = self._file_status(item)
        limitations = {_FILE_ASSOCIATION_LIMITATION}
        candidates: PathSubjectCandidates | None = None
        if item.binary:
            limitations.add(
                "Binary changes have no source-free declaration attribution."
            )
        elif status is ChangedFileStatus.DELETED:
            limitations.add(
                "Deleted subjects require a compatible base snapshot; current-snapshot identity was not guessed."
            )
        elif not semantic_enabled:
            limitations.add(
                (
                    "Semantic association was disabled because the snapshot is stale."
                    if alignment is SnapshotAlignmentState.STALE
                    else "Semantic association was disabled because snapshot currency is unknown."
                )
            )
        else:
            candidates = self._resolver.candidates_for_path(
                path, maximum_candidates=maximum_candidates
            )
            if not candidates.candidates:
                limitations.add(
                    "No exact current-snapshot subject was associated with this path; absence is not proof of no impact."
                )
            if candidates.project_fallback:
                limitations.add(
                    "Only containing-project context was available; it was not used as an exact changed-subject impact root."
                )
            elif candidates.total_candidate_count > 1:
                limitations.add(
                    "The exact path is associated with multiple canonical subjects; path evidence does not identify which declaration a hunk changed."
                )
        if status is ChangedFileStatus.RENAMED:
            limitations.add(
                "Git rename metadata does not prove semantic identity continuity between old and new subjects."
            )
        return _FilePlan(item, path, status, candidates, tuple(sorted(limitations)))

    @staticmethod
    def _file_status(item: DiffFile) -> ChangedFileStatus:
        if item.renamed:
            return ChangedFileStatus.RENAMED
        if item.old_path is None:
            return ChangedFileStatus.ADDED
        if item.new_path is None:
            return ChangedFileStatus.DELETED
        return ChangedFileStatus.MODIFIED

    @staticmethod
    def _round_robin_candidates(
        plans: tuple[_FilePlan, ...], maximum_subjects: int
    ) -> tuple[tuple[SubjectCandidate, ...], ...]:
        selected: list[list[SubjectCandidate]] = [[] for _ in plans]
        candidate_lists = [
            plan.candidates.candidates if plan.candidates is not None else ()
            for plan in plans
        ]
        retained = 0
        offset = 0
        while retained < maximum_subjects:
            progress = False
            for index, candidates in enumerate(candidate_lists):
                if offset < len(candidates):
                    selected[index].append(candidates[offset])
                    retained += 1
                    progress = True
                    if retained == maximum_subjects:
                        break
            if not progress:
                break
            offset += 1
        return tuple(tuple(items) for items in selected)

    def _git_evidence(self, diff: GitDiff, plan: _FilePlan) -> EvidenceRecord:
        return _git_evidence_record(
            lineage=self._snapshot.snapshot_id,
            diff_fingerprint=diff.fingerprint,
            path=plan.path,
            old_path=plan.diff_file.old_path,
            new_path=plan.diff_file.new_path,
            status=plan.status,
            binary=plan.diff_file.binary,
            hunk_count=len(plan.diff_file.hunks),
            added_line_count=len(plan.diff_file.added_lines),
            removed_line_count=len(plan.diff_file.removed_lines),
        )

    def _mapping_evidence(
        self,
        file_record: EvidenceRecord,
        path: str,
        total_subject_count: int,
        returned_subject_count: int,
        project_fallback: bool,
        alignment: SnapshotAlignmentState,
    ) -> EvidenceRecord:
        return _mapping_evidence_record(
            lineage=self._snapshot.snapshot_id,
            file_record=file_record,
            path=path,
            total_subject_count=total_subject_count,
            returned_subject_count=returned_subject_count,
            project_fallback=project_fallback,
            alignment=alignment,
        )

    def _association_evidence(
        self,
        file_record: EvidenceRecord,
        candidate: SubjectCandidate,
        path: str,
        project_fallback: bool,
        path_source_refs: tuple[str, ...],
    ) -> EvidenceRecord:
        return _association_evidence_record(
            lineage=self._snapshot.snapshot_id,
            file_record=file_record,
            candidate=candidate,
            path=path,
            project_fallback=project_fallback,
            path_source_refs=path_source_refs,
        )

    def _impact(
        self,
        roots: tuple[SubjectCandidate, ...],
        request: ChangeReviewRequest,
    ) -> ImpactPredictionResponse | None:
        if not roots or self._resolver.graph is None:
            return None
        service = ImpactPredictionService(
            self._resolver,
            snapshot_id=self._snapshot.snapshot_id,
            analyzer_version=self._snapshot.analyzer_version,
            semantic_context=self._snapshot.semantic_context,
            measurement=self._measurement,
        )
        queries = tuple(SubjectQuery(item.canonical_id) for item in roots)
        return service.predict(ImpactPredictionRequest(
            queries[0],
            request.change_kind,
            max_depth=request.impact_depth,
            limit=request.impact_limit,
            include_tests=True,
            include_dependencies=True,
            include_risk=True,
            additional_subjects=queries[1:],
        ))

    def _architecture(
        self,
        roots: tuple[SubjectCandidate, ...],
        request: ChangeReviewRequest,
    ) -> tuple[
        tuple[RefactoringResponse, ...],
        tuple[ChangeReviewState, ...],
        tuple[str, ...],
    ]:
        if not request.include_architecture or not roots or self._resolver.graph is None:
            return (), (), ()
        service = RefactoringAdvisorService(
            self._resolver,
            snapshot_id=self._snapshot.snapshot_id,
            analyzer_version=self._snapshot.analyzer_version,
            semantic_context=self._snapshot.semantic_context,
            measurement=self._measurement,
        )
        retained: list[RefactoringResponse] = []
        states: list[ChangeReviewState] = []
        limitations: set[str] = set()
        retained_advice_count = 0
        selected_roots = roots[: request.architecture_subject_limit]
        for candidate in selected_roots:
            remaining = request.architecture_advice_limit - retained_advice_count
            if remaining <= 0:
                break
            response = service.advise(RefactoringRequest(
                SubjectQuery(candidate.canonical_id),
                (RefactoringFamily.CYCLE_BREAKING,),
                remaining,
                False,
                request.impact_depth,
            ))
            if response.advice:
                limitations.update(response.limitations)
                retained.append(response)
                retained_advice_count += len(response.advice)
                states.append(ChangeReviewState.PARTIAL)
            else:
                states.append(ChangeReviewState.INSUFFICIENT)
        if len(roots) > request.architecture_subject_limit:
            limitations.add(
                "Architecture review subjects were deterministically bounded."
            )
        if retained_advice_count >= request.architecture_advice_limit:
            limitations.add(
                "Architecture advice reached its deterministic global result bound; additional compatible advice may exist."
            )
        return tuple(retained), tuple(states), tuple(sorted(limitations))

    def _sections(
        self,
        alignment: SnapshotAlignmentState,
        diff: ChangeReviewDiff,
        files: tuple[ChangedFileReview, ...],
        roots: tuple[SubjectCandidate, ...],
        architecture_roots: tuple[SubjectCandidate, ...],
        impact: ImpactPredictionResponse | None,
        architecture: tuple[RefactoringResponse, ...],
        architecture_states: tuple[ChangeReviewState, ...],
        architecture_limitations: tuple[str, ...],
        git_evidence_ids: tuple[str, ...],
        association_evidence_ids: tuple[str, ...],
        request: ChangeReviewRequest,
    ) -> tuple[ChangeReviewSection, ...]:
        git_limitations = [_UNTRACKED_LIMITATION]
        if diff.omitted_file_count:
            git_limitations.append(
                "Changed files were deterministically truncated before semantic review."
            )
        git_state = (
            ChangeReviewState.PARTIAL
            if diff.omitted_file_count else ChangeReviewState.AVAILABLE
        )
        alignment_state, alignment_limitations = self._alignment_section(alignment)
        mapping_ids = tuple(sorted({
            candidate.canonical_id
            for item in files
            for candidate in item.subjects
        }))
        mapping_state, mapping_limitations = self._mapping_section(
            alignment, files, roots
        )
        impact_section = self._impact_section(alignment, roots, impact)
        tests_section = self._tests_section(alignment, impact)
        risk_section = self._risk_section(alignment, impact)
        architecture_section, migration_section = self._architecture_sections(
            alignment,
            architecture_roots,
            architecture,
            architecture_states,
            architecture_limitations,
            request,
        )
        return tuple(sorted((
            ChangeReviewSection(
                "git_diff", git_state,
                tuple(item.path for item in files), git_evidence_ids,
                tuple(git_limitations),
            ),
            ChangeReviewSection(
                "snapshot_alignment", alignment_state, (), (), alignment_limitations,
            ),
            ChangeReviewSection(
                "subject_mapping", mapping_state, mapping_ids,
                association_evidence_ids, mapping_limitations,
            ),
            impact_section,
            architecture_section,
            tests_section,
            risk_section,
            migration_section,
        ), key=lambda item: item.name))

    @staticmethod
    def _alignment_section(
        alignment: SnapshotAlignmentState,
    ) -> tuple[ChangeReviewState, tuple[str, ...]]:
        if alignment is SnapshotAlignmentState.CURRENT:
            return ChangeReviewState.AVAILABLE, ()
        if alignment is SnapshotAlignmentState.ASSUMED_CURRENT:
            return ChangeReviewState.PARTIAL, (
                "Snapshot currency was explicitly assumed and not independently verified.",
            )
        if alignment is SnapshotAlignmentState.STALE:
            return ChangeReviewState.STALE, (
                "Current workspace content differs from the semantic snapshot fingerprint.",
            )
        return ChangeReviewState.UNAVAILABLE, (
            "No current workspace fingerprint was supplied and currency was not assumed.",
        )

    def _mapping_section(
        self,
        alignment: SnapshotAlignmentState,
        files: tuple[ChangedFileReview, ...],
        roots: tuple[SubjectCandidate, ...],
    ) -> tuple[ChangeReviewState, tuple[str, ...]]:
        if alignment is SnapshotAlignmentState.STALE:
            return ChangeReviewState.STALE, (
                "Stale snapshot subjects were not associated with current changes.",
            )
        if alignment is SnapshotAlignmentState.UNKNOWN:
            return ChangeReviewState.UNAVAILABLE, (
                "Snapshot currency is unknown; exact subject association was disabled.",
            )
        if self._resolver.graph is None:
            return ChangeReviewState.UNAVAILABLE, (
                "The canonical PR129 graph is unavailable or incompatible.",
            )
        semantic_files = tuple(
            item for item in files
            if not item.binary and item.status is not ChangedFileStatus.DELETED
        )
        limitations = {_FILE_ASSOCIATION_LIMITATION}
        if any(not item.subjects or item.project_fallback for item in semantic_files):
            limitations.add(
                "Some changed paths had no exact canonical subject association."
            )
        if any(item.omitted_subject_count for item in files):
            limitations.add("Some file-associated subjects were omitted by bounds.")
        if not roots:
            limitations.add(
                "No exact changed-path subject was available for downstream analysis."
            )
            return ChangeReviewState.INSUFFICIENT, tuple(sorted(limitations))
        return ChangeReviewState.PARTIAL, tuple(sorted(limitations))

    @staticmethod
    def _impact_section(
        alignment: SnapshotAlignmentState,
        roots: tuple[SubjectCandidate, ...],
        impact: ImpactPredictionResponse | None,
    ) -> ChangeReviewSection:
        if alignment is SnapshotAlignmentState.STALE:
            return ChangeReviewSection("impact", ChangeReviewState.STALE, limitations=(
                "Impact was not evaluated against stale semantic identity.",
            ))
        if alignment is SnapshotAlignmentState.UNKNOWN:
            return ChangeReviewSection("impact", ChangeReviewState.UNAVAILABLE, limitations=(
                "Impact requires a current or explicitly assumed-current snapshot.",
            ))
        if not roots or impact is None:
            return ChangeReviewSection("impact", ChangeReviewState.INSUFFICIENT, limitations=(
                "No exact current-snapshot subject was available as an impact root.",
            ))
        evidence_ids = tuple(item.evidence_id for item in impact.evidence_index.records)
        if impact.findings:
            return ChangeReviewSection(
                "impact", ChangeReviewState.PARTIAL,
                tuple(item.subject.canonical_id for item in impact.findings),
                evidence_ids,
                tuple(sorted({
                    *impact.limitations,
                    "Impact is limited to authoritative relationships represented in the current canonical graph.",
                })),
            )
        return ChangeReviewSection(
            "impact", ChangeReviewState.INSUFFICIENT, (), evidence_ids,
            tuple(sorted({
                *impact.limitations,
                "No represented in-repository impact was proven; external and unrepresented consumers remain possible.",
            })),
        )

    @staticmethod
    def _tests_section(
        alignment: SnapshotAlignmentState,
        impact: ImpactPredictionResponse | None,
    ) -> ChangeReviewSection:
        if alignment is SnapshotAlignmentState.STALE:
            return ChangeReviewSection("tests", ChangeReviewState.STALE, limitations=(
                "Targeted tests were not selected from stale semantic evidence.",
            ))
        if impact is None:
            return ChangeReviewSection("tests", ChangeReviewState.UNAVAILABLE, limitations=(
                "Targeted test selection requires exact subjects and compatible PR131/PR136 evidence.",
                _NO_NEGATIVE_TEST_CLAIM,
            ))
        tests = tuple(
            item for item in impact.findings if item.category is ImpactCategory.TEST
        )
        evidence_ids = tuple(sorted({
            evidence_id for item in tests for evidence_id in item.evidence_ids
        }))
        capability = next((item for item in impact.capabilities if item.name == "tests"), None)
        if tests:
            return ChangeReviewSection(
                "tests", ChangeReviewState.PARTIAL,
                tuple(item.subject.canonical_id for item in tests), evidence_ids,
                tuple(sorted({
                    *(capability.limitations if capability is not None else ()),
                    "Recommendations cover only tests linked by compatible structured evidence.",
                })),
            )
        state = _state_from_impact_capability(capability)
        if state is ChangeReviewState.AVAILABLE:
            state = ChangeReviewState.INSUFFICIENT
        return ChangeReviewSection(
            "tests", state, (), (),
            tuple(sorted({
                *(capability.limitations if capability is not None else ()),
                _NO_NEGATIVE_TEST_CLAIM,
            })),
        )

    @staticmethod
    def _risk_section(
        alignment: SnapshotAlignmentState,
        impact: ImpactPredictionResponse | None,
    ) -> ChangeReviewSection:
        if alignment is SnapshotAlignmentState.STALE:
            return ChangeReviewSection("risk", ChangeReviewState.STALE, limitations=(
                "Current-snapshot risk was not attached to a stale change scope.",
            ))
        if impact is None:
            return ChangeReviewSection("risk", ChangeReviewState.UNAVAILABLE, limitations=(
                "Risk requires compatible PR132 evidence attached to an exact subject or proven impact.",
            ))
        findings = tuple(item for item in impact.findings if item.risk_context is not None)
        evidence_ids = tuple(sorted({
            evidence_id
            for item in findings
            if item.risk_context is not None
            for evidence_id in item.risk_context.evidence_ids
        }))
        capability = next((item for item in impact.capabilities if item.name == "risk"), None)
        if findings:
            return ChangeReviewSection(
                "risk", ChangeReviewState.PARTIAL,
                tuple(item.subject.canonical_id for item in findings), evidence_ids,
                (
                    "Risk values are existing PR132 current-snapshot context; the diff is not claimed to have introduced them.",
                ),
            )
        state = _state_from_impact_capability(capability)
        if state is ChangeReviewState.AVAILABLE:
            state = ChangeReviewState.INSUFFICIENT
        return ChangeReviewSection(
            "risk", state, (), (),
            tuple(sorted({
                *(capability.limitations if capability is not None else ()),
                "No compatible risk context was attached; absence is not evidence of low risk.",
            })),
        )

    @staticmethod
    def _architecture_sections(
        alignment: SnapshotAlignmentState,
        roots: tuple[SubjectCandidate, ...],
        responses: tuple[RefactoringResponse, ...],
        states: tuple[ChangeReviewState, ...],
        limitations: tuple[str, ...],
        request: ChangeReviewRequest,
    ) -> tuple[ChangeReviewSection, ChangeReviewSection]:
        if not request.include_architecture:
            architecture = ChangeReviewSection(
                "architecture", ChangeReviewState.NOT_REQUESTED,
                limitations=("Architecture review was not requested.",),
            )
            migration = ChangeReviewSection(
                "migration", ChangeReviewState.NOT_REQUESTED,
                limitations=("Migration context was not requested with architecture review.",),
            )
            return architecture, migration
        if alignment is SnapshotAlignmentState.STALE:
            return (
                ChangeReviewSection("architecture", ChangeReviewState.STALE, limitations=(
                    "Architecture context was not evaluated against stale semantic evidence.",
                )),
                ChangeReviewSection("migration", ChangeReviewState.STALE, limitations=(
                    "Migration context was not evaluated against stale semantic evidence.",
                )),
            )
        if alignment is SnapshotAlignmentState.UNKNOWN:
            return (
                ChangeReviewSection("architecture", ChangeReviewState.UNAVAILABLE, limitations=(
                    "Architecture context requires a current or explicitly assumed-current snapshot.",
                )),
                ChangeReviewSection("migration", ChangeReviewState.UNAVAILABLE, limitations=(
                    "Migration context requires a current or explicitly assumed-current snapshot.",
                )),
            )
        if not roots:
            return (
                ChangeReviewSection("architecture", ChangeReviewState.INSUFFICIENT, limitations=(
                    "No exact changed subject was available for architecture scope intersection.",
                )),
                ChangeReviewSection("migration", ChangeReviewState.UNSUPPORTED, limitations=(
                    "General migration planning is unsupported without verified PR137 cycle-seam evidence.",
                )),
            )
        advice = tuple(item for response in responses for item in response.advice)
        evidence_ids = tuple(sorted({
            record.evidence_id
            for response in responses
            for record in response.evidence_index.records
        }))
        if advice:
            common_limitations = tuple(sorted({
                *limitations,
                "These are existing fully revalidated dependency-cycle seams in the analyzed snapshot; the diff is not claimed to have introduced them.",
            }))
            ids = tuple(item.advice_id for item in advice)
            return (
                ChangeReviewSection(
                    "architecture", ChangeReviewState.PARTIAL,
                    ids, evidence_ids, common_limitations,
                ),
                ChangeReviewSection(
                    "migration", ChangeReviewState.PARTIAL,
                    ids, evidence_ids,
                    tuple(sorted({
                        *common_limitations,
                        "Only PR137 evidence-backed preconditions and verification steps are available; no general migration plan was generated.",
                    })),
                ),
            )
        architecture_state = (
            ChangeReviewState.INSUFFICIENT
            if states else ChangeReviewState.UNAVAILABLE
        )
        return (
            ChangeReviewSection(
                "architecture", architecture_state, limitations=tuple(sorted({
                    *limitations,
                    "No fully revalidated PR137 cycle seam intersected the exact changed scope; no clean-architecture claim is implied.",
                })),
            ),
            ChangeReviewSection(
                "migration", ChangeReviewState.UNSUPPORTED, limitations=(
                    "General migration planning is unsupported without verified cycle-seam or semantic before/after evidence.",
                ),
            ),
        )


def _state_from_impact_capability(capability: object) -> ChangeReviewState:
    state = getattr(capability, "state", None)
    return {
        ImpactCapabilityState.AVAILABLE: ChangeReviewState.AVAILABLE,
        ImpactCapabilityState.PARTIAL: ChangeReviewState.PARTIAL,
        ImpactCapabilityState.UNAVAILABLE: ChangeReviewState.UNAVAILABLE,
        ImpactCapabilityState.INCOMPATIBLE: ChangeReviewState.INCOMPATIBLE,
        ImpactCapabilityState.UNSUPPORTED: ChangeReviewState.UNSUPPORTED,
    }.get(state, ChangeReviewState.UNAVAILABLE)
