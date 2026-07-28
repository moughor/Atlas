"""Transport-neutral distributed coordination for incremental analysis jobs."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from threading import RLock
import time
from typing import Any, Callable, Iterable, Mapping

from .engine import _path_key
from .scheduler import DependencyCycleError, ExecutionFailure, ParallelIncrementalScheduler


class WorkerUnavailableError(RuntimeError):
    """Raised when an unknown or inactive worker requests coordinator work."""


class LeaseConflictError(RuntimeError):
    """Raised when a worker attempts to complete a lease it does not own."""


class JobState(str, Enum):
    PENDING = "pending"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, order=True)
class WorkerRegistration:
    worker_id: str
    capabilities: tuple[str, ...] = ()
    metadata: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.worker_id.strip():
            raise ValueError("worker_id must not be empty")
        object.__setattr__(self, "capabilities", tuple(sorted(set(self.capabilities))))
        object.__setattr__(self, "metadata", tuple(sorted(dict(self.metadata).items())))


@dataclass(frozen=True)
class WorkerStatus:
    registration: WorkerRegistration
    last_heartbeat: float
    active: bool = True
    completed: int = 0
    failed: int = 0


@dataclass(frozen=True, order=True)
class DistributedJob:
    path: Path
    fingerprint: str
    dependencies: tuple[Path, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    max_attempts: int = 1

    def __post_init__(self) -> None:
        if len(self.fingerprint) != 64:
            raise ValueError("fingerprint must be a SHA-256 digest")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        object.__setattr__(self, "dependencies", tuple(sorted(set(self.dependencies), key=_path_key)))
        object.__setattr__(self, "required_capabilities", tuple(sorted(set(self.required_capabilities))))


@dataclass(frozen=True, order=True)
class JobLease:
    path: Path
    worker_id: str
    lease_id: int
    attempt: int
    expires_at: float


@dataclass(frozen=True)
class JobRecord:
    job: DistributedJob
    state: JobState = JobState.PENDING
    attempt: int = 0
    lease: JobLease | None = None
    result: Any = None
    failure: ExecutionFailure | None = None


@dataclass(frozen=True)
class CoordinatorMetrics:
    submitted: int = 0
    leased: int = 0
    completed: int = 0
    failed: int = 0
    retried: int = 0
    expired_leases: int = 0
    cancelled: int = 0


@dataclass(frozen=True)
class CoordinatorSnapshot:
    workers: tuple[WorkerStatus, ...]
    jobs: tuple[JobRecord, ...]
    metrics: CoordinatorMetrics

    @property
    def pending(self) -> tuple[Path, ...]:
        return tuple(record.job.path for record in self.jobs if record.state == JobState.PENDING)

    @property
    def completed(self) -> tuple[Path, ...]:
        return tuple(record.job.path for record in self.jobs if record.state == JobState.SUCCEEDED)


@dataclass(frozen=True)
class DistributedExecutionRun:
    results: tuple[tuple[Path, Any], ...]
    failures: tuple[ExecutionFailure, ...]
    cancelled: tuple[Path, ...]
    assignments: tuple[JobLease, ...]
    metrics: CoordinatorMetrics

    @property
    def succeeded(self) -> bool:
        return not self.failures and not self.cancelled

    def result_map(self) -> dict[Path, Any]:
        return dict(self.results)


class DistributedAnalysisCoordinator:
    """Coordinates deterministic job leasing across transport adapters.

    The class intentionally has no networking dependency. A REST, RPC, queue, or
    in-process adapter can expose these methods without changing scheduling rules.
    """

    def __init__(self, *, lease_seconds: float = 30.0, heartbeat_timeout: float = 90.0) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if heartbeat_timeout <= 0:
            raise ValueError("heartbeat_timeout must be positive")
        self.lease_seconds = float(lease_seconds)
        self.heartbeat_timeout = float(heartbeat_timeout)
        self._workers: dict[str, WorkerStatus] = {}
        self._jobs: dict[Path, JobRecord] = {}
        self._lease_sequence = 0
        self._metrics = CoordinatorMetrics()
        self._lock = RLock()

    def register_worker(
        self,
        worker_id: str,
        *,
        capabilities: Iterable[str] = (),
        metadata: Mapping[str, str] | None = None,
        now: float | None = None,
    ) -> WorkerStatus:
        registration = WorkerRegistration(worker_id, tuple(capabilities), tuple((metadata or {}).items()))
        timestamp = time.monotonic() if now is None else float(now)
        with self._lock:
            previous = self._workers.get(worker_id)
            status = WorkerStatus(
                registration,
                timestamp,
                True,
                0 if previous is None else previous.completed,
                0 if previous is None else previous.failed,
            )
            self._workers[worker_id] = status
            return status

    def heartbeat(self, worker_id: str, *, now: float | None = None) -> WorkerStatus:
        timestamp = time.monotonic() if now is None else float(now)
        with self._lock:
            worker = self._require_worker(worker_id)
            updated = WorkerStatus(worker.registration, timestamp, True, worker.completed, worker.failed)
            self._workers[worker_id] = updated
            return updated

    def deactivate_stale_workers(self, *, now: float | None = None) -> tuple[str, ...]:
        timestamp = time.monotonic() if now is None else float(now)
        stale: list[str] = []
        with self._lock:
            for worker_id, worker in sorted(self._workers.items()):
                if worker.active and timestamp - worker.last_heartbeat > self.heartbeat_timeout:
                    self._workers[worker_id] = WorkerStatus(
                        worker.registration, worker.last_heartbeat, False, worker.completed, worker.failed
                    )
                    stale.append(worker_id)
            if stale:
                self._expire_leases_locked(timestamp, owners=set(stale))
        return tuple(stale)

    def submit(self, jobs: Iterable[DistributedJob]) -> tuple[Path, ...]:
        incoming = tuple(sorted(jobs, key=lambda job: _path_key(job.path)))
        if len({job.path for job in incoming}) != len(incoming):
            raise ValueError("duplicate job path")
        all_paths = set(self._jobs) | {job.path for job in incoming}
        scheduler = ParallelIncrementalScheduler()
        dependency_map = {job.path: job.dependencies for job in incoming}
        scheduler.plan_waves(all_paths, dependency_map)
        with self._lock:
            duplicates = [job.path for job in incoming if job.path in self._jobs]
            if duplicates:
                joined = ", ".join(path.as_posix() for path in duplicates)
                raise ValueError(f"jobs already submitted: {joined}")
            for job in incoming:
                self._jobs[job.path] = JobRecord(job)
            self._metrics = self._replace_metrics(submitted=self._metrics.submitted + len(incoming))
        return tuple(job.path for job in incoming)

    def lease(self, worker_id: str, *, limit: int = 1, now: float | None = None) -> tuple[JobLease, ...]:
        if limit < 1:
            raise ValueError("limit must be at least one")
        timestamp = time.monotonic() if now is None else float(now)
        with self._lock:
            worker = self._require_worker(worker_id)
            if not worker.active:
                raise WorkerUnavailableError(f"worker is inactive: {worker_id}")
            self._expire_leases_locked(timestamp)
            capabilities = set(worker.registration.capabilities)
            ready = [
                record
                for record in self._jobs.values()
                if record.state == JobState.PENDING
                and set(record.job.required_capabilities) <= capabilities
                and self._dependencies_succeeded(record.job)
            ]
            ready.sort(key=lambda record: _path_key(record.job.path))
            leases: list[JobLease] = []
            for record in ready[:limit]:
                self._lease_sequence += 1
                lease = JobLease(
                    record.job.path,
                    worker_id,
                    self._lease_sequence,
                    record.attempt + 1,
                    timestamp + self.lease_seconds,
                )
                self._jobs[record.job.path] = JobRecord(
                    record.job, JobState.LEASED, lease.attempt, lease, record.result, record.failure
                )
                leases.append(lease)
            self._metrics = self._replace_metrics(leased=self._metrics.leased + len(leases))
            return tuple(leases)

    def complete(self, worker_id: str, lease_id: int, result: Any) -> JobRecord:
        with self._lock:
            path, record = self._record_for_lease(worker_id, lease_id)
            updated = JobRecord(record.job, JobState.SUCCEEDED, record.attempt, None, result, None)
            self._jobs[path] = updated
            worker = self._require_worker(worker_id)
            self._workers[worker_id] = WorkerStatus(
                worker.registration, worker.last_heartbeat, worker.active, worker.completed + 1, worker.failed
            )
            self._metrics = self._replace_metrics(completed=self._metrics.completed + 1)
            return updated

    def fail(self, worker_id: str, lease_id: int, error: BaseException) -> JobRecord:
        with self._lock:
            path, record = self._record_for_lease(worker_id, lease_id)
            failure = ExecutionFailure(path, type(error).__name__, str(error))
            worker = self._require_worker(worker_id)
            self._workers[worker_id] = WorkerStatus(
                worker.registration, worker.last_heartbeat, worker.active, worker.completed, worker.failed + 1
            )
            if record.attempt < record.job.max_attempts:
                updated = JobRecord(record.job, JobState.PENDING, record.attempt, None, None, failure)
                self._metrics = self._replace_metrics(
                    failed=self._metrics.failed + 1, retried=self._metrics.retried + 1
                )
            else:
                updated = JobRecord(record.job, JobState.FAILED, record.attempt, None, None, failure)
                self._metrics = self._replace_metrics(failed=self._metrics.failed + 1)
                self._cancel_dependents_locked(path)
            self._jobs[path] = updated
            return updated

    def expire_leases(self, *, now: float | None = None) -> tuple[Path, ...]:
        timestamp = time.monotonic() if now is None else float(now)
        with self._lock:
            return self._expire_leases_locked(timestamp)

    def snapshot(self) -> CoordinatorSnapshot:
        with self._lock:
            workers = tuple(self._workers[key] for key in sorted(self._workers))
            jobs = tuple(sorted(self._jobs.values(), key=lambda record: _path_key(record.job.path)))
            return CoordinatorSnapshot(workers, jobs, self._metrics)

    def execute_locally(
        self,
        analyzers: Mapping[str, Callable[[Path], Any]],
        *,
        fail_fast: bool = False,
        now: float = 0.0,
    ) -> DistributedExecutionRun:
        """Drive the coordinator with deterministic in-process worker adapters."""
        if not analyzers:
            raise ValueError("at least one worker analyzer is required")
        for worker_id in sorted(analyzers):
            if worker_id not in self._workers:
                self.register_worker(worker_id, now=now)
        assignments: list[JobLease] = []
        while True:
            progress = False
            for worker_id in sorted(analyzers):
                leases = self.lease(worker_id, limit=1, now=now)
                if not leases:
                    continue
                progress = True
                lease = leases[0]
                assignments.append(lease)
                try:
                    self.complete(worker_id, lease.lease_id, analyzers[worker_id](lease.path))
                except BaseException as error:
                    record = self.fail(worker_id, lease.lease_id, error)
                    if fail_fast and record.state == JobState.FAILED:
                        self._cancel_all_pending_locked()
                        progress = False
                        break
            snapshot = self.snapshot()
            terminal = all(
                record.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}
                for record in snapshot.jobs
            )
            if terminal or not progress:
                break
        snapshot = self.snapshot()
        results = tuple(
            (record.job.path, record.result)
            for record in snapshot.jobs
            if record.state == JobState.SUCCEEDED
        )
        failures = tuple(
            record.failure for record in snapshot.jobs if record.state == JobState.FAILED and record.failure is not None
        )
        cancelled = tuple(record.job.path for record in snapshot.jobs if record.state == JobState.CANCELLED)
        return DistributedExecutionRun(results, failures, cancelled, tuple(assignments), snapshot.metrics)

    def _require_worker(self, worker_id: str) -> WorkerStatus:
        try:
            return self._workers[worker_id]
        except KeyError as exc:
            raise WorkerUnavailableError(f"unknown worker: {worker_id}") from exc

    def _record_for_lease(self, worker_id: str, lease_id: int) -> tuple[Path, JobRecord]:
        for path, record in self._jobs.items():
            lease = record.lease
            if lease is not None and lease.lease_id == lease_id:
                if lease.worker_id != worker_id:
                    raise LeaseConflictError("lease belongs to another worker")
                if record.state != JobState.LEASED:
                    raise LeaseConflictError("lease is no longer active")
                return path, record
        raise LeaseConflictError(f"unknown lease: {lease_id}")

    def _dependencies_succeeded(self, job: DistributedJob) -> bool:
        return all(
            dependency in self._jobs and self._jobs[dependency].state == JobState.SUCCEEDED
            for dependency in job.dependencies
        )

    def _expire_leases_locked(self, now: float, owners: set[str] | None = None) -> tuple[Path, ...]:
        expired: list[Path] = []
        for path, record in sorted(self._jobs.items(), key=lambda item: _path_key(item[0])):
            lease = record.lease
            if record.state != JobState.LEASED or lease is None:
                continue
            if owners is not None and lease.worker_id not in owners:
                continue
            if owners is None and lease.expires_at > now:
                continue
            if record.attempt < record.job.max_attempts:
                self._jobs[path] = JobRecord(record.job, JobState.PENDING, record.attempt, None, None, record.failure)
                self._metrics = self._replace_metrics(retried=self._metrics.retried + 1)
            else:
                failure = ExecutionFailure(path, "LeaseExpired", "worker lease expired")
                self._jobs[path] = JobRecord(record.job, JobState.FAILED, record.attempt, None, None, failure)
                self._cancel_dependents_locked(path)
            expired.append(path)
        if expired:
            self._metrics = self._replace_metrics(expired_leases=self._metrics.expired_leases + len(expired))
        return tuple(expired)

    def _cancel_dependents_locked(self, failed_path: Path) -> None:
        changed = True
        blocked = {failed_path}
        while changed:
            changed = False
            for path, record in sorted(self._jobs.items(), key=lambda item: _path_key(item[0])):
                if record.state != JobState.PENDING:
                    continue
                if set(record.job.dependencies) & blocked:
                    self._jobs[path] = JobRecord(record.job, JobState.CANCELLED, record.attempt)
                    blocked.add(path)
                    self._metrics = self._replace_metrics(cancelled=self._metrics.cancelled + 1)
                    changed = True

    def _cancel_all_pending_locked(self) -> None:
        with self._lock:
            count = 0
            for path, record in tuple(self._jobs.items()):
                if record.state == JobState.PENDING:
                    self._jobs[path] = JobRecord(record.job, JobState.CANCELLED, record.attempt)
                    count += 1
            if count:
                self._metrics = self._replace_metrics(cancelled=self._metrics.cancelled + count)

    def _replace_metrics(self, **changes: int) -> CoordinatorMetrics:
        values = {
            "submitted": self._metrics.submitted,
            "leased": self._metrics.leased,
            "completed": self._metrics.completed,
            "failed": self._metrics.failed,
            "retried": self._metrics.retried,
            "expired_leases": self._metrics.expired_leases,
            "cancelled": self._metrics.cancelled,
        }
        values.update(changes)
        return CoordinatorMetrics(**values)
