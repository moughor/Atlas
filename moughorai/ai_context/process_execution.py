from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from multiprocessing import get_context
from os import getpid
from pathlib import Path
from threading import Lock
from time import monotonic_ns
from types import TracebackType
from typing import Mapping

from moughorai.semantic import SemanticDocument
from moughorai.workspace import Project

from .analyzer_registry import AnalyzerRegistry
from .persistence import (
    decode_analysis_result_bytes,
    encode_analysis_result_bytes,
)


@dataclass(frozen=True, slots=True)
class ProjectAnalysisRequest:
    """Immutable, compact input for one project-local worker task."""

    project_name: str
    project_path: str
    project_dependencies: tuple[str, ...]
    include: tuple[str, ...]
    exclude: tuple[str, ...]
    options: tuple[tuple[str, str], ...]
    available_dependencies: tuple[str, ...]

    @classmethod
    def create(
        cls,
        project: Project,
        dependencies: Mapping[str, object],
    ) -> ProjectAnalysisRequest:
        return cls(
            project.name,
            str(project.path),
            tuple(project.dependencies),
            tuple(project.include),
            tuple(project.exclude),
            tuple(project.options),
            tuple(sorted(dependencies)),
        )

    def project(self) -> Project:
        return Project(
            self.project_name,
            Path(self.project_path),
            self.project_dependencies,
            self.include,
            self.exclude,
            self.options,
        )


@dataclass(frozen=True, slots=True)
class ProjectAnalysisResponse:
    """Source-free worker response plus non-semantic operational observations."""

    project_name: str
    payload: bytes | None
    error: str | None
    worker_pid: int
    analysis_ns: int
    serialization_ns: int


@dataclass(frozen=True, slots=True)
class ProjectProcessMetric:
    """Run-local process observation that never enters semantic output."""

    project_name: str
    worker_pid: int
    round_trip_ns: int
    analysis_ns: int
    serialization_ns: int
    payload_bytes: int

    @property
    def coordination_ns(self) -> int:
        return max(
            0,
            self.round_trip_ns - self.analysis_ns - self.serialization_ns,
        )


class ProjectProcessError(RuntimeError):
    """Preserve the worker analyzer's canonical error text in the parent."""

    def __init__(self, analysis_error: str) -> None:
        super().__init__(analysis_error)
        self.analysis_error = analysis_error


_worker_registry: AnalyzerRegistry | None = None


def initialize_project_analysis_worker() -> None:
    """Create exactly one analyzer registry, and therefore parser, per process."""

    global _worker_registry
    _worker_registry = AnalyzerRegistry()


def analyze_project_request(
    request: ProjectAnalysisRequest,
) -> ProjectAnalysisResponse:
    """Spawn-safe top-level entry point for project-local Atlas analysis."""

    global _worker_registry
    if _worker_registry is None:
        initialize_project_analysis_worker()
    registry = _worker_registry
    if registry is None:  # pragma: no cover - defensive initialization guard
        raise RuntimeError("project analyzer worker failed to initialize")

    analysis_started = monotonic_ns()
    try:
        document = registry(
            request.project(),
            {name: None for name in request.available_dependencies},
        )
    except Exception as exc:
        analysis_ns = monotonic_ns() - analysis_started
        return ProjectAnalysisResponse(
            request.project_name,
            None,
            f"{type(exc).__name__}: {exc}",
            getpid(),
            analysis_ns,
            0,
        )

    analysis_ns = monotonic_ns() - analysis_started
    serialization_started = monotonic_ns()
    try:
        payload = encode_analysis_result_bytes(document)
    except Exception as exc:
        return ProjectAnalysisResponse(
            request.project_name,
            None,
            f"{type(exc).__name__}: {exc}",
            getpid(),
            analysis_ns,
            monotonic_ns() - serialization_started,
        )
    return ProjectAnalysisResponse(
        request.project_name,
        payload,
        None,
        getpid(),
        analysis_ns,
        monotonic_ns() - serialization_started,
    )


class ProcessProjectAnalyzer:
    """Process-backed callable compatible with the workspace scheduler."""

    def __init__(self, max_workers: int) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self.max_workers = max_workers
        self._executor = ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=get_context("spawn"),
            initializer=initialize_project_analysis_worker,
        )
        self._lock = Lock()
        self._metrics: list[ProjectProcessMetric] = []
        self._closed = False

    @property
    def task_metrics(self) -> tuple[ProjectProcessMetric, ...]:
        with self._lock:
            return tuple(self._metrics)

    @property
    def worker_pids(self) -> tuple[int, ...]:
        return tuple(sorted({item.worker_pid for item in self.task_metrics}))

    def __call__(
        self,
        project: Project,
        dependencies: Mapping[str, object],
    ) -> SemanticDocument:
        with self._lock:
            if self._closed:
                raise RuntimeError("process project analyzer is closed")
        request = ProjectAnalysisRequest.create(project, dependencies)
        started = monotonic_ns()
        response = self._executor.submit(
            analyze_project_request,
            request,
        ).result()
        round_trip_ns = monotonic_ns() - started
        if response.project_name != project.name:
            raise RuntimeError(
                "process project analysis returned a mismatched project result"
            )
        payload_bytes = len(response.payload) if response.payload is not None else 0
        metric = ProjectProcessMetric(
            project.name,
            response.worker_pid,
            round_trip_ns,
            response.analysis_ns,
            response.serialization_ns,
            payload_bytes,
        )
        with self._lock:
            self._metrics.append(metric)
        if response.error is not None:
            raise ProjectProcessError(response.error)
        if response.payload is None:
            raise RuntimeError("process project analysis returned no payload")
        return decode_analysis_result_bytes(response.payload)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)

    def __enter__(self) -> ProcessProjectAnalyzer:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
