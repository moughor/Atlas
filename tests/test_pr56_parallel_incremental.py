from __future__ import annotations

from pathlib import Path
from threading import Barrier, Lock
import time

import pytest

from moughorai.incremental_analysis import (
    DependencyCycleError,
    FileFingerprint,
    IncrementalAnalysisEngine,
    IncrementalCache,
    ParallelIncrementalScheduler,
)


def fp(name: str, digit: str = "a") -> FileFingerprint:
    return FileFingerprint(Path(name), 1, digit * 64)


def test_max_workers_must_be_positive():
    with pytest.raises(ValueError, match="at least one"):
        ParallelIncrementalScheduler(max_workers=0)


def test_empty_plan_has_no_waves():
    assert ParallelIncrementalScheduler().plan_waves(()) == ()


def test_independent_files_share_wave():
    paths = [Path("b.java"), Path("a.java")]
    assert ParallelIncrementalScheduler().plan_waves(paths) == ((Path("a.java"), Path("b.java")),)


def test_dependency_creates_ordered_waves():
    a, b, c = map(Path, ("a.java", "b.java", "c.java"))
    waves = ParallelIncrementalScheduler().plan_waves((c, a, b), {b: (a,), c: (b,)})
    assert waves == ((a,), (b,), (c,))


def test_external_dependency_does_not_create_wave():
    a, external = Path("a.java"), Path("lib.java")
    assert ParallelIncrementalScheduler().plan_waves((a,), {a: (external,)}) == ((a,),)


def test_cycle_reports_all_cycle_candidates():
    a, b = Path("a.java"), Path("b.java")
    with pytest.raises(DependencyCycleError) as caught:
        ParallelIncrementalScheduler().plan_waves((a, b), {a: (b,), b: (a,)})
    assert caught.value.paths == (a, b)
    assert "a.java" in str(caught.value)


def test_self_cycle_is_rejected():
    a = Path("a.java")
    with pytest.raises(DependencyCycleError):
        ParallelIncrementalScheduler().plan_waves((a,), {a: (a,)})


def test_results_are_stably_ordered_despite_completion_order():
    scheduler = ParallelIncrementalScheduler(max_workers=3)
    current = (fp("c.java"), fp("a.java"), fp("b.java"))

    def analyzer(path: Path):
        time.sleep({"a.java": .02, "b.java": .01, "c.java": 0}[path.name])
        return path.stem

    run = scheduler.run(current, analyzer)
    assert [path.name for path, _ in run.results] == ["a.java", "b.java", "c.java"]
    assert run.analyzed == (Path("a.java"), Path("b.java"), Path("c.java"))


def test_parallel_workers_overlap():
    scheduler = ParallelIncrementalScheduler(max_workers=2)
    barrier = Barrier(2)
    seen: list[str] = []
    lock = Lock()

    def analyzer(path: Path):
        barrier.wait(timeout=1)
        with lock:
            seen.append(path.name)
        return path.name

    run = scheduler.run((fp("a.java"), fp("b.java")), analyzer)
    assert run.succeeded
    assert sorted(seen) == ["a.java", "b.java"]


def test_dependency_is_completed_before_dependent_starts():
    scheduler = ParallelIncrementalScheduler(max_workers=4)
    a, b = Path("a.java"), Path("b.java")
    order: list[str] = []

    def analyzer(path: Path):
        order.append(path.name)
        return path.name

    scheduler.run((fp("a.java"), fp("b.java")), analyzer, dependencies={b: (a,)})
    assert order == ["a.java", "b.java"]


def test_successful_results_are_written_to_cache():
    cache = IncrementalCache()
    scheduler = ParallelIncrementalScheduler(IncrementalAnalysisEngine(cache), max_workers=2)
    scheduler.run((fp("a.java"),), lambda path: {"path": path.name})
    assert cache.get("a.java", "a" * 64) == {"path": "a.java"}


def test_unchanged_cached_result_is_reused():
    cache = IncrementalCache()
    cache.put("a.java", "a" * 64, "cached")
    scheduler = ParallelIncrementalScheduler(IncrementalAnalysisEngine(cache))
    called = []
    run = scheduler.run((fp("a.java"),), lambda path: called.append(path), previous=(fp("a.java"),))
    assert called == []
    assert run.reused == (Path("a.java"),)
    assert run.result_map()[Path("a.java")] == "cached"


def test_cache_miss_for_unchanged_file_triggers_analysis():
    scheduler = ParallelIncrementalScheduler()
    run = scheduler.run((fp("a.java"),), lambda path: "new", previous=(fp("a.java"),))
    assert run.analyzed == (Path("a.java"),)


def test_modified_file_is_not_reused():
    cache = IncrementalCache()
    cache.put("a.java", "a" * 64, "old")
    scheduler = ParallelIncrementalScheduler(IncrementalAnalysisEngine(cache))
    run = scheduler.run((fp("a.java", "b"),), lambda path: "new", previous=(fp("a.java", "a"),))
    assert run.result_map()[Path("a.java")] == "new"


def test_removed_files_are_invalidated():
    cache = IncrementalCache()
    cache.put("gone.java", "a" * 64, "old")
    scheduler = ParallelIncrementalScheduler(IncrementalAnalysisEngine(cache))
    run = scheduler.run((), lambda path: None, previous=(fp("gone.java"),))
    assert run.changes.removed == (Path("gone.java"),)
    assert cache.entries == ()


def test_full_rebuild_analyzes_unchanged_cached_files():
    cache = IncrementalCache()
    cache.put("a.java", "a" * 64, "old")
    scheduler = ParallelIncrementalScheduler(IncrementalAnalysisEngine(cache))
    run = scheduler.run((fp("a.java"),), lambda path: "new", previous=(fp("a.java"),), full_rebuild=True)
    assert run.analyzed == (Path("a.java"),)
    assert run.reused == ()


def test_failure_is_captured_without_raising():
    scheduler = ParallelIncrementalScheduler()

    def analyzer(path: Path):
        raise RuntimeError("boom")

    run = scheduler.run((fp("a.java"),), analyzer)
    assert not run.succeeded
    assert run.failures[0].error_type == "RuntimeError"
    assert run.failures[0].message == "boom"
    assert run.results == ()


def test_failed_result_is_not_cached():
    cache = IncrementalCache()
    scheduler = ParallelIncrementalScheduler(IncrementalAnalysisEngine(cache))
    run = scheduler.run((fp("a.java"),), lambda path: (_ for _ in ()).throw(ValueError("bad")))
    assert run.failures
    assert cache.entries == ()


def test_independent_branch_continues_after_failure():
    scheduler = ParallelIncrementalScheduler(max_workers=2)

    def analyzer(path: Path):
        if path.name == "a.java":
            raise ValueError("bad")
        return path.name

    run = scheduler.run((fp("a.java"), fp("b.java")), analyzer)
    assert run.result_map() == {Path("b.java"): "b.java"}
    assert [failure.path for failure in run.failures] == [Path("a.java")]


def test_dependent_of_failure_is_cancelled():
    scheduler = ParallelIncrementalScheduler()
    a, b = Path("a.java"), Path("b.java")

    def analyzer(path: Path):
        if path == a:
            raise ValueError("bad")
        return path.name

    run = scheduler.run((fp("a.java"), fp("b.java")), analyzer, dependencies={b: (a,)})
    assert run.cancelled == (b,)
    assert b not in run.completed


def test_transitive_dependents_of_failure_are_cancelled():
    scheduler = ParallelIncrementalScheduler()
    a, b, c = map(Path, ("a.java", "b.java", "c.java"))
    run = scheduler.run(
        (fp("a.java"), fp("b.java"), fp("c.java")),
        lambda path: (_ for _ in ()).throw(ValueError("bad")) if path == a else path.name,
        dependencies={b: (a,), c: (b,)},
    )
    assert run.cancelled == (b, c)


def test_fail_fast_cancels_later_waves():
    scheduler = ParallelIncrementalScheduler(max_workers=2)
    a, b, c = map(Path, ("a.java", "b.java", "c.java"))
    run = scheduler.run(
        (fp("a.java"), fp("b.java"), fp("c.java")),
        lambda path: (_ for _ in ()).throw(ValueError("bad")) if path == a else path.name,
        dependencies={c: (b,)},
        fail_fast=True,
    )
    assert c in run.cancelled


def test_fail_fast_finishes_current_wave():
    scheduler = ParallelIncrementalScheduler(max_workers=2)

    def analyzer(path: Path):
        if path.name == "a.java":
            raise ValueError("bad")
        return "ok"

    run = scheduler.run((fp("a.java"), fp("b.java")), analyzer, fail_fast=True)
    assert run.result_map() == {Path("b.java"): "ok"}


def test_waves_are_exposed_in_run_report():
    scheduler = ParallelIncrementalScheduler()
    a, b = Path("a.java"), Path("b.java")
    run = scheduler.run((fp("a.java"), fp("b.java")), lambda path: path.name, dependencies={b: (a,)})
    assert run.waves == ((a,), (b,))


def test_result_map_returns_copy():
    run = ParallelIncrementalScheduler().run((fp("a.java"),), lambda path: 1)
    result = run.result_map()
    result[Path("b.java")] = 2
    assert Path("b.java") not in run.result_map()


def test_completed_excludes_failures_and_cancellations():
    scheduler = ParallelIncrementalScheduler()
    a, b = Path("a.java"), Path("b.java")
    run = scheduler.run(
        (fp("a.java"), fp("b.java")),
        lambda path: (_ for _ in ()).throw(RuntimeError()) if path == a else 1,
        dependencies={b: (a,)},
    )
    assert run.completed == ()


def test_duplicate_paths_are_normalized_by_fingerprint_map():
    scheduler = ParallelIncrementalScheduler()
    run = scheduler.run((fp("a.java"), fp("a.java")), lambda path: path.name)
    assert run.analyzed == (Path("a.java"),)


def test_duplicate_dependencies_do_not_change_waves():
    a, b = Path("a.java"), Path("b.java")
    waves = ParallelIncrementalScheduler().plan_waves((a, b), {b: (a, a)})
    assert waves == ((a,), (b,))


@pytest.mark.parametrize("workers", [1, 2, 4, 8])
def test_worker_counts_produce_same_deterministic_report(workers: int):
    scheduler = ParallelIncrementalScheduler(max_workers=workers)
    current = tuple(fp(f"{letter}.java") for letter in "dcba")
    run = scheduler.run(current, lambda path: path.stem)
    assert run.results == tuple((Path(f"{letter}.java"), letter) for letter in "abcd")


@pytest.mark.parametrize("message", ["", "simple", "unicode café", "line one\nline two"])
def test_failure_message_is_preserved(message: str):
    scheduler = ParallelIncrementalScheduler()
    run = scheduler.run((fp("a.java"),), lambda path: (_ for _ in ()).throw(RuntimeError(message)))
    assert run.failures[0].message == message


@pytest.mark.parametrize("name", ["A.java", "a.java", "nested/A.java", "space name.java"])
def test_path_forms_are_preserved(name: str):
    scheduler = ParallelIncrementalScheduler()
    path = Path(name)
    run = scheduler.run((FileFingerprint(path, 1, "a" * 64),), lambda value: value.as_posix())
    assert run.results[0] == (path, path.as_posix())


def test_all_public_types_are_importable():
    from moughorai.incremental_analysis import (  # noqa: F401
        DependencyCycleError,
        ExecutionFailure,
        ParallelIncrementalRun,
        ParallelIncrementalScheduler,
    )
