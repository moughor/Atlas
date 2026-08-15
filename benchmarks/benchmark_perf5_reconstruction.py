"""Focused PERF5 profiler for strict persisted PR157 reconstruction.

The target must already have a configured-active snapshot.  This benchmark only
loads that snapshot and reconstructs persisted artifacts; it never analyzes source
or writes snapshot/benchmark output files.  Normal wall time, instrumented phase
time, and cProfile time are separate modes because instrumentation is deliberately
diagnostic and may inflate the measured operation.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack, nullcontext
import ctypes
from ctypes import wintypes
import cProfile
import gc
import io
import json
from pathlib import Path
import pstats
import sys
from threading import Event, Thread
from time import perf_counter
from typing import Any, Callable, Mapping
from unittest.mock import patch

_SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from moughorai.code_intelligence import JavaCodeIntelligenceService
from moughorai.java_code_intelligence._validation import (
    reconstruction_validation_scope,
)
from moughorai.java_code_intelligence.call_sites import (
    CallResolutionState,
    CallSiteEvidence,
    CallSiteRequest,
)
import moughorai.java_code_intelligence.code_graph as graph_module
from moughorai.java_code_intelligence.models import SourcePosition, SourceRange
from moughorai.java_code_intelligence.persistence import callable_index_from_dict
from moughorai.java_code_intelligence.test_evidence import (
    java_test_evidence_from_dict,
)
from moughorai.reachability.models import DeadCodeReport
from moughorai.semantic_snapshot import SnapshotResolver


class _ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


_PSAPI = ctypes.WinDLL("psapi", use_last_error=True)
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_PSAPI.GetProcessMemoryInfo.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_ProcessMemoryCountersEx),
    wintypes.DWORD,
]
_PSAPI.GetProcessMemoryInfo.restype = wintypes.BOOL
_KERNEL32.GetCurrentProcess.restype = wintypes.HANDLE
_PROCESS_HANDLE = _KERNEL32.GetCurrentProcess()


def _memory() -> dict[str, int | None]:
    counters = _ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(counters)
    if not _PSAPI.GetProcessMemoryInfo(
        _PROCESS_HANDLE, ctypes.byref(counters), counters.cb
    ):
        return {"working_set_bytes": None, "private_bytes": None}
    return {
        "working_set_bytes": int(counters.WorkingSetSize),
        "private_bytes": int(counters.PrivateUsage),
    }


class _Recorder:
    def __init__(self) -> None:
        self.timings: dict[str, dict[str, float | int]] = {}
        self._gc_started: dict[int, float] = {}
        self.gc = {"collections": 0, "seconds": 0.0}

    def add(self, name: str, seconds: float) -> None:
        target = self.timings.setdefault(name, {"calls": 0, "seconds": 0.0})
        target["calls"] = int(target["calls"]) + 1
        target["seconds"] = float(target["seconds"]) + seconds

    def call(self, name: str, function: Callable[[], Any]) -> Any:
        started = perf_counter()
        try:
            return function()
        finally:
            self.add(name, perf_counter() - started)

    def gc_callback(self, phase: str, info: dict[str, Any]) -> None:
        generation = int(info.get("generation", -1))
        if phase == "start":
            self._gc_started[generation] = perf_counter()
            return
        started = self._gc_started.pop(generation, None)
        if started is not None:
            self.gc["collections"] = int(self.gc["collections"]) + 1
            self.gc["seconds"] = float(self.gc["seconds"]) + perf_counter() - started


def _timed(
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


def _instrumentation(recorder: _Recorder) -> ExitStack:
    stack = ExitStack()

    original_table = graph_module._table

    def table(value: object, label: str) -> tuple[str, ...]:
        return recorder.call(
            f"table_decode:{label}", lambda: original_table(value, label)
        )

    original_row = graph_module._row

    def row(value: object, label: str) -> tuple[object, ...]:
        return recorder.call(f"compact_decode:{label}", lambda: original_row(value, label))

    original_refs = graph_module._refs

    def refs(value: object, values: Any, label: str) -> tuple[int, ...]:
        return recorder.call(
            f"reference_list:{label}", lambda: original_refs(value, values, label)
        )

    stack.enter_context(patch.object(graph_module, "_table", table))
    stack.enter_context(patch.object(graph_module, "_row", row))
    stack.enter_context(patch.object(graph_module, "_refs", refs))
    for name in (
        "_canonical_row",
        "_call_site_row",
        "_validated_call_site_row",
        "_reconstructed_call_site",
        "_reference_values",
        "_call_evidence_id",
        "_site_row",
        "_edge_row",
        "_diagnostic_row",
        "_validate_strict_order",
        "_validate_callable_binding",
        "_validate_site_accounting",
        "_projection_tables",
        "_edges",
        "_digest",
    ):
        original = getattr(graph_module, name)
        stack.enter_context(patch.object(
            graph_module, name, _timed(recorder, name, original)
        ))
    for model, name in (
        (CallSiteRequest, "CallSiteRequest.__post_init__"),
        (CallSiteEvidence, "CallSiteEvidence.__post_init__"),
        (SourcePosition, "SourcePosition.__post_init__"),
        (SourceRange, "SourceRange.__post_init__"),
    ):
        original = model.__post_init__
        stack.enter_context(patch.object(
            model, "__post_init__", _timed(recorder, name, original)
        ))
    original_create = CallSiteEvidence.__dict__["create"].__func__
    stack.enter_context(patch.object(
        CallSiteEvidence,
        "create",
        classmethod(_timed(recorder, "CallSiteEvidence.create", original_create)),
    ))
    return stack


class _PeakSampler:
    def __init__(self) -> None:
        self.stop = Event()
        self.peak = {"working_set_bytes": 0, "private_bytes": 0}
        self.thread = Thread(target=self._sample, name="perf5-memory", daemon=True)

    def _sample(self) -> None:
        while not self.stop.wait(0.02):
            reading = _memory()
            for name, value in reading.items():
                if value is not None:
                    self.peak[name] = max(self.peak[name], value)

    def __enter__(self) -> _PeakSampler:
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop.set()
        self.thread.join()


def _profile_text(profile: cProfile.Profile) -> dict[str, str]:
    reports = {}
    for name, ordering in (("cumulative", "cumulative"), ("self_time", "tottime")):
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).strip_dirs().sort_stats(ordering).print_stats(60)
        reports[name] = stream.getvalue()
    return reports


def _string_references(graph: Any) -> dict[str, int]:
    references = 0
    identities: set[int] = set()
    values: set[str] = set()
    for site in graph.call_sites:
        request = site.request
        strings = (
            request.caller_subject_id,
            request.caller_normalized_key,
            request.project_id,
            request.source_path,
            request.member_name,
            *((request.receiver,) if request.receiver is not None else ()),
            *request.owner_type_hints,
            *request.argument_hints,
            *request.limitations,
            *((site.target_subject_id,) if site.target_subject_id is not None else ()),
            *((site.declared_target_id,) if site.declared_target_id is not None else ()),
            *site.candidate_target_ids,
            *site.limitations,
            site.evidence_id,
        )
        references += len(strings)
        identities.update(id(item) for item in strings)
        values.update(strings)
    return {
        "references": references,
        "unique_object_identities": len(identities),
        "unique_values": len(values),
        "duplicate_equal_object_identities": len(identities) - len(values),
    }


def _object_profile(graph: Any, service: JavaCodeIntelligenceService) -> dict[str, Any]:
    sites = graph.call_sites
    ranges = {id(item.request.source_range) for item in sites}
    positions = {
        id(position)
        for item in sites
        for position in (item.request.source_range.start, item.request.source_range.end)
    }
    candidate_tuples = {id(item.candidate_target_ids) for item in sites}
    request_limitation_tuples = {id(item.request.limitations) for item in sites}
    evidence_limitation_tuples = {id(item.limitations) for item in sites}
    tuple_shallow_bytes = sum(
        sys.getsizeof(value)
        for item in sites
        for value in (
            item.request.owner_type_hints,
            item.request.argument_hints,
            item.request.limitations,
            item.candidate_target_ids,
            item.limitations,
        )
    )
    sample = sites[0] if sites else None
    return {
        "counts": {
            "CallSiteEvidence": len(sites),
            "CallSiteRequest": len(sites),
            "SourceRange_unique": len(ranges),
            "SourcePosition_unique": len(positions),
            "candidate_target_tuple_unique": len(candidate_tuples),
            "candidate_target_references": sum(len(item.candidate_target_ids) for item in sites),
            "request_limitation_tuple_unique": len(request_limitation_tuples),
            "evidence_limitation_tuple_unique": len(evidence_limitation_tuples),
            "CodeGraphEdge": len(graph.edges),
            "CodeGraphDiagnostic": len(graph.diagnostics),
        },
        "representative_shallow_bytes": {
            "CallSiteEvidence": sys.getsizeof(sample) if sample is not None else 0,
            "CallSiteRequest": sys.getsizeof(sample.request) if sample is not None else 0,
            "SourceRange": sys.getsizeof(sample.request.source_range) if sample is not None else 0,
            "SourcePosition": sys.getsizeof(sample.request.source_range.start) if sample is not None else 0,
            "CodeGraphEdge": sys.getsizeof(graph.edges[0]) if graph.edges else 0,
        },
        "five_site_tuple_shallow_bytes": tuple_shallow_bytes,
        "strings": _string_references(graph),
        "service_indexes": {
            "entries": len(service._entries),
            "sites": len(service._sites),
            "incoming_keys": len(service._incoming),
            "outgoing_keys": len(service._outgoing),
            "sites_by_caller_keys": len(service._sites_by_caller),
            "test_records": len(service._test_records),
            "exact_name_keys": len(service._exact_names),
            "shallow_dict_bytes": sum(sys.getsizeof(value) for value in (
                service._entries,
                service._sites,
                service._incoming,
                service._outgoing,
                service._sites_by_caller,
                service._test_records,
                service._exact_names,
            )),
        },
    }


def run(
    workspace: Path,
    *,
    instrument: bool = False,
    profile_enabled: bool = False,
    object_profile: bool = False,
) -> dict[str, Any]:
    resolution = SnapshotResolver(workspace).resolve()
    context = resolution.snapshot.semantic_context
    raw_index = context.get("java_callable_index")
    raw_graph = context.get("java_code_graph")
    raw_tests = context.get("java_test_evidence")
    if not all(isinstance(item, Mapping) for item in (raw_index, raw_graph, raw_tests)):
        raise RuntimeError("configured snapshot lacks persisted Java artifacts")

    recorder = _Recorder()
    memory = {"before_callable_index": _memory()}
    profiler = cProfile.Profile()
    with reconstruction_validation_scope():
        callable_index = recorder.call(
            "callable_index_reconstruction",
            lambda: callable_index_from_dict(raw_index),
        )
        memory["pre_code_graph"] = _memory()
        stack = _instrumentation(recorder) if instrument else ExitStack()
        gc.callbacks.append(recorder.gc_callback)
        try:
            peak_context = (
                nullcontext(None)
                if instrument or profile_enabled
                else _PeakSampler()
            )
            with stack, peak_context as sampler:
                if profile_enabled:
                    profiler.enable()
                try:
                    code_graph = recorder.call(
                        "code_graph_from_dict",
                        lambda: graph_module.code_graph_from_dict(raw_graph, callable_index),
                    )
                finally:
                    if profile_enabled:
                        profiler.disable()
            memory["code_graph_peak"] = (
                sampler.peak if sampler is not None else None
            )
        finally:
            gc.callbacks.remove(recorder.gc_callback)
        memory["post_code_graph"] = _memory()
        test_evidence = recorder.call(
            "test_evidence_reconstruction",
            lambda: java_test_evidence_from_dict(raw_tests, callable_index),
        )
        raw_reachability = context.get("reachability")
        reachability = recorder.call(
            "reachability_reconstruction",
            lambda: DeadCodeReport.from_dict(raw_reachability),
        ) if isinstance(raw_reachability, Mapping) else None
    memory["pre_java_service"] = _memory()
    service = recorder.call(
        "java_service_reverse_index_construction",
        lambda: JavaCodeIntelligenceService(
            snapshot_id=resolution.snapshot.snapshot_id,
            callable_index=callable_index,
            code_graph=code_graph,
            test_evidence=test_evidence,
            reachability_report=reachability,
        ),
    )
    memory["post_java_service"] = _memory()
    states = Counter(item.state.value for item in code_graph.call_sites)
    edge_kinds = Counter(item.kind.value for item in code_graph.edges)
    result = {
        "mode": {
            "instrumented": instrument,
            "profiled": profile_enabled,
            "object_profiled": object_profile,
        },
        "source_root": str(_SOURCE_ROOT),
        "snapshot": resolution.to_dict(),
        "timings": recorder.timings,
        "gc_during_code_graph": recorder.gc,
        "memory": memory,
        "artifacts": {
            "callable_index_fingerprint": callable_index.input_fingerprint,
            "code_graph_fingerprint": code_graph.input_fingerprint,
            "test_evidence_fingerprint": test_evidence.input_fingerprint,
            "reachability_fingerprint": getattr(reachability, "input_fingerprint", None),
            "call_sites": len(code_graph.call_sites),
            "resolution_states": dict(sorted(states.items())),
            "edges": len(code_graph.edges),
            "edge_kinds": dict(sorted(edge_kinds.items())),
            "diagnostics": len(code_graph.diagnostics),
        },
        "objects": _object_profile(code_graph, service) if object_profile else None,
        "profile": _profile_text(profiler) if profile_enabled else None,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--instrument", action="store_true")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--objects", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(
        run(
            arguments.workspace.expanduser().resolve(),
            instrument=arguments.instrument,
            profile_enabled=arguments.profile,
            object_profile=arguments.objects,
        ),
        ensure_ascii=False,
        sort_keys=True,
    ))


if __name__ == "__main__":
    main()
