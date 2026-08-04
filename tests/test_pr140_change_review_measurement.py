from __future__ import annotations

import json

from moughorai.change_review import (
    ChangeReviewRequest,
    ChangeReviewService,
)
from moughorai.git_diff import DiffFile, GitDiff
from moughorai.measurement import (
    MeasurementConfig,
    MeasurementSession,
    MetricStatus,
)

from test_pr140_change_review import _snapshot


_WORKSPACE_FINGERPRINT = "pr140-workspace"
_EXPECTED_PHASES = {
    "change_review.resolver_index",
    "change_review.path_association",
    "change_review.materialize",
}


def _measurement_session() -> MeasurementSession:
    return MeasurementSession(MeasurementConfig(
        enabled=True,
        capture_process_cpu=False,
        capture_thread_cpu=False,
        capture_process_memory=False,
        capture_python_memory=False,
        capture_filesystem=False,
    ))


def _cohort_diff(file_count: int, *, reverse: bool = False) -> GitDiff:
    files = tuple(
        DiffFile(path, path)
        for path in (
            f"cohort/File{index:03d}.java" for index in range(file_count)
        )
    )
    return GitDiff(tuple(reversed(files)) if reverse else files)


def _request() -> ChangeReviewRequest:
    return ChangeReviewRequest(
        maximum_files=256,
        maximum_subjects_per_file=1,
        maximum_subjects=128,
        include_architecture=False,
    )


def _review_cohort(file_count: int, *, reverse: bool = False):
    snapshot = _snapshot()
    session = _measurement_session()
    response = ChangeReviewService.from_snapshot(
        snapshot, measurement=session,
    ).review(
        _cohort_diff(file_count, reverse=reverse),
        _request(),
        current_workspace_fingerprint=_WORKSPACE_FINGERPRINT,
    )
    return snapshot, response, session.report()


def test_change_review_records_expected_measurement_phases_and_work_units() -> None:
    _snapshot_value, response, report = _review_cohort(25)
    by_phase = {sample.phase_id: sample for sample in report.samples}

    assert set(by_phase) == _EXPECTED_PHASES
    assert all(sample.succeeded for sample in report.samples)
    assert all(sample.consumer == "change-review" for sample in report.samples)

    resolver_units = by_phase["change_review.resolver_index"].metric(
        "units_processed"
    )
    association_units = by_phase["change_review.path_association"].metric(
        "units_processed"
    )
    materialize_units = by_phase["change_review.materialize"].metric(
        "units_processed"
    )
    assert resolver_units.status is MetricStatus.MEASURED
    assert resolver_units.value == 5  # Four canonical nodes and one edge.
    assert association_units.status is MetricStatus.MEASURED
    assert association_units.value == 50  # One file plus one project fallback each.
    assert materialize_units.status is MetricStatus.MEASURED
    assert materialize_units.value == 33  # Twenty-five files plus eight sections.
    assert "wall_time_ns" not in response.to_json()


def test_change_review_is_ephemeral_and_never_mutates_or_grows_the_snapshot() -> None:
    snapshot = _snapshot()
    before = json.dumps(
        snapshot.to_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    before_id = snapshot.snapshot_id
    before_context_keys = tuple(sorted(snapshot.semantic_context))

    service = ChangeReviewService.from_snapshot(snapshot)
    first = service.review(
        _cohort_diff(25),
        _request(),
        current_workspace_fingerprint=_WORKSPACE_FINGERPRINT,
    )
    second = service.review(
        _cohort_diff(25, reverse=True),
        _request(),
        current_workspace_fingerprint=_WORKSPACE_FINGERPRINT,
    )
    after = json.dumps(
        snapshot.to_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert first.to_json() == second.to_json()
    assert first.lineage == before_id
    assert snapshot.snapshot_id == before_id
    assert tuple(sorted(snapshot.semantic_context)) == before_context_keys
    assert after == before
    assert len(after) == len(before)
    assert "change_review" not in snapshot.semantic_context


def test_controlled_cohorts_have_deterministic_linear_response_bounds() -> None:
    sizes: dict[int, int] = {}
    snapshot_bytes: dict[int, bytes] = {}

    for file_count in (0, 1, 25, 250):
        snapshot, response, report = _review_cohort(file_count)
        serialized = response.to_json().encode("utf-8")
        sizes[file_count] = len(serialized)
        snapshot_bytes[file_count] = json.dumps(
            snapshot.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

        expected_returned = min(file_count, 128)
        assert response.diff.total_file_count == file_count
        assert response.diff.selected_file_count == file_count
        assert response.total_subject_count == file_count
        assert sum(len(item.subjects) for item in response.changed_files) == (
            expected_returned
        )
        assert response.omitted_subject_count == file_count - expected_returned
        assert len(response.evidence_index.records) == (
            (2 * file_count) + expected_returned
        )
        assert {sample.phase_id for sample in report.samples} == _EXPECTED_PHASES

        _snapshot_again, reordered, _report_again = _review_cohort(
            file_count, reverse=True
        )
        assert response.to_json() == reordered.to_json()

    baseline_size = sizes[0]
    assert sizes[0] < sizes[1] < sizes[25] < sizes[250]
    for file_count in (1, 25, 250):
        assert sizes[file_count] <= baseline_size + (file_count * 8_192)
    assert len(set(snapshot_bytes.values())) == 1
