"""Hierarchical, optional measurement sessions with no global collector state."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
from threading import RLock, get_ident
from time import perf_counter_ns, process_time_ns
import time
import tracemalloc

from .filesystem import FilesystemLedger
from .models import (
    FilesystemLedgerSnapshot,
    MeasurementPhase,
    MeasurementPhaseSampling,
    MeasurementReport,
    MeasurementSampling,
    MeasurementSample,
    MetricReason,
    MetricStatus,
    MetricUnit,
    MetricValue,
    phase_identifier,
    stable_identifier,
)
from .probes import (
    CurrentProcessMemoryProbe,
    ProcessMemoryProbe,
    ProcessMemoryReading,
)


@dataclass(frozen=True, slots=True)
class MeasurementConfig:
    """Run-level controls.  Collection is disabled unless explicitly enabled."""

    enabled: bool = False
    capture_process_cpu: bool = True
    capture_thread_cpu: bool = True
    capture_process_memory: bool = False
    capture_python_memory: bool = False
    capture_filesystem: bool = True
    worker_metrics_supported: bool = False
    sample_every: int = 1
    filesystem_resource_limit: int = 100_000
    worker_id: str = "main"

    def __post_init__(self) -> None:
        for name in (
            "enabled",
            "capture_process_cpu",
            "capture_thread_cpu",
            "capture_process_memory",
            "capture_python_memory",
            "capture_filesystem",
            "worker_metrics_supported",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")
        if (
            not isinstance(self.sample_every, int)
            or isinstance(self.sample_every, bool)
            or self.sample_every < 1
        ):
            raise ValueError("sample_every must be a positive integer")
        if (
            not isinstance(self.filesystem_resource_limit, int)
            or isinstance(self.filesystem_resource_limit, bool)
            or self.filesystem_resource_limit < 1
        ):
            raise ValueError("filesystem_resource_limit must be a positive integer")
        stable_identifier(self.worker_id, label="worker identifier")


class MeasurementScope:
    """Mutable scope-local counters used to produce an immutable sample."""

    __slots__ = (
        "_closed",
        "_enabled",
        "_work",
        "_worker",
        "_worker_metrics_supported",
        "_concurrent_context",
    )

    def __init__(
        self,
        *,
        enabled: bool,
        worker_metrics_supported: bool,
        concurrent_context: bool = False,
    ) -> None:
        self._enabled = enabled
        self._closed = False
        self._work: dict[str, int] = {}
        self._worker: dict[str, int] = {}
        self._worker_metrics_supported = worker_metrics_supported
        self._concurrent_context = concurrent_context

    def _record(self, target: dict[str, int], name: str, value: int, *, additive: bool) -> None:
        if not self._enabled:
            return
        if self._closed:
            raise RuntimeError("measurement scope is already closed")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
        if additive:
            target[name] = target.get(name, 0) + value
        else:
            target[name] = value

    def add_units(self, count: int = 1) -> None:
        self._record(self._work, "units_processed", count, additive=True)

    def add_bytes(self, count: int) -> None:
        self._record(self._work, "bytes_processed", count, additive=True)

    def add_objects_produced(self, count: int = 1) -> None:
        self._record(self._work, "objects_produced", count, additive=True)

    def set_objects_retained(self, count: int) -> None:
        self._record(self._work, "objects_retained", count, additive=False)

    def set_queue_wait_ns(self, value: int) -> None:
        self._record(self._worker, "queue_wait_ns", value, additive=False)

    def set_idle_time_ns(self, value: int) -> None:
        self._record(self._worker, "idle_time_ns", value, additive=False)

    def set_queue_depth(self, value: int) -> None:
        self._record(self._worker, "queue_depth", value, additive=False)

    def _close(self) -> None:
        self._closed = True


@dataclass(frozen=True, slots=True)
class _ActiveScope:
    path: tuple[str, ...]
    worker_id: str
    concurrent_context: bool


class _MeasurementScopeContext(AbstractContextManager[MeasurementScope]):
    """Class-based context manager that never rewrites application exceptions."""

    def __init__(
        self,
        session: "MeasurementSession",
        phase: MeasurementPhase | str,
        *,
        consumer: str,
        worker_id: str | None,
        sample_key: str | None,
        worker_metrics: bool,
    ) -> None:
        self._session = session
        self._phase = phase
        self._consumer = consumer
        self._worker_id = worker_id
        self._sample_key = sample_key
        self._worker_metrics = worker_metrics
        self._sampled = False
        self._token = None
        self._scope = MeasurementScope(
            enabled=False,
            worker_metrics_supported=False,
        )
        self._phase_id = ""
        self._scope_path: tuple[str, ...] = ()
        self._normalized_consumer = "atlas"
        self._normalized_worker = "main"
        self._memory_start = _disabled_memory()
        unavailable = MetricValue.unavailable(
            MetricUnit.BYTES,
            MetricReason.NOT_RECORDED,
        )
        self._python_start = (unavailable, unavailable)
        self._process_start: int | None = None
        self._thread_start: int | None = None
        self._wall_start: int | None = None

    def __enter__(self) -> MeasurementScope:
        session = self._session
        if not session.config.enabled:
            return self._scope

        self._phase_id = phase_identifier(self._phase)
        self._normalized_consumer = stable_identifier(
            self._consumer,
            label="measurement consumer",
        )
        stack = session._scope_stack.get()
        inherited_worker = stack[-1].worker_id if stack else session.config.worker_id
        self._scope_path = (*((stack[-1].path) if stack else ()), self._phase_id)
        self._normalized_worker = stable_identifier(
            self._worker_id or inherited_worker,
            label="worker identifier",
        )
        concurrent_context = self._worker_metrics or (
            stack[-1].concurrent_context if stack else False
        )
        self._sampled = session._should_sample(
            self._scope_path,
            self._normalized_consumer,
            self._sample_key,
        )
        self._token = session._scope_stack.set(
            (*stack, _ActiveScope(
                self._scope_path,
                self._normalized_worker,
                concurrent_context,
            ))
        )
        self._scope = MeasurementScope(
            enabled=self._sampled,
            worker_metrics_supported=(
                session.config.worker_metrics_supported and self._worker_metrics
            ),
            concurrent_context=concurrent_context,
        )
        if not self._sampled:
            return self._scope
        try:
            self._memory_start = session._read_memory()
            self._python_start = session._read_python_memory()
            self._process_start = session._read_clock(
                session._process_cpu_clock_ns
                if session.config.capture_process_cpu
                else None
            )
            self._thread_start = session._read_clock(
                session._thread_cpu_clock_ns
                if session.config.capture_thread_cpu
                else None
            )
            self._wall_start = session._read_clock(session._wall_clock_ns)
            return self._scope
        except BaseException:
            session._scope_stack.reset(self._token)
            self._token = None
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        session = self._session
        try:
            if session.config.enabled and self._sampled:
                try:
                    session._complete_sample(
                        self._scope,
                        phase_id=self._phase_id,
                        scope_path=self._scope_path,
                        consumer=self._normalized_consumer,
                        worker_id=self._normalized_worker,
                        succeeded=exc_type is None,
                        wall_start=self._wall_start,
                        process_start=self._process_start,
                        thread_start=self._thread_start,
                        memory_start=self._memory_start,
                        python_start=self._python_start,
                    )
                except Exception:
                    # Operational instrumentation must never alter an analysis
                    # result or mask the original application exception.
                    pass
        finally:
            self._scope._close()
            if self._token is not None:
                session._scope_stack.reset(self._token)
                self._token = None
        return False


class _DisabledMeasurementScopeContext(AbstractContextManager[MeasurementScope]):
    """Allocation-light reusable scope used by the default disabled session."""

    def __init__(self) -> None:
        self._scope = MeasurementScope(
            enabled=False,
            worker_metrics_supported=False,
            concurrent_context=False,
        )

    def __enter__(self) -> MeasurementScope:
        return self._scope

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        return False


def _missing(unit: MetricUnit, reason: MetricReason) -> MetricValue:
    return MetricValue.unavailable(unit, reason)


def _disabled_memory() -> ProcessMemoryReading:
    value = _missing(MetricUnit.BYTES, MetricReason.COLLECTION_DISABLED)
    return ProcessMemoryReading(value, value, value)


class MeasurementSession:
    """Collect measurements for one run without process-global collector state."""

    def __init__(
        self,
        config: MeasurementConfig | None = None,
        *,
        wall_clock_ns: Callable[[], int] = perf_counter_ns,
        process_cpu_clock_ns: Callable[[], int] = process_time_ns,
        thread_cpu_clock_ns: Callable[[], int] | None = getattr(time, "thread_time_ns", None),
        thread_identifier: Callable[[], int] = get_ident,
        memory_probe: ProcessMemoryProbe | None = None,
    ) -> None:
        self.config = config or MeasurementConfig()
        self.filesystem = FilesystemLedger(
            enabled=self.config.enabled and self.config.capture_filesystem,
            resource_limit=self.config.filesystem_resource_limit,
        )
        self._wall_clock_ns = wall_clock_ns
        self._process_cpu_clock_ns = process_cpu_clock_ns
        self._thread_cpu_clock_ns = thread_cpu_clock_ns
        self._thread_identifier = thread_identifier
        self._memory_probe = memory_probe or CurrentProcessMemoryProbe()
        self._samples: list[MeasurementSample] = []
        self._eligible_scopes = 0
        self._sampled_scopes = 0
        self._eligible_scopes_by_phase: dict[str, int] = {}
        self._sampled_scopes_by_phase: dict[str, int] = {}
        self._lock = RLock()
        self._disabled_scope = _DisabledMeasurementScopeContext()
        self._scope_stack: ContextVar[tuple[_ActiveScope, ...]] = ContextVar(
            "atlas_measurement_scope_stack",
            default=(),
        )

    def scope(
        self,
        phase: MeasurementPhase | str,
        *,
        consumer: str = "atlas",
        worker_id: str | None = None,
        sample_key: str | None = None,
        worker_metrics: bool = False,
    ) -> AbstractContextManager[MeasurementScope]:
        """Measure a nested operation and always preserve the operation outcome.

        ``sample_key`` is required only when deterministic down-sampling is
        configured.  It is hashed for selection and is never retained.
        """

        if not self.config.enabled:
            return self._disabled_scope
        return _MeasurementScopeContext(
            self,
            phase,
            consumer=consumer,
            worker_id=worker_id,
            sample_key=sample_key,
            worker_metrics=worker_metrics,
        )

    def _complete_sample(
        self,
        scope: MeasurementScope,
        *,
        phase_id: str,
        scope_path: tuple[str, ...],
        consumer: str,
        worker_id: str,
        succeeded: bool,
        wall_start: int | None,
        process_start: int | None,
        thread_start: int | None,
        memory_start: ProcessMemoryReading,
        python_start: tuple[MetricValue, MetricValue],
    ) -> None:
        wall_end = self._read_clock(self._wall_clock_ns)
        thread_end = self._read_clock(
            self._thread_cpu_clock_ns if self.config.capture_thread_cpu else None
        )
        process_end = self._read_clock(
            self._process_cpu_clock_ns if self.config.capture_process_cpu else None
        )
        python_end = self._read_python_memory()
        memory_end = self._read_memory()
        metrics = self._metrics(
            scope,
            wall_start=wall_start,
            wall_end=wall_end,
            process_start=process_start,
            process_end=process_end,
            thread_start=thread_start,
            thread_end=thread_end,
            memory_start=memory_start,
            memory_end=memory_end,
            python_start=python_start,
            python_end=python_end,
        )
        try:
            observed_thread_id = self._thread_identifier()
            thread_id = (
                observed_thread_id
                if isinstance(observed_thread_id, int)
                and not isinstance(observed_thread_id, bool)
                and observed_thread_id >= 0
                else 0
            )
        except Exception:
            thread_id = 0
        sample = MeasurementSample(
            phase_id=phase_id,
            scope_path=scope_path,
            consumer=consumer,
            worker_id=worker_id,
            thread_id=thread_id,
            succeeded=succeeded,
            metrics=tuple(metrics.items()),
        )
        with self._lock:
            self._samples.append(sample)

    def report(self) -> MeasurementReport:
        with self._lock:
            samples = tuple(self._samples)
            eligible_scopes = self._eligible_scopes
            sampled_scopes = self._sampled_scopes
            eligible_by_phase = dict(self._eligible_scopes_by_phase)
            sampled_by_phase = dict(self._sampled_scopes_by_phase)
        filesystem = (
            self.filesystem.snapshot()
            if self.config.enabled
            else FilesystemLedgerSnapshot()
        )
        sampling = MeasurementSampling(
            (
                MetricStatus.MEASURED
                if self.config.enabled
                else MetricStatus.UNAVAILABLE
            ),
            self.config.sample_every,
            eligible_scopes,
            sampled_scopes,
            tuple(
                MeasurementPhaseSampling(
                    phase_id,
                    eligible,
                    sampled_by_phase.get(phase_id, 0),
                )
                for phase_id, eligible in eligible_by_phase.items()
            ),
        )
        return MeasurementReport(
            samples=samples,
            filesystem=filesystem,
            sampling=sampling,
        )

    def clear(self) -> int:
        with self._lock:
            count = len(self._samples)
            self._samples.clear()
            self._eligible_scopes = 0
            self._sampled_scopes = 0
            self._eligible_scopes_by_phase.clear()
            self._sampled_scopes_by_phase.clear()
        self.filesystem.clear()
        return count

    def _should_sample(
        self,
        scope_path: tuple[str, ...],
        consumer: str,
        sample_key: str | None,
    ) -> bool:
        if self.config.sample_every == 1:
            selected = True
        else:
            if sample_key is None:
                raise ValueError(
                    "sample_key is required for deterministic measurement sampling"
                )
            # Worker assignment is intentionally excluded: thread-pool scheduling is
            # operationally nondeterministic and must not change sample selection.
            preimage = "\x00".join((*scope_path, consumer, sample_key))
            digest = hashlib.sha256(preimage.encode("utf-8")).digest()
            selected = (
                int.from_bytes(digest[:8], "big")
                % self.config.sample_every
                == 0
            )
        with self._lock:
            self._eligible_scopes += 1
            phase_id = scope_path[-1]
            self._eligible_scopes_by_phase[phase_id] = (
                self._eligible_scopes_by_phase.get(phase_id, 0) + 1
            )
            if selected:
                self._sampled_scopes += 1
                self._sampled_scopes_by_phase[phase_id] = (
                    self._sampled_scopes_by_phase.get(phase_id, 0) + 1
                )
        return selected

    @staticmethod
    def _read_clock(clock: Callable[[], int] | None) -> int | None:
        if clock is None:
            return None
        try:
            value = clock()
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                return None
            return value
        except Exception:
            return None

    def _read_memory(self) -> ProcessMemoryReading:
        if not self.config.capture_process_memory:
            return _disabled_memory()
        try:
            reading = self._memory_probe.read()
            values = (
                reading.rss_bytes,
                reading.working_set_bytes,
                reading.commit_bytes,
            ) if isinstance(reading, ProcessMemoryReading) else ()
            if not values or not all(self._valid_absolute_memory(item) for item in values):
                raise TypeError("memory probe returned an invalid reading")
            return reading
        except Exception:
            value = _missing(MetricUnit.BYTES, MetricReason.PROVIDER_UNAVAILABLE)
            return ProcessMemoryReading(value, value, value)

    @staticmethod
    def _valid_absolute_memory(value: object) -> bool:
        if not isinstance(value, MetricValue) or value.unit is not MetricUnit.BYTES:
            return False
        if value.status is not MetricStatus.MEASURED:
            return True
        return (
            isinstance(value.value, int)
            and not isinstance(value.value, bool)
            and value.value >= 0
        )

    def _read_python_memory(self) -> tuple[MetricValue, MetricValue]:
        if not self.config.capture_python_memory:
            value = _missing(MetricUnit.BYTES, MetricReason.COLLECTION_DISABLED)
            return value, value
        if not tracemalloc.is_tracing():
            value = _missing(MetricUnit.BYTES, MetricReason.TRACEMALLOC_INACTIVE)
            return value, value
        try:
            current, peak = tracemalloc.get_traced_memory()
            if (
                not isinstance(current, int)
                or isinstance(current, bool)
                or current < 0
                or not isinstance(peak, int)
                or isinstance(peak, bool)
                or peak < current
            ):
                raise ValueError("invalid tracemalloc reading")
            return (
                MetricValue.measured(current, MetricUnit.BYTES),
                MetricValue.measured(peak, MetricUnit.BYTES),
            )
        except Exception:
            value = _missing(MetricUnit.BYTES, MetricReason.PROVIDER_UNAVAILABLE)
            return value, value

    def _duration(
        self,
        start: int | None,
        end: int | None,
        *,
        configured: bool,
        unsupported: bool = False,
    ) -> MetricValue:
        if not configured:
            return _missing(MetricUnit.NANOSECONDS, MetricReason.COLLECTION_DISABLED)
        if unsupported:
            return MetricValue.unsupported(
                MetricUnit.NANOSECONDS,
                MetricReason.RUNTIME_UNSUPPORTED,
            )
        if start is None or end is None:
            return _missing(MetricUnit.NANOSECONDS, MetricReason.PROVIDER_UNAVAILABLE)
        if end < start:
            return _missing(MetricUnit.NANOSECONDS, MetricReason.PROVIDER_UNAVAILABLE)
        return MetricValue.measured(end - start, MetricUnit.NANOSECONDS)

    @staticmethod
    def _delta(start: MetricValue, end: MetricValue) -> MetricValue:
        if (
            start.status is MetricStatus.MEASURED
            and end.status is MetricStatus.MEASURED
            and start.value is not None
            and end.value is not None
        ):
            return MetricValue.measured(end.value - start.value, end.unit)
        missing = next(
            item for item in (end, start) if item.status is not MetricStatus.MEASURED
        )
        assert missing.reason is not None
        return MetricValue(missing.status, missing.unit, reason=missing.reason)

    def _metrics(
        self,
        scope: MeasurementScope,
        *,
        wall_start: int | None,
        wall_end: int | None,
        process_start: int | None,
        process_end: int | None,
        thread_start: int | None,
        thread_end: int | None,
        memory_start: ProcessMemoryReading,
        memory_end: ProcessMemoryReading,
        python_start: tuple[MetricValue, MetricValue],
        python_end: tuple[MetricValue, MetricValue],
    ) -> dict[str, MetricValue]:
        wall = self._duration(wall_start, wall_end, configured=True)
        process_cpu = self._duration(
            process_start,
            process_end,
            configured=self.config.capture_process_cpu,
        )
        if scope._concurrent_context:
            process_cpu = _missing(
                MetricUnit.NANOSECONDS,
                MetricReason.CONCURRENT_ATTRIBUTION,
            )
        thread_cpu = self._duration(
            thread_start,
            thread_end,
            configured=self.config.capture_thread_cpu,
            unsupported=self.config.capture_thread_cpu and self._thread_cpu_clock_ns is None,
        )
        if scope._concurrent_context:
            utilization = _missing(
                MetricUnit.PERCENT,
                MetricReason.CONCURRENT_ATTRIBUTION,
            )
        elif wall.status is not MetricStatus.MEASURED:
            assert wall.reason is not None
            utilization = MetricValue(
                wall.status,
                MetricUnit.PERCENT,
                reason=wall.reason,
            )
        elif process_cpu.status is not MetricStatus.MEASURED:
            assert process_cpu.reason is not None
            utilization = MetricValue(
                process_cpu.status,
                MetricUnit.PERCENT,
                reason=process_cpu.reason,
            )
        elif wall.value == 0:
            utilization = _missing(MetricUnit.PERCENT, MetricReason.ZERO_WALL_TIME)
        else:
            assert wall.value is not None and process_cpu.value is not None
            utilization = MetricValue.measured(
                float(process_cpu.value) * 100.0 / float(wall.value),
                MetricUnit.PERCENT,
            )

        not_recorded_count = _missing(MetricUnit.COUNT, MetricReason.NOT_RECORDED)
        metrics: dict[str, MetricValue] = {
            "wall_time_ns": wall,
            "process_cpu_time_ns": process_cpu,
            "thread_cpu_time_ns": thread_cpu,
            "process_utilization_percent": utilization,
            "rss_bytes": memory_end.rss_bytes,
            "rss_delta_bytes": self._delta(memory_start.rss_bytes, memory_end.rss_bytes),
            "working_set_bytes": memory_end.working_set_bytes,
            "working_set_delta_bytes": self._delta(
                memory_start.working_set_bytes,
                memory_end.working_set_bytes,
            ),
            "commit_bytes": memory_end.commit_bytes,
            "commit_delta_bytes": self._delta(
                memory_start.commit_bytes,
                memory_end.commit_bytes,
            ),
            "python_allocated_bytes": python_end[0],
            "python_allocated_delta_bytes": self._delta(python_start[0], python_end[0]),
            "python_peak_allocated_bytes": python_end[1],
            "units_processed": not_recorded_count,
            "bytes_processed": _missing(MetricUnit.BYTES, MetricReason.NOT_RECORDED),
            "objects_produced": not_recorded_count,
            "objects_retained": not_recorded_count,
        }
        for name, value in scope._work.items():
            unit = MetricUnit.BYTES if name == "bytes_processed" else MetricUnit.COUNT
            metrics[name] = MetricValue.measured(value, unit)

        worker_metrics_supported = scope._worker_metrics_supported
        worker_reason = (
            MetricReason.NOT_RECORDED
            if worker_metrics_supported
            else MetricReason.RUNTIME_UNSUPPORTED
        )
        worker_status = (
            MetricStatus.UNAVAILABLE
            if worker_metrics_supported
            else MetricStatus.UNSUPPORTED
        )
        for name, unit in (
            ("queue_wait_ns", MetricUnit.NANOSECONDS),
            ("service_time_ns", MetricUnit.NANOSECONDS),
            ("idle_time_ns", MetricUnit.NANOSECONDS),
            ("queue_depth", MetricUnit.COUNT),
        ):
            metrics[name] = MetricValue(worker_status, unit, reason=worker_reason)
        if worker_metrics_supported:
            metrics["service_time_ns"] = wall
            for name, value in scope._worker.items():
                if name == "service_time_ns":
                    continue
                unit = MetricUnit.COUNT if name == "queue_depth" else MetricUnit.NANOSECONDS
                metrics[name] = MetricValue.measured(value, unit)
        return metrics
