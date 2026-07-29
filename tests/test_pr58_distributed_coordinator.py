from pathlib import Path
import pytest

from moughorai.incremental_analysis import (
    DistributedAnalysisCoordinator, DistributedJob, JobState,
    LeaseConflictError, WorkerRegistration, WorkerUnavailableError,
)

DIGEST = "a" * 64

def job(name, deps=(), caps=(), attempts=1):
    return DistributedJob(Path(name), DIGEST, tuple(Path(x) for x in deps), tuple(caps), attempts)


def test_registration_normalizes_capabilities_and_metadata():
    r = WorkerRegistration("w", ("gpu", "cpu", "gpu"), (("b", "2"), ("a", "1")))
    assert r.capabilities == ("cpu", "gpu")
    assert r.metadata == (("a", "1"), ("b", "2"))

@pytest.mark.parametrize("worker_id", ["", "   "])
def test_registration_rejects_empty_id(worker_id):
    with pytest.raises(ValueError): WorkerRegistration(worker_id)

@pytest.mark.parametrize("lease,heartbeat", [(0, 1), (-1, 1), (1, 0), (1, -1)])
def test_invalid_timeouts(lease, heartbeat):
    with pytest.raises(ValueError): DistributedAnalysisCoordinator(lease_seconds=lease, heartbeat_timeout=heartbeat)


def test_register_and_heartbeat():
    c = DistributedAnalysisCoordinator()
    c.register_worker("w", capabilities=("cpu",), now=1)
    s = c.heartbeat("w", now=2)
    assert s.last_heartbeat == 2 and s.active


def test_unknown_worker_rejected():
    c = DistributedAnalysisCoordinator()
    with pytest.raises(WorkerUnavailableError): c.heartbeat("missing")


def test_submit_is_deterministic():
    c = DistributedAnalysisCoordinator()
    assert c.submit([job("b.py"), job("a.py")]) == (Path("a.py"), Path("b.py"))
    assert c.snapshot().pending == (Path("a.py"), Path("b.py"))


def test_duplicate_submission_rejected():
    c = DistributedAnalysisCoordinator(); c.submit([job("a.py")])
    with pytest.raises(ValueError): c.submit([job("a.py")])


def test_duplicate_in_batch_rejected():
    c = DistributedAnalysisCoordinator()
    with pytest.raises(ValueError): c.submit([job("a.py"), job("a.py")])


def test_cycle_rejected():
    c = DistributedAnalysisCoordinator()
    with pytest.raises(ValueError): c.submit([job("a", ("b",)), job("b", ("a",))])


def test_capability_filtering():
    c = DistributedAnalysisCoordinator(); c.register_worker("cpu", capabilities=("cpu",), now=0)
    c.submit([job("gpu.py", caps=("gpu",)), job("cpu.py", caps=("cpu",))])
    leases = c.lease("cpu", limit=2, now=0)
    assert [x.path for x in leases] == [Path("cpu.py")]


def test_dependencies_wait_for_success():
    c = DistributedAnalysisCoordinator(); c.register_worker("w", now=0)
    c.submit([job("a"), job("b", ("a",))])
    first = c.lease("w", limit=2, now=0)
    assert [x.path for x in first] == [Path("a")]
    c.complete("w", first[0].lease_id, 1)
    assert c.lease("w", now=0)[0].path == Path("b")


def test_completion_records_result_and_metrics():
    c = DistributedAnalysisCoordinator(); c.register_worker("w", now=0); c.submit([job("a")])
    lease = c.lease("w", now=0)[0]; c.complete("w", lease.lease_id, {"ok": 1})
    snap = c.snapshot()
    assert snap.jobs[0].result == {"ok": 1}
    assert snap.metrics.completed == 1
    assert snap.workers[0].completed == 1


def test_wrong_worker_cannot_complete():
    c = DistributedAnalysisCoordinator(); c.register_worker("a", now=0); c.register_worker("b", now=0); c.submit([job("x")])
    lease = c.lease("a", now=0)[0]
    with pytest.raises(LeaseConflictError): c.complete("b", lease.lease_id, 1)


def test_failure_retries_until_max_attempts():
    c = DistributedAnalysisCoordinator(); c.register_worker("w", now=0); c.submit([job("a", attempts=2)])
    first = c.lease("w", now=0)[0]; r = c.fail("w", first.lease_id, RuntimeError("x"))
    assert r.state == JobState.PENDING
    second = c.lease("w", now=0)[0]; r = c.fail("w", second.lease_id, RuntimeError("y"))
    assert r.state == JobState.FAILED
    assert c.snapshot().metrics.retried == 1


def test_terminal_failure_cancels_transitive_dependents():
    c = DistributedAnalysisCoordinator(); c.register_worker("w", now=0)
    c.submit([job("a"), job("b", ("a",)), job("c", ("b",))])
    lease = c.lease("w", now=0)[0]; c.fail("w", lease.lease_id, RuntimeError("bad"))
    states = {r.job.path: r.state for r in c.snapshot().jobs}
    assert states == {Path("a"): JobState.FAILED, Path("b"): JobState.CANCELLED, Path("c"): JobState.CANCELLED}


def test_expired_lease_is_requeued():
    c = DistributedAnalysisCoordinator(lease_seconds=5); c.register_worker("w", now=0); c.submit([job("a", attempts=2)])
    c.lease("w", now=0)
    assert c.expire_leases(now=6) == (Path("a"),)
    assert c.snapshot().jobs[0].state == JobState.PENDING


def test_expired_final_lease_fails():
    c = DistributedAnalysisCoordinator(lease_seconds=5); c.register_worker("w", now=0); c.submit([job("a")])
    c.lease("w", now=0); c.expire_leases(now=6)
    assert c.snapshot().jobs[0].state == JobState.FAILED


def test_stale_worker_is_deactivated_and_lease_requeued():
    c = DistributedAnalysisCoordinator(lease_seconds=100, heartbeat_timeout=10)
    c.register_worker("w", now=0); c.submit([job("a", attempts=2)]); c.lease("w", now=0)
    assert c.deactivate_stale_workers(now=11) == ("w",)
    assert c.snapshot().jobs[0].state == JobState.PENDING
    with pytest.raises(WorkerUnavailableError): c.lease("w", now=11)


def test_reregister_reactivates_worker_preserving_counts():
    c = DistributedAnalysisCoordinator(heartbeat_timeout=1); c.register_worker("w", now=0)
    c.deactivate_stale_workers(now=2)
    assert c.register_worker("w", now=3).active


def test_local_execution_merges_results_in_path_order():
    c = DistributedAnalysisCoordinator(); c.submit([job("b"), job("a")])
    run = c.execute_locally({"w2": lambda p: p.name, "w1": lambda p: p.name}, now=0)
    assert run.results == ((Path("a"), "a"), (Path("b"), "b"))
    assert run.succeeded


def test_local_execution_retries():
    c = DistributedAnalysisCoordinator(); c.submit([job("a", attempts=2)])
    calls = {"n": 0}
    def analyzer(path):
        calls["n"] += 1
        if calls["n"] == 1: raise RuntimeError("transient")
        return "ok"
    run = c.execute_locally({"w": analyzer}, now=0)
    assert run.result_map()[Path("a")] == "ok"
    assert run.metrics.retried == 1


def test_local_failure_and_cancellation():
    c = DistributedAnalysisCoordinator(); c.submit([job("a"), job("b", ("a",))])
    run = c.execute_locally({"w": lambda p: (_ for _ in ()).throw(RuntimeError("bad"))}, now=0)
    assert [f.path for f in run.failures] == [Path("a")]
    assert run.cancelled == (Path("b"),)


def test_local_fail_fast_cancels_remaining_independent_jobs():
    c = DistributedAnalysisCoordinator(); c.submit([job("a"), job("b")])
    run = c.execute_locally({"w": lambda p: (_ for _ in ()).throw(RuntimeError("bad"))}, fail_fast=True, now=0)
    assert run.failures[0].path == Path("a")
    assert run.cancelled == (Path("b"),)


def test_local_requires_worker():
    c = DistributedAnalysisCoordinator()
    with pytest.raises(ValueError): c.execute_locally({})

@pytest.mark.parametrize("limit", [0, -1])
def test_invalid_lease_limit(limit):
    c = DistributedAnalysisCoordinator(); c.register_worker("w", now=0)
    with pytest.raises(ValueError): c.lease("w", limit=limit, now=0)

@pytest.mark.parametrize("digest", ["", "a" * 63, "a" * 65])
def test_invalid_digest(digest):
    with pytest.raises(ValueError): DistributedJob(Path("a"), digest)

@pytest.mark.parametrize("attempts", [0, -1])
def test_invalid_attempt_count(attempts):
    with pytest.raises(ValueError): DistributedJob(Path("a"), DIGEST, max_attempts=attempts)


def test_snapshot_order_is_stable():
    c = DistributedAnalysisCoordinator(); c.register_worker("z", now=0); c.register_worker("a", now=0)
    c.submit([job("z"), job("a")])
    s = c.snapshot()
    assert [w.registration.worker_id for w in s.workers] == ["a", "z"]
    assert [r.job.path for r in s.jobs] == [Path("a"), Path("z")]


def test_assignment_order_is_deterministic():
    c = DistributedAnalysisCoordinator(); c.submit([job("c"), job("a"), job("b")])
    run = c.execute_locally({"z": lambda p: p.name, "a": lambda p: p.name}, now=0)
    assert [(x.worker_id, x.path) for x in run.assignments] == [("a", Path("a")), ("z", Path("b")), ("a", Path("c"))]
