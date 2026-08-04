from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import socket
import subprocess
import urllib.request

import pytest

from moughorai.change_review import (
    ChangeReviewRequest,
    ChangeReviewResponse,
    ChangeReviewService,
    ChangeReviewState,
    SnapshotAlignmentState,
    render_change_review,
)
from moughorai.git_diff import DiffFile, GitDiff
from moughorai.impact_analysis import ImpactPredictionService
from moughorai.java_llm_provider import JavaLlmProviderService
from moughorai.llm import LlmClient
from moughorai.refactoring_advisor import RefactoringAdvisorService
from moughorai.refactoring_advisor import (
    RefactoringFamily,
    RefactoringRequest,
)
from moughorai.semantic_evidence import EvidenceKind, EvidenceRecord
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import (
    CanonicalSubjectResolver,
    PathSubjectCandidates,
    SubjectQuery,
)
from moughorai.ai_context import WorkspaceSemanticContext

from test_pr140_change_review import _cycle_snapshot, _diff, _review, _snapshot


def test_nested_tampering_and_dangling_or_unused_evidence_are_rejected() -> None:
    response = _review()
    payload = response.to_dict()

    unknown_request = deepcopy(payload)
    unknown_request["request"]["unexpected"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="unknown change review request"):
        ChangeReviewResponse.from_dict(unknown_request)

    changed_file_dangling = deepcopy(payload)
    changed_file_dangling["changed_files"][0]["evidence_ids"].append(  # type: ignore[index,union-attr]
        f"evidence:{'0' * 64}"
    )
    with pytest.raises(ValueError, match="dangling evidence"):
        ChangeReviewResponse.from_dict(changed_file_dangling)

    identity_tampering = deepcopy(payload)
    identity_tampering["evidence_index"]["records"][0]["detail"][  # type: ignore[index]
        "status"
    ] = "tampered"
    with pytest.raises(ValueError, match="evidence identity"):
        ChangeReviewResponse.from_dict(identity_tampering)

    unused_record = EvidenceRecord.create(
        EvidenceKind.SEMANTIC_FACT,
        "type:unused",
        "atlas-pr140-test/1",
        response.lineage,
        detail={"fact": "unused"},
    )
    unused_evidence = deepcopy(payload)
    unused_evidence["evidence_index"]["records"].append(  # type: ignore[index,union-attr]
        unused_record.to_dict()
    )
    with pytest.raises(ValueError, match="unused feature evidence"):
        ChangeReviewResponse.from_dict(unused_evidence)


def test_private_paths_and_retained_source_flags_are_rejected() -> None:
    payload = _review().to_dict()

    private_path = deepcopy(payload)
    private_path["changed_files"][0][  # type: ignore[index]
        "path"
    ] = r"C:\Users\private\Secret.java"
    with pytest.raises(ValueError, match="workspace-relative|absolute paths"):
        ChangeReviewResponse.from_dict(private_path)

    retained_source = deepcopy(payload)
    retained_source["diff"]["source_content_retained"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="exclude.*source content"):
        ChangeReviewResponse.from_dict(retained_source)

    source_shaped = deepcopy(payload)
    source_shaped["limitations"].append(  # type: ignore[union-attr]
        'public class Secret { String password="topsecret"; }'
    )
    with pytest.raises(ValueError, match="source-free|private-data-free"):
        ChangeReviewResponse.from_dict(source_shaped)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            "changed_file_path",
            "changed file status and paths|Git evidence projection",
        ),
        ("section_state", "impact projection"),
        ("section_items", "impact projection"),
        ("diff_workspace_prefix", "fingerprint"),
        ("semantic_confidence", "semantic confidence"),
        (
            "candidate_source_refs",
            "exact path provenance|subject evidence projection",
        ),
        ("escape_control", "one-line"),
    ),
)
def test_round_trip_rejects_semantically_tampered_feature_projections(
    mutation: str,
    message: str,
) -> None:
    payload = deepcopy(_review().to_dict())
    changed_file = payload["changed_files"][0]  # type: ignore[index]
    impact = next(
        item
        for item in payload["sections"]  # type: ignore[union-attr]
        if item["name"] == "impact"
    )

    if mutation == "changed_file_path":
        changed_file["path"] = "safe/Forged.java"
    elif mutation == "section_state":
        impact["state"] = "available"
    elif mutation == "section_items":
        impact["item_ids"] = ["type:forged"]
    elif mutation == "diff_workspace_prefix":
        payload["diff"]["workspace_prefix"] = "forged-prefix"  # type: ignore[index]
    elif mutation == "semantic_confidence":
        changed_file["semantic_confidence"]["score"] = 0.8
        changed_file["semantic_confidence"]["support"] = 0.8
    elif mutation == "candidate_source_refs":
        changed_file["candidate_evidence"][0]["source_refs"] = [
            "knowledge_node.metadata:path"
        ]
    else:
        changed_file["path"] = "safe/\x1b[31mForged.java"

    with pytest.raises(ValueError, match=message):
        ChangeReviewResponse.from_dict(payload)


def test_renderer_escapes_control_bytes_from_validated_nested_upstream_text() -> None:
    snapshot = _cycle_snapshot()
    response = _review(
        snapshot=snapshot,
        diff=GitDiff((DiffFile("alpha/pom.xml", "alpha/pom.xml"),)),
        fingerprint="cycle-workspace",
    )
    architecture = response.architecture_reviews[0]
    unsafe_advice = replace(
        architecture.advice[0],
        rationale="Validated upstream rationale\x1b[31mred",
    )
    unsafe_architecture = replace(
        architecture,
        advice=(unsafe_advice, *architecture.advice[1:]),
    )
    nested_response = replace(
        response,
        architecture_reviews=(unsafe_architecture,),
    )

    rendered = render_change_review(nested_response)

    assert "\x1b" not in rendered
    assert r"\u001b[31m" in rendered


@pytest.mark.parametrize(
    ("fingerprint", "expected_alignment", "expected_impact_state"),
    [
        (
            None,
            SnapshotAlignmentState.UNKNOWN,
            ChangeReviewState.UNAVAILABLE,
        ),
        (
            "different-workspace",
            SnapshotAlignmentState.STALE,
            ChangeReviewState.STALE,
        ),
    ],
)
def test_unknown_and_stale_alignment_never_invoke_semantic_advisors(
    monkeypatch: pytest.MonkeyPatch,
    fingerprint: str | None,
    expected_alignment: SnapshotAlignmentState,
    expected_impact_state: ChangeReviewState,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("stale or unknown review invoked a semantic advisor")

    monkeypatch.setattr(ImpactPredictionService, "predict", forbidden)
    monkeypatch.setattr(RefactoringAdvisorService, "advise", forbidden)

    response = _review(fingerprint=fingerprint)

    assert response.alignment is expected_alignment
    assert response.impact is None
    assert response.architecture_reviews == ()
    assert all(not item.subjects for item in response.changed_files)
    assert response.section("impact").state is expected_impact_state


def test_change_review_service_performs_no_provider_network_or_subprocess_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("ChangeReviewService attempted external execution or I/O")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(LlmClient, "complete", forbidden)
    monkeypatch.setattr(JavaLlmProviderService, "execute", forbidden)

    response = ChangeReviewService.from_snapshot(_snapshot()).review(
        _diff(),
        ChangeReviewRequest(include_architecture=False),
        current_workspace_fingerprint="pr140-workspace",
    )

    assert response.alignment is SnapshotAlignmentState.CURRENT
    assert response.changed_files


def test_large_reordered_inputs_apply_identical_deterministic_bounds() -> None:
    files = tuple(
        DiffFile(path, path)
        for path in (f"generated/File{index:03d}.java" for index in range(300))
    )
    request = ChangeReviewRequest(
        maximum_files=25,
        maximum_subjects_per_file=1,
        maximum_subjects=7,
        include_architecture=False,
    )
    first = _review(diff=GitDiff(files), request=request)
    second = _review(diff=GitDiff(tuple(reversed(files))), request=request)

    assert first.to_json() == second.to_json()
    assert first.diff.total_file_count == 300
    assert first.diff.selected_file_count == 25
    assert first.diff.omitted_file_count == 275
    assert first.total_subject_count == 25
    assert sum(len(item.subjects) for item in first.changed_files) == 7
    assert first.omitted_subject_count == 18
    assert all(item.project_fallback for item in first.changed_files[:7])
    assert "deterministic bounds" in " ".join(first.limitations)


@pytest.mark.parametrize("file_count", (512, 513, 1000))
def test_requested_file_bounds_are_serializable_at_and_above_legacy_array_limit(
    file_count: int,
) -> None:
    files = tuple(
        DiffFile(path, path)
        for path in (
            f"boundary/File{index:04d}.java" for index in range(file_count)
        )
    )
    request = ChangeReviewRequest(
        maximum_files=file_count,
        maximum_subjects_per_file=1,
        maximum_subjects=1,
        include_architecture=False,
    )

    first = _review(diff=GitDiff(files), request=request)
    second = _review(diff=GitDiff(tuple(reversed(files))), request=request)

    assert first.to_json() == second.to_json()
    assert first.diff.total_file_count == file_count
    assert first.diff.selected_file_count == file_count
    assert first.diff.omitted_file_count == 0
    assert len(first.changed_files) == file_count
    assert len(first.section("git_diff").item_ids) == file_count
    assert len(first.section("git_diff").evidence_ids) == file_count
    assert ChangeReviewResponse.from_dict(first.to_dict()).to_dict() == first.to_dict()


def test_unrelated_same_lineage_pr137_response_cannot_be_substituted() -> None:
    snapshot = _cycle_snapshot()
    response = _review(
        snapshot=snapshot,
        diff=GitDiff((DiffFile("alpha/pom.xml", "alpha/pom.xml"),)),
        fingerprint="cycle-workspace",
    )
    unrelated = RefactoringAdvisorService.from_snapshot(snapshot).advise(
        RefactoringRequest(
            SubjectQuery("project:gamma"),
            (RefactoringFamily.CYCLE_BREAKING,),
            8,
            False,
            4,
        )
    )

    with pytest.raises(ValueError, match="architecture request"):
        replace(response, architecture_reviews=(unrelated,))


@pytest.mark.parametrize("target", ("section", "response"))
def test_replay_rejects_replaced_limitations(target: str) -> None:
    payload = deepcopy(_review().to_dict())
    if target == "section":
        section = next(
            item
            for item in payload["sections"]  # type: ignore[union-attr]
            if item["name"] == "impact"
        )
        section["limitations"] = ["Forged but syntactically valid limitation."]
        message = "impact projection"
    else:
        payload["limitations"] = [
            "Forged but syntactically valid response limitation."
        ]
        message = "response limitations"

    with pytest.raises(ValueError, match=message):
        ChangeReviewResponse.from_dict(payload)


def test_current_alignment_requires_equal_workspace_fingerprints_on_replay() -> None:
    payload = deepcopy(_review().to_dict())
    payload["current_workspace_fingerprint"] = "different-workspace"

    with pytest.raises(ValueError, match="snapshot alignment"):
        ChangeReviewResponse.from_dict(payload)


def _multi_subject_snapshot() -> AtlasSemanticSnapshot:
    base = _snapshot()
    context = dict(base.semantic_context)
    symbols = [dict(item) for item in context["symbols"]]
    next(item for item in symbols if item["id"] == "type:consumer")[
        "source"
    ] = "src/Api.java"
    context["symbols"] = symbols
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(context),
        workspace_fingerprint="pr140-workspace",
        analyzer_version="test-pr140/1",
    )


def test_replay_enforces_outer_file_and_subject_bounds() -> None:
    response_payload = deepcopy(_review().to_dict())
    too_many_files = deepcopy(response_payload)
    too_many_files["request"]["maximum_files"] = 1  # type: ignore[index]
    with pytest.raises(ValueError, match="too many|request bound"):
        ChangeReviewResponse.from_dict(too_many_files)

    too_many_subjects = deepcopy(response_payload)
    too_many_subjects["request"]["maximum_subjects"] = 1  # type: ignore[index]
    with pytest.raises(ValueError, match="subjects exceed the request bound"):
        ChangeReviewResponse.from_dict(too_many_subjects)

    multi_subject = _review(
        snapshot=_multi_subject_snapshot(),
        diff=GitDiff((DiffFile("src/Api.java", "src/Api.java"),)),
        request=ChangeReviewRequest(
            maximum_subjects_per_file=2,
            maximum_subjects=2,
        ),
    ).to_dict()
    multi_subject["request"]["maximum_subjects_per_file"] = 1  # type: ignore[index]
    with pytest.raises(ValueError, match="per-file request bound"):
        ChangeReviewResponse.from_dict(multi_subject)


def test_replay_enforces_nested_impact_and_architecture_bounds() -> None:
    impact_payload = deepcopy(_review().to_dict())
    impact_payload["request"]["impact_limit"] = 1  # type: ignore[index]
    with pytest.raises(ValueError, match="impact request"):
        ChangeReviewResponse.from_dict(impact_payload)

    snapshot = _cycle_snapshot()
    architecture_payload = _review(
        snapshot=snapshot,
        diff=GitDiff((DiffFile("alpha/pom.xml", "alpha/pom.xml"),)),
        fingerprint="cycle-workspace",
    ).to_dict()
    architecture_payload["request"]["architecture_advice_limit"] = 1  # type: ignore[index]
    with pytest.raises(ValueError, match="architecture request|advice exceeds"):
        ChangeReviewResponse.from_dict(architecture_payload)


def test_drive_relative_paths_are_rejected_by_every_pr140_path_adapter() -> None:
    with pytest.raises(ValueError, match="safe workspace-relative"):
        DiffFile(None, "C:private/Main.java")

    resolver = CanonicalSubjectResolver.from_snapshot(_snapshot())
    with pytest.raises(ValueError, match="workspace-relative"):
        resolver.candidates_for_path("C:private/Main.java")

    payload = deepcopy(_review().to_dict())
    payload["changed_files"][0]["path"] = "C:private/Main.java"  # type: ignore[index]
    with pytest.raises(ValueError, match="workspace-relative"):
        ChangeReviewResponse.from_dict(payload)


def test_duplicate_path_candidate_evidence_is_rejected_at_both_boundaries() -> None:
    resolver = CanonicalSubjectResolver.from_snapshot(_snapshot())
    candidates_payload = resolver.candidates_for_path("src/Api.java").to_dict()
    duplicate = deepcopy(candidates_payload["candidate_evidence"][0])  # type: ignore[index]
    candidates_payload["candidate_evidence"].append(duplicate)  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="candidate evidence IDs must be unique"):
        PathSubjectCandidates.from_dict(candidates_payload)

    response_payload = deepcopy(_review().to_dict())
    duplicate = deepcopy(
        response_payload["changed_files"][0]["candidate_evidence"][0]  # type: ignore[index]
    )
    response_payload["changed_files"][0]["candidate_evidence"].append(  # type: ignore[index,union-attr]
        duplicate
    )
    with pytest.raises(ValueError, match="candidate evidence IDs must be unique"):
        ChangeReviewResponse.from_dict(response_payload)
