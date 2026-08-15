"""Phase and memory profiler for PERF4 persisted-runtime reconstruction.

The target must already have a configured-active snapshot.  This diagnostic never
analyzes the workspace and never writes snapshot or benchmark output files.
"""

from __future__ import annotations

import argparse
import cProfile
from contextlib import ExitStack
import gc
import hashlib
import io
import json
from pathlib import Path
import pstats
from time import perf_counter
from typing import Any, Callable
from unittest.mock import patch

from moughorai.atlas_cli import _engineering_answer_name_resolver
from moughorai.code_intelligence import (
    CodeIntelligenceConfiguration,
    JavaCodeIntelligenceService,
)
import moughorai.code_intelligence.service as code_service_module
from moughorai.engineering_answer import (
    EngineeringAnswerConfiguration,
    EngineeringAnswerService,
    EngineeringAnswerView,
    render_engineering_answer,
)
from moughorai.measurement.probes import CurrentProcessMemoryProbe
from moughorai.repository_runtime import RepositoryRuntimeSession
from moughorai.semantic_search import SemanticSearchRequest
import moughorai.semantic_snapshot.models as snapshot_models
import moughorai.semantic_snapshot.store as snapshot_store
from moughorai.semantic_snapshot import SnapshotResolver


_SEARCH_CONFIGURATION = CodeIntelligenceConfiguration(
    max_depth=1,
    max_nodes=1,
    max_direct_relationships=1,
    max_paths_per_section=1,
    max_limitation_representatives=1,
    max_resolution_candidates=1,
    max_candidates_per_call_site=1,
)


def _memory() -> dict[str, int | None]:
    reading = CurrentProcessMemoryProbe().read()
    return {
        "working_set_bytes": reading.working_set_bytes.value,
        "private_bytes": reading.commit_bytes.value,
    }


class _Recorder:
    def __init__(self) -> None:
        self.timings: dict[str, dict[str, float | int]] = {}
        self._active_phase = "unattributed"
        self._gc_started: dict[int, float] = {}
        self._gc: dict[str, dict[str, float | int]] = {}

    def start_gc(self) -> None:
        gc.callbacks.append(self._gc_callback)

    def stop_gc(self) -> None:
        gc.callbacks.remove(self._gc_callback)

    def _gc_callback(self, phase: str, info: dict[str, Any]) -> None:
        generation = int(info.get("generation", -1))
        if phase == "start":
            self._gc_started[generation] = perf_counter()
            return
        started = self._gc_started.pop(generation, None)
        if started is None:
            return
        target = self._gc.setdefault(
            self._active_phase, {"collections": 0, "seconds": 0.0}
        )
        target["collections"] = int(target["collections"]) + 1
        target["seconds"] = float(target["seconds"]) + perf_counter() - started

    def add(self, name: str, seconds: float) -> None:
        target = self.timings.setdefault(name, {"calls": 0, "seconds": 0.0})
        target["calls"] = int(target["calls"]) + 1
        target["seconds"] = float(target["seconds"]) + seconds

    def call(self, name: str, function: Callable[[], Any]) -> Any:
        previous = self._active_phase
        self._active_phase = name
        started = perf_counter()
        try:
            return function()
        finally:
            self.add(name, perf_counter() - started)
            self._active_phase = previous

    @property
    def gc(self) -> dict[str, dict[str, float | int]]:
        return self._gc


def _timed_wrapper(
    recorder: _Recorder,
    name: str,
    original: Callable[..., Any],
) -> Callable[..., Any]:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        started = perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            recorder.add(name, perf_counter() - started)

    return wrapped


def _resolve_snapshot(workspace: Path, recorder: _Recorder):
    original_read_text = Path.read_text
    original_loads = snapshot_store.json.loads
    original_outer_canonical = snapshot_store.canonical_json
    original_inner_canonical = snapshot_models.canonical_json

    def read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        name = (
            "ass_file_open_read"
            if path.name == "latest.ass"
            else "snapshot_registration_read"
        )
        started = perf_counter()
        try:
            return original_read_text(path, *args, **kwargs)
        finally:
            recorder.add(name, perf_counter() - started)

    def loads(value: Any, *args: Any, **kwargs: Any) -> Any:
        name = (
            "outer_snapshot_decode"
            if isinstance(value, str) and len(value) > 1_000_000
            else "snapshot_registration_decode"
        )
        started = perf_counter()
        try:
            return original_loads(value, *args, **kwargs)
        finally:
            recorder.add(name, perf_counter() - started)

    with ExitStack() as stack:
        stack.enter_context(patch.object(Path, "read_text", read_text))
        stack.enter_context(patch.object(snapshot_store.json, "loads", loads))
        stack.enter_context(patch.object(
            snapshot_store,
            "canonical_json",
            _timed_wrapper(
                recorder, "outer_snapshot_checksum", original_outer_canonical
            ),
        ))
        stack.enter_context(patch.object(
            snapshot_models,
            "canonical_json",
            _timed_wrapper(
                recorder, "snapshot_identity_validation", original_inner_canonical
            ),
        ))
        return recorder.call(
            "snapshot_resolution",
            lambda: SnapshotResolver(workspace).resolve(),
        )


def _profile_text(profile: cProfile.Profile) -> dict[str, str]:
    reports = {}
    for key, ordering in (("cumulative", "cumulative"), ("self_time", "tottime")):
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).strip_dirs().sort_stats(ordering).print_stats(40)
        reports[key] = stream.getvalue()
    return reports


def run(workspace: Path, *, profile_enabled: bool = False) -> dict[str, Any]:
    recorder = _Recorder()
    profiler = cProfile.Profile()
    memory = {"before_snapshot_load": _memory()}
    recorder.start_gc()
    if profile_enabled:
        profiler.enable()
    runtime_session: RepositoryRuntimeSession | None = None
    try:
        resolution = _resolve_snapshot(workspace, recorder)
        snapshot = resolution.snapshot
        memory["after_snapshot_load"] = _memory()

        runtime_session = RepositoryRuntimeSession(workspace_root=workspace)
        runtime = recorder.call(
            "repository_runtime_construction",
            lambda: runtime_session.runtime_for(snapshot),
        )
        memory["after_runtime_construction"] = _memory()

        recorder.call("canonical_subject_resolver_construction", lambda: runtime.resolver)
        memory["after_canonical_subject_resolver"] = _memory()
        search_service = recorder.call(
            "semantic_search_index_projection_construction",
            lambda: runtime.semantic_search,
        )
        memory["after_semantic_search"] = _memory()
        search_response = recorder.call(
            "first_search_query",
            lambda: search_service.search_semantic(
                SemanticSearchRequest("mapEventToSepJmsEvent", limit=10)
            ),
        )
        if not search_response.hits:
            raise RuntimeError("accepted target search returned no hits")
        hit = search_response.hits[0]

        originals = {
            "callable_index_reconstruction": code_service_module.callable_index_from_dict,
            "java_code_graph_reconstruction": code_service_module.code_graph_from_dict,
            "test_evidence_reconstruction": code_service_module.java_test_evidence_from_dict,
        }
        with ExitStack() as stack:
            for name, original in originals.items():
                stack.enter_context(patch.object(
                    code_service_module,
                    original.__name__,
                    _timed_wrapper(recorder, name, original),
                ))
            original_init = JavaCodeIntelligenceService.__init__
            stack.enter_context(patch.object(
                JavaCodeIntelligenceService,
                "__init__",
                _timed_wrapper(
                    recorder, "java_service_reverse_index_construction", original_init
                ),
            ))
            java_service = recorder.call(
                "java_code_intelligence_construction",
                lambda: runtime.java_code_intelligence,
            )
        memory["after_java_code_intelligence"] = _memory()

        selected = recorder.call(
            "search_java_identity_projection",
            lambda: java_service.query(
                hit.canonical_subject_id,
                configuration=_SEARCH_CONFIGURATION,
            ),
        )
        subject = selected.resolution.subject
        if subject is None:
            raise RuntimeError("accepted target did not resolve to a Java callable")

        answer = recorder.call(
            "first_answer_query",
            lambda: EngineeringAnswerService(java_service).query(
                subject.canonical_id,
                project=subject.project,
                configuration=EngineeringAnswerConfiguration(
                    max_depth=8,
                    max_nodes=4_096,
                    max_representatives_per_section=8,
                    max_limitation_representatives=4,
                    max_candidates_per_call_site=5,
                    max_inspect_items=16,
                ),
            ),
        )
        name_resolver = _engineering_answer_name_resolver(java_service)
        rendered = {
            view.value: render_engineering_answer(
                answer,
                view=view,
                name_resolver=name_resolver,
            )
            for view in EngineeringAnswerView
        }
        memory["after_first_answer"] = _memory()
        if profile_enabled:
            profiler.disable()

        return {
            "snapshot": resolution.to_dict(),
            "timings": recorder.timings,
            "gc": recorder.gc,
            "memory": memory,
            "search": {
                "hit_count": len(search_response.hits),
                "first_canonical_subject_id": hit.canonical_subject_id,
                "first_project": hit.project,
            },
            "output_hashes": {
                name: hashlib.sha256(value.encode("utf-8")).hexdigest()
                for name, value in rendered.items()
            },
            "runtime_statistics": {
                "runtime_build_count": runtime_session.statistics.runtime_build_count,
                "reuse_count": runtime_session.statistics.reuse_count,
                "component_build_counts": dict(
                    runtime_session.statistics.component_build_counts
                ),
            },
            "profile": _profile_text(profiler) if profile_enabled else None,
        }
    finally:
        if profile_enabled:
            profiler.disable()
        recorder.stop_gc()
        if runtime_session is not None:
            runtime_session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--profile", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(
        run(arguments.workspace.expanduser().resolve(), profile_enabled=arguments.profile),
        ensure_ascii=False,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
