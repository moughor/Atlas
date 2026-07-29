from __future__ import annotations

import json
from pathlib import Path

import pytest

from moughorai.incremental_analysis import (
    CheckpointEntry,
    CheckpointFormatError,
    ExecutionCheckpoint,
    FileFingerprint,
    IncrementalAnalysisEngine,
    IncrementalCache,
    ResilientParallelScheduler,
    RetryPolicy,
)


def fp(name: str, digit: str = "a") -> FileFingerprint:
    return FileFingerprint(Path(name), 1, digit * 64)


def test_retry_policy_validates_attempts():
    with pytest.raises(ValueError, match="at least one"):
        RetryPolicy(max_attempts=0)


def test_retry_policy_validates_backoff():
    with pytest.raises(ValueError, match="negative"):
        RetryPolicy(backoff_seconds=-1)


def test_retry_policy_requires_exception_types():
    with pytest.raises(TypeError):
        RetryPolicy(retryable=("ValueError",))  # type: ignore[arg-type]


def test_default_policy_does_not_retry():
    scheduler = ResilientParallelScheduler()
    calls = []
    run = scheduler.run((fp("a.java"),), lambda path: calls.append(path) or (_ for _ in ()).throw(ValueError("bad")))
    assert len(calls) == 1
    assert run.retry_count == 0


def test_retry_eventually_succeeds():
    calls = {"count": 0}
    scheduler = ResilientParallelScheduler(retry_policy=RetryPolicy(max_attempts=3))
    def analyzer(path):
        calls["count"] += 1
        if calls["count"] < 3:
            raise ValueError("temporary")
        return "ok"
    run = scheduler.run((fp("a.java"),), analyzer)
    assert run.succeeded
    assert run.result_map()[Path("a.java")] == "ok"
    assert [record.succeeded for record in run.attempts] == [False, False, True]
    assert run.retry_count == 2


def test_non_retryable_error_stops_immediately():
    scheduler = ResilientParallelScheduler(retry_policy=RetryPolicy(max_attempts=4, retryable=(ValueError,)))
    run = scheduler.run((fp("a.java"),), lambda path: (_ for _ in ()).throw(TypeError("fatal")))
    assert len(run.attempts) == 1
    assert run.failures[0].error_type == "TypeError"


def test_retry_exhaustion_reports_last_error():
    scheduler = ResilientParallelScheduler(retry_policy=RetryPolicy(max_attempts=2))
    run = scheduler.run((fp("a.java"),), lambda path: (_ for _ in ()).throw(RuntimeError("still bad")))
    assert len(run.attempts) == 2
    assert run.failures[0].message == "still bad"


def test_successful_result_is_cached_after_retry():
    cache = IncrementalCache()
    scheduler = ResilientParallelScheduler(IncrementalAnalysisEngine(cache), retry_policy=RetryPolicy(max_attempts=2))
    calls = [0]
    def analyzer(path):
        calls[0] += 1
        if calls[0] == 1:
            raise ValueError()
        return 7
    scheduler.run((fp("a.java"),), analyzer)
    assert cache.get("a.java", "a" * 64) == 7


def test_failed_result_is_not_cached():
    cache = IncrementalCache()
    scheduler = ResilientParallelScheduler(IncrementalAnalysisEngine(cache), retry_policy=RetryPolicy(max_attempts=2))
    scheduler.run((fp("a.java"),), lambda path: (_ for _ in ()).throw(ValueError()))
    assert cache.entries == ()


def test_checkpoint_round_trip(tmp_path):
    checkpoint = ExecutionCheckpoint((CheckpointEntry(Path("a.java"), "a" * 64, {"x": 1}),))
    path = tmp_path / "checkpoint.json"
    checkpoint.save(path)
    loaded = ExecutionCheckpoint.load(path)
    assert loaded.entries == checkpoint.entries
    assert path.read_text().endswith("\n")


def test_checkpoint_serialization_is_deterministic():
    a = CheckpointEntry(Path("a.java"), "a" * 64, 1)
    b = CheckpointEntry(Path("b.java"), "b" * 64, 2)
    assert ExecutionCheckpoint((b, a)).to_json() == ExecutionCheckpoint((a, b)).to_json()


def test_checkpoint_missing_file_loads_empty(tmp_path):
    assert ExecutionCheckpoint.load(tmp_path / "missing.json").entries == ()


def test_checkpoint_rejects_wrong_schema():
    with pytest.raises(CheckpointFormatError, match="schema"):
        ExecutionCheckpoint.from_dict({"schema_version": 999, "entries": []})


def test_checkpoint_rejects_non_list_entries():
    with pytest.raises(CheckpointFormatError, match="list"):
        ExecutionCheckpoint.from_dict({"schema_version": 1, "entries": {}})


def test_checkpoint_rejects_duplicate_paths():
    value = {"schema_version": 1, "entries": [
        {"path": "a.java", "fingerprint": "a" * 64, "result": 1},
        {"path": "a.java", "fingerprint": "b" * 64, "result": 2},
    ]}
    with pytest.raises(CheckpointFormatError, match="duplicate"):
        ExecutionCheckpoint.from_dict(value)


def test_checkpoint_rejects_bad_digest():
    with pytest.raises(CheckpointFormatError):
        ExecutionCheckpoint.from_dict({"schema_version": 1, "entries": [{"path": "a", "fingerprint": "bad"}]})


def test_checkpoint_corruption_can_recover(tmp_path):
    path = tmp_path / "checkpoint.json"
    path.write_text("not json")
    assert ExecutionCheckpoint.load(path, recover=True).entries == ()


def test_checkpoint_corruption_raises_by_default(tmp_path):
    path = tmp_path / "checkpoint.json"
    path.write_text("not json")
    with pytest.raises(CheckpointFormatError):
        ExecutionCheckpoint.load(path)


def test_run_writes_checkpoint(tmp_path):
    path = tmp_path / "checkpoint.json"
    run = ResilientParallelScheduler().run((fp("a.java"),), lambda p: {"name": p.name}, checkpoint_path=path)
    assert run.analyzed == (Path("a.java"),)
    assert ExecutionCheckpoint.load(path).get(Path("a.java"), "a" * 64) == {"name": "a.java"}


def test_second_run_resumes_from_checkpoint(tmp_path):
    path = tmp_path / "checkpoint.json"
    scheduler = ResilientParallelScheduler()
    scheduler.run((fp("a.java"),), lambda p: "first", checkpoint_path=path)
    called = []
    run = scheduler.run((fp("a.java"),), lambda p: called.append(p), checkpoint_path=path)
    assert called == []
    assert run.resumed == (Path("a.java"),)
    assert run.result_map()[Path("a.java")] == "first"


def test_resume_can_be_disabled(tmp_path):
    path = tmp_path / "checkpoint.json"
    scheduler = ResilientParallelScheduler()
    scheduler.run((fp("a.java"),), lambda p: "first", checkpoint_path=path)
    run = scheduler.run((fp("a.java"),), lambda p: "second", checkpoint_path=path, resume=False, full_rebuild=True)
    assert run.result_map()[Path("a.java")] == "second"
    assert run.resumed == ()


def test_changed_fingerprint_is_not_resumed(tmp_path):
    path = tmp_path / "checkpoint.json"
    scheduler = ResilientParallelScheduler()
    scheduler.run((fp("a.java", "a"),), lambda p: "old", checkpoint_path=path)
    run = scheduler.run((fp("a.java", "b"),), lambda p: "new", previous=(fp("a.java", "a"),), checkpoint_path=path)
    assert run.result_map()[Path("a.java")] == "new"
    assert run.resumed == ()


def test_removed_checkpoint_entries_are_pruned(tmp_path):
    path = tmp_path / "checkpoint.json"
    scheduler = ResilientParallelScheduler()
    scheduler.run((fp("a.java"), fp("b.java")), lambda p: p.name, checkpoint_path=path)
    scheduler.run((fp("a.java"),), lambda p: p.name, checkpoint_path=path)
    assert [entry.path for entry in ExecutionCheckpoint.load(path).entries] == [Path("a.java")]


def test_failed_items_are_not_checkpointed(tmp_path):
    path = tmp_path / "checkpoint.json"
    scheduler = ResilientParallelScheduler()
    scheduler.run((fp("a.java"),), lambda p: (_ for _ in ()).throw(ValueError()), checkpoint_path=path)
    assert ExecutionCheckpoint.load(path).entries == ()


def test_successes_before_failure_are_checkpointed(tmp_path):
    path = tmp_path / "checkpoint.json"
    scheduler = ResilientParallelScheduler(max_workers=1)
    def analyzer(p):
        if p.name == "b.java": raise ValueError("bad")
        return p.name
    scheduler.run((fp("a.java"), fp("b.java")), analyzer, checkpoint_path=path)
    assert ExecutionCheckpoint.load(path).get(Path("a.java"), "a" * 64) == "a.java"


def test_dependency_failure_cancels_dependent():
    a, b = Path("a.java"), Path("b.java")
    run = ResilientParallelScheduler().run((fp("a.java"), fp("b.java")), lambda p: (_ for _ in ()).throw(ValueError()) if p == a else 1, dependencies={b: (a,)})
    assert run.cancelled == (b,)


def test_independent_branch_survives_failure():
    run = ResilientParallelScheduler(max_workers=2).run((fp("a.java"), fp("b.java")), lambda p: (_ for _ in ()).throw(ValueError()) if p.name == "a.java" else "ok")
    assert run.result_map() == {Path("b.java"): "ok"}


def test_fail_fast_cancels_later_wave():
    a, b = Path("a.java"), Path("b.java")
    run = ResilientParallelScheduler().run((fp("a.java"), fp("b.java")), lambda p: (_ for _ in ()).throw(ValueError()), dependencies={b: (a,)}, fail_fast=True)
    assert b in run.cancelled


def test_cycle_is_still_rejected():
    a, b = Path("a.java"), Path("b.java")
    with pytest.raises(Exception, match="cycle"):
        ResilientParallelScheduler().run((fp("a.java"), fp("b.java")), lambda p: 1, dependencies={a: (b,), b: (a,)})


def test_results_are_stably_sorted():
    run = ResilientParallelScheduler(max_workers=3).run((fp("c.java"), fp("a.java"), fp("b.java")), lambda p: p.name)
    assert [p.name for p, _ in run.results] == ["a.java", "b.java", "c.java"]


def test_attempts_are_stably_sorted_by_path_and_number():
    counts = {"a.java": 0, "b.java": 0}
    def analyzer(p):
        counts[p.name] += 1
        if counts[p.name] == 1: raise ValueError()
        return p.name
    run = ResilientParallelScheduler(max_workers=2, retry_policy=RetryPolicy(max_attempts=2)).run((fp("b.java"), fp("a.java")), analyzer)
    assert [(r.path.name, r.attempt) for r in run.attempts] == [("a.java", 1), ("a.java", 2), ("b.java", 1), ("b.java", 2)]


def test_result_map_is_copy():
    run = ResilientParallelScheduler().run((fp("a.java"),), lambda p: 1)
    value = run.result_map(); value[Path("b.java")] = 2
    assert Path("b.java") not in run.result_map()


def test_empty_run_succeeds(tmp_path):
    path = tmp_path / "checkpoint.json"
    run = ResilientParallelScheduler().run((), lambda p: 1, checkpoint_path=path)
    assert run.succeeded and run.results == ()
    assert json.loads(path.read_text())["entries"] == []


def test_backoff_zero_does_not_delay_contract():
    policy = RetryPolicy(max_attempts=2, backoff_seconds=0)
    assert policy.backoff_seconds == 0


def test_checkpoint_put_validates_digest():
    with pytest.raises(ValueError, match="SHA-256"):
        ExecutionCheckpoint().put(Path("a"), "bad", 1)


def test_checkpoint_get_requires_matching_fingerprint():
    checkpoint = ExecutionCheckpoint((CheckpointEntry(Path("a"), "a" * 64, 1),))
    assert checkpoint.get(Path("a"), "b" * 64) is None


def test_retry_record_contains_error_details():
    scheduler = ResilientParallelScheduler(retry_policy=RetryPolicy(max_attempts=2))
    run = scheduler.run((fp("a.java"),), lambda p: (_ for _ in ()).throw(ValueError("temporary")))
    assert run.attempts[0].error_type == "ValueError"
    assert run.attempts[0].message == "temporary"


def test_full_rebuild_ignores_checkpoint(tmp_path):
    path = tmp_path / "checkpoint.json"
    scheduler = ResilientParallelScheduler()
    scheduler.run((fp("a.java"),), lambda p: "old", checkpoint_path=path)
    run = scheduler.run((fp("a.java"),), lambda p: "new", checkpoint_path=path, full_rebuild=True)
    assert run.result_map()[Path("a.java")] == "new"


def test_resume_and_cache_are_reported_separately(tmp_path):
    path = tmp_path / "checkpoint.json"
    cache = IncrementalCache()
    cache.put("b.java", "b" * 64, "cached")
    checkpoint = ExecutionCheckpoint((CheckpointEntry(Path("a.java"), "a" * 64, "resumed"),))
    checkpoint.save(path)
    scheduler = ResilientParallelScheduler(IncrementalAnalysisEngine(cache))
    run = scheduler.run((fp("a.java"), fp("b.java", "b")), lambda p: "new", previous=(fp("a.java"), fp("b.java", "b")), checkpoint_path=path)
    assert run.resumed == (Path("a.java"),)
    assert run.reused == (Path("b.java"),)
