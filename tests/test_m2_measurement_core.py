from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
from threading import Thread

import pytest
from jsonschema import Draft202012Validator

from moughorai.measurement import (
    CurrentProcessMemoryProbe,
    FilesystemConsumerMetrics,
    FilesystemConsumerOverlap,
    FilesystemLedger,
    FilesystemLedgerSnapshot,
    FilesystemOperation,
    MeasurementConfig,
    MeasurementPhase,
    MeasurementReport,
    MeasurementSampling,
    MeasurementSession,
    MetricAggregation,
    MetricReason,
    MetricStatus,
    MetricUnit,
    MetricValue,
    ProcessMemoryReading,
    STABLE_PHASE_IDS,
)


class Clock:
    def __init__(self, *values: int) -> None:
        self._values = iter(values)

    def __call__(self) -> int:
        return next(self._values)


class ConstantClock:
    def __init__(self, value: int = 1) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class MemoryProbe:
    def __init__(self, *readings: ProcessMemoryReading) -> None:
        self._readings = iter(readings)

    def read(self) -> ProcessMemoryReading:
        return next(self._readings)


def measured_bytes(value: int) -> MetricValue:
    return MetricValue.measured(value, MetricUnit.BYTES)


def test_disabled_session_does_not_call_clocks_or_validate_instrumentation() -> None:
    def fail() -> int:
        raise AssertionError("disabled instrumentation called a probe")

    session = MeasurementSession(
        wall_clock_ns=fail,
        process_cpu_clock_ns=fail,
        thread_cpu_clock_ns=fail,
    )
    with session.scope("an invalid phase/path", consumer="absolute/path") as scope:
        scope.add_units(-1)
        session.filesystem.content_read("absolute/path", bytes_read=-1)
    assert session.report().to_dict()["samples"] == []
    assert session.report().filesystem.consumers == ()
    assert session.report().sampling.status is MetricStatus.UNAVAILABLE


def test_disabled_filesystem_collection_is_not_reported_as_observed_zero() -> None:
    session = MeasurementSession(
        MeasurementConfig(enabled=True, capture_filesystem=False)
    )
    with session.scope(MeasurementPhase.WORKSPACE_DISCOVERY):
        pass

    filesystem = session.report().to_dict()["filesystem"]
    assert filesystem["coverage"] == {
        "status": "unavailable",
        "reason": "collection-disabled",
    }
    assert all(value == 0 for value in filesystem["totals"].values())


def test_phase_registry_contains_the_required_stable_phases() -> None:
    assert STABLE_PHASE_IDS == tuple(item.value for item in MeasurementPhase)
    assert set(STABLE_PHASE_IDS) == {
        "workspace.discovery",
        "project.ownership",
        "project.analysis",
        "repository.inventory",
        "filesystem.traversal",
        "path.normalization",
        "build.parsing",
        "language.java.parsing",
        "language.kotlin.parsing",
        "language.python.parsing",
        "symbol.extraction",
        "dependency.intelligence",
        "knowledge_graph.build",
        "architecture.analysis",
        "reachability.analysis",
        "risk.analysis",
        "repository.summary",
        "repository.report",
        "explain.projection",
        "semantic_snapshot.build",
        "serialization",
        "persistence",
        "recovery",
        "publication",
    }


def test_scope_records_cpu_work_and_explicit_unavailable_metrics() -> None:
    session = MeasurementSession(
        MeasurementConfig(enabled=True),
        wall_clock_ns=Clock(100, 300),
        process_cpu_clock_ns=Clock(10, 110),
        thread_cpu_clock_ns=Clock(20, 70),
        thread_identifier=lambda: 7,
    )
    with session.scope(MeasurementPhase.JAVA_PARSING, consumer="java-parser") as scope:
        scope.add_units(3)
        scope.add_bytes(250)
        scope.add_objects_produced(4)
        scope.set_objects_retained(2)

    sample = session.report().samples[0]
    assert sample.phase_id == "language.java.parsing"
    assert sample.scope_path == ("language.java.parsing",)
    assert sample.thread_id == 7
    assert sample.metric("wall_time_ns").value == 200
    assert sample.metric("process_cpu_time_ns").value == 100
    assert sample.metric("thread_cpu_time_ns").value == 50
    assert sample.metric("process_utilization_percent").value == 50.0
    assert sample.metric("units_processed").value == 3
    assert sample.metric("bytes_processed").value == 250
    assert sample.metric("objects_produced").value == 4
    assert sample.metric("objects_retained").value == 2
    assert sample.metric("rss_bytes").to_dict() == {
        "status": "unavailable",
        "unit": "bytes",
        "reason": "collection-disabled",
    }
    assert sample.metric("queue_wait_ns").status is MetricStatus.UNSUPPORTED


def test_hierarchical_scope_paths_are_context_local() -> None:
    clock = ConstantClock()
    session = MeasurementSession(
        MeasurementConfig(enabled=True),
        wall_clock_ns=clock,
        process_cpu_clock_ns=clock,
        thread_cpu_clock_ns=clock,
        thread_identifier=lambda: 1,
    )
    with session.scope(MeasurementPhase.WORKSPACE_DISCOVERY):
        with session.scope(MeasurementPhase.FILESYSTEM_TRAVERSAL):
            pass
    assert [item.scope_path for item in session.report().samples] == [
        ("workspace.discovery",),
        ("workspace.discovery", "filesystem.traversal"),
    ]


def test_failed_scope_is_measured_without_swallowing_the_exception() -> None:
    clock = ConstantClock()
    session = MeasurementSession(
        MeasurementConfig(enabled=True),
        wall_clock_ns=clock,
        process_cpu_clock_ns=clock,
        thread_cpu_clock_ns=clock,
    )
    with pytest.raises(RuntimeError, match="application failure"):
        with session.scope(MeasurementPhase.BUILD_PARSING):
            raise RuntimeError("application failure")
    assert session.report().samples[0].succeeded is False


def test_missing_thread_clock_is_reported_as_unsupported() -> None:
    session = MeasurementSession(
        MeasurementConfig(enabled=True),
        wall_clock_ns=Clock(1, 2),
        process_cpu_clock_ns=Clock(1, 2),
        thread_cpu_clock_ns=None,
    )
    with session.scope(MeasurementPhase.SERIALIZATION):
        pass
    metric = session.report().samples[0].metric("thread_cpu_time_ns")
    assert metric.status is MetricStatus.UNSUPPORTED
    assert metric.reason is MetricReason.RUNTIME_UNSUPPORTED


def test_utilization_preserves_disabled_cpu_reason_even_with_zero_wall() -> None:
    session = MeasurementSession(
        MeasurementConfig(enabled=True, capture_process_cpu=False),
        wall_clock_ns=ConstantClock(),
        thread_cpu_clock_ns=ConstantClock(),
    )
    with session.scope(MeasurementPhase.SERIALIZATION):
        pass
    utilization = session.report().samples[0].metric(
        "process_utilization_percent"
    )
    assert utilization.status is MetricStatus.UNAVAILABLE
    assert utilization.reason is MetricReason.COLLECTION_DISABLED


def test_memory_probe_records_facts_deltas_and_unsupported_commit() -> None:
    unsupported = MetricValue.unsupported(
        MetricUnit.BYTES,
        MetricReason.PLATFORM_UNSUPPORTED,
    )
    probe = MemoryProbe(
        ProcessMemoryReading(measured_bytes(100), measured_bytes(90), unsupported),
        ProcessMemoryReading(measured_bytes(140), measured_bytes(120), unsupported),
    )
    session = MeasurementSession(
        MeasurementConfig(enabled=True, capture_process_memory=True),
        wall_clock_ns=Clock(1, 2),
        process_cpu_clock_ns=Clock(1, 2),
        thread_cpu_clock_ns=Clock(1, 2),
        memory_probe=probe,
    )
    with session.scope(MeasurementPhase.REPOSITORY_INVENTORY):
        pass
    sample = session.report().samples[0]
    assert sample.metric("rss_bytes").value == 140
    assert sample.metric("rss_delta_bytes").value == 40
    assert sample.metric("working_set_delta_bytes").value == 30
    assert sample.metric("commit_bytes").status is MetricStatus.UNSUPPORTED
    assert sample.metric("commit_delta_bytes").status is MetricStatus.UNSUPPORTED


def test_invalid_absolute_memory_probe_is_reported_unavailable() -> None:
    invalid = ProcessMemoryReading(
        MetricValue.measured(1, MetricUnit.COUNT),
        MetricValue.measured(2, MetricUnit.PERCENT),
        MetricValue.measured(-3, MetricUnit.BYTES),
    )
    session = MeasurementSession(
        MeasurementConfig(enabled=True, capture_process_memory=True),
        wall_clock_ns=Clock(1, 2),
        process_cpu_clock_ns=Clock(1, 2),
        thread_cpu_clock_ns=Clock(1, 2),
        memory_probe=MemoryProbe(invalid, invalid),
    )
    with session.scope(MeasurementPhase.REPOSITORY_INVENTORY):
        pass

    sample = session.report().samples[0]
    for name in ("rss_bytes", "working_set_bytes", "commit_bytes"):
        assert sample.metric(name).status is MetricStatus.UNAVAILABLE
        assert sample.metric(name).reason is MetricReason.PROVIDER_UNAVAILABLE


@pytest.mark.parametrize("invalid", [True, -1, 1.5])
def test_invalid_clock_values_are_not_coerced_to_measured_zero(
    invalid: object,
) -> None:
    session = MeasurementSession(
        MeasurementConfig(enabled=True),
        wall_clock_ns=lambda: invalid,  # type: ignore[arg-type,return-value]
        process_cpu_clock_ns=ConstantClock(),
        thread_cpu_clock_ns=ConstantClock(),
    )
    with session.scope(MeasurementPhase.SNAPSHOT):
        pass
    wall = session.report().samples[0].metric("wall_time_ns")
    assert wall.status is MetricStatus.UNAVAILABLE
    assert wall.reason is MetricReason.PROVIDER_UNAVAILABLE


def test_non_monotonic_clock_is_not_clamped_to_measured_zero() -> None:
    session = MeasurementSession(
        MeasurementConfig(enabled=True),
        wall_clock_ns=Clock(2, 1),
        process_cpu_clock_ns=ConstantClock(),
        thread_cpu_clock_ns=ConstantClock(),
    )
    with session.scope(MeasurementPhase.SNAPSHOT):
        pass
    wall = session.report().samples[0].metric("wall_time_ns")
    assert wall.status is MetricStatus.UNAVAILABLE
    assert wall.reason is MetricReason.PROVIDER_UNAVAILABLE


def test_python_memory_is_unavailable_when_tracemalloc_is_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("moughorai.measurement.session.tracemalloc.is_tracing", lambda: False)
    clock = ConstantClock()
    session = MeasurementSession(
        MeasurementConfig(enabled=True, capture_python_memory=True),
        wall_clock_ns=clock,
        process_cpu_clock_ns=clock,
        thread_cpu_clock_ns=clock,
    )
    with session.scope(MeasurementPhase.SNAPSHOT):
        pass
    metric = session.report().samples[0].metric("python_allocated_bytes")
    assert metric.status is MetricStatus.UNAVAILABLE
    assert metric.reason is MetricReason.TRACEMALLOC_INACTIVE


def test_python_memory_uses_tracemalloc_without_starting_or_resetting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readings = iter(((100, 180), (130, 220)))
    monkeypatch.setattr("moughorai.measurement.session.tracemalloc.is_tracing", lambda: True)
    monkeypatch.setattr(
        "moughorai.measurement.session.tracemalloc.get_traced_memory",
        lambda: next(readings),
    )
    clock = ConstantClock()
    session = MeasurementSession(
        MeasurementConfig(enabled=True, capture_python_memory=True),
        wall_clock_ns=clock,
        process_cpu_clock_ns=clock,
        thread_cpu_clock_ns=clock,
    )
    with session.scope(MeasurementPhase.KNOWLEDGE_GRAPH):
        pass
    sample = session.report().samples[0]
    assert sample.metric("python_allocated_bytes").value == 130
    assert sample.metric("python_allocated_delta_bytes").value == 30
    assert sample.metric("python_peak_allocated_bytes").value == 220


def test_worker_metrics_are_only_facts_when_the_worker_reports_them() -> None:
    clock = Clock(10, 30)
    session = MeasurementSession(
        MeasurementConfig(enabled=True, worker_metrics_supported=True),
        wall_clock_ns=clock,
        process_cpu_clock_ns=ConstantClock(),
        thread_cpu_clock_ns=ConstantClock(),
    )
    with session.scope(
        MeasurementPhase.JAVA_PARSING,
        worker_id="worker-2",
        worker_metrics=True,
    ) as scope:
        scope.set_queue_wait_ns(7)
        scope.set_idle_time_ns(2)
        scope.set_queue_depth(4)
    sample = session.report().samples[0]
    assert sample.worker_id == "worker-2"
    assert sample.metric("service_time_ns").value == 20
    assert sample.metric("queue_wait_ns").value == 7
    assert sample.metric("idle_time_ns").value == 2
    assert sample.metric("queue_depth").value == 4


def test_worker_capability_is_scope_local() -> None:
    session = MeasurementSession(
        MeasurementConfig(enabled=True, worker_metrics_supported=True),
        wall_clock_ns=Clock(10, 30),
        process_cpu_clock_ns=ConstantClock(),
        thread_cpu_clock_ns=ConstantClock(),
    )
    with session.scope(MeasurementPhase.REPOSITORY_SUMMARY):
        pass
    sample = session.report().samples[0]
    assert sample.metric("service_time_ns").status is MetricStatus.UNSUPPORTED
    assert sample.metric("queue_wait_ns").status is MetricStatus.UNSUPPORTED


def test_nested_worker_scopes_inherit_identity_and_reject_process_cpu_attribution() -> None:
    clock = ConstantClock()
    session = MeasurementSession(
        MeasurementConfig(enabled=True, worker_metrics_supported=True),
        wall_clock_ns=clock,
        process_cpu_clock_ns=clock,
        thread_cpu_clock_ns=clock,
    )
    with session.scope(
        MeasurementPhase.PROJECT_ANALYSIS,
        worker_id="worker-3",
        worker_metrics=True,
    ):
        with session.scope(MeasurementPhase.JAVA_PARSING):
            pass

    nested = next(
        item
        for item in session.report().samples
        if item.phase_id == MeasurementPhase.JAVA_PARSING.value
    )
    assert nested.worker_id == "worker-3"
    assert nested.metric("process_cpu_time_ns").status is MetricStatus.UNAVAILABLE
    assert (
        nested.metric("process_cpu_time_ns").reason
        is MetricReason.CONCURRENT_ATTRIBUTION
    )
    assert nested.metric("thread_cpu_time_ns").status is MetricStatus.MEASURED
    assert nested.metric("queue_wait_ns").status is MetricStatus.UNSUPPORTED


def test_filesystem_ledger_is_run_local_aggregated_and_source_free() -> None:
    ledger = FilesystemLedger(enabled=True)
    ledger.directory_enumerated("workspace-discovery", count=2)
    ledger.metadata_looked_up("workspace-discovery", count=3)
    ledger.path_normalized("workspace-discovery")
    ledger.content_read("java-parser", bytes_read=512, count=2)
    ledger.content_hashed("java-parser")
    ledger.descriptor_parsed("workspace-discovery")
    ledger.language_parsed("java-parser", count=2)
    snapshot = ledger.snapshot()

    assert [item.consumer for item in snapshot.consumers] == [
        "java-parser",
        "workspace-discovery",
    ]
    assert snapshot.totals == {
        "directory_enumerations": 2,
        "metadata_lookups": 3,
        "path_normalizations": 1,
        "content_reads": 2,
        "bytes_read": 512,
        "content_read_bytes_unavailable": 0,
        "consumer_unique_content_resources": 0,
        "consumer_repeated_content_reads": 0,
        "hashes": 1,
        "descriptor_parses": 1,
        "language_parses": 2,
        "measurement_metadata_lookups": 0,
    }
    encoded = json.dumps(snapshot.to_dict()).lower()
    assert "c:\\" not in encoded
    assert "/home/" not in encoded
    assert ledger.clear() == 12
    assert ledger.snapshot().consumers == ()


def test_filesystem_bytes_are_valid_only_for_content_reads() -> None:
    ledger = FilesystemLedger(enabled=True)
    with pytest.raises(ValueError, match="only for content reads"):
        ledger.record(
            FilesystemOperation.HASH,
            consumer="hasher",
            bytes_read=2,
        )
    with pytest.raises(ValueError, match="at least one content read"):
        ledger.content_read("reader", bytes_read=1, count=0)


def test_filesystem_snapshot_rejects_impossible_repeat_evidence() -> None:
    left = FilesystemConsumerMetrics(
        "left",
        content_reads=1,
        consumer_unique_content_resources=1,
    )
    right = FilesystemConsumerMetrics(
        "right",
        content_reads=1,
        consumer_unique_content_resources=1,
    )
    with pytest.raises(ValueError, match="overlap exceeds"):
        FilesystemLedgerSnapshot(
            consumers=(left, right),
            observed_unique_content_resources=1,
            observed_content_reads=2,
            overlaps=(FilesystemConsumerOverlap(("left", "right"), 2),),
            coverage_status="partial",
            coverage_reason="explicit-instrumentation-boundaries",
        )


def test_file_content_read_counts_physical_bytes_without_retaining_the_path(
    tmp_path,
) -> None:
    target = tmp_path / "source.txt"
    target.write_bytes(b"\xef\xbb\xbfline\r\n")
    ledger = FilesystemLedger(enabled=True)

    ledger.file_content_read("reader", target)

    snapshot = ledger.snapshot()
    assert snapshot.totals["bytes_read"] == 9
    assert snapshot.totals["metadata_lookups"] == 0
    assert snapshot.totals["measurement_metadata_lookups"] == 1
    assert snapshot.totals["content_read_bytes_unavailable"] == 0
    assert str(target) not in json.dumps(snapshot.to_dict())


def test_file_content_ledger_reports_source_free_repeat_and_overlap_counts(
    tmp_path,
) -> None:
    target = tmp_path / "source.txt"
    target.write_text("value", encoding="utf-8")
    ledger = FilesystemLedger(enabled=True)

    ledger.file_content_read("parser", target)
    ledger.file_content_read("parser", target)
    ledger.file_content_read("summary", target)

    payload = ledger.snapshot().to_dict()
    assert payload["content_resources"] == {
        "observed_reads": 3,
        "observed_repeated_reads": 2,
        "observed_unique": 1,
        "consumer_overlaps": [
            {
                "consumers": ["parser", "summary"],
                "observed_resources": 1,
            }
        ],
        "resource_limit_reached": False,
        "resource_tracking_limit": 100_000,
        "tracking_reason": None,
        "tracking_status": "measured",
        "untracked_reads": 0,
    }
    consumers = {item["consumer"]: item for item in payload["consumers"]}
    assert consumers["parser"]["consumer_unique_content_resources"] == 1
    assert consumers["parser"]["consumer_repeated_content_reads"] == 1
    assert consumers["summary"]["consumer_unique_content_resources"] == 1
    assert str(target) not in json.dumps(payload)


def test_identity_free_content_reads_are_reported_as_untracked() -> None:
    ledger = FilesystemLedger(enabled=True)
    ledger.content_read("reader", bytes_read=None, count=2)

    resources = ledger.snapshot().to_dict()["content_resources"]
    assert resources == {
        "observed_reads": 0,
        "observed_repeated_reads": 0,
        "observed_unique": 0,
        "consumer_overlaps": [],
        "resource_limit_reached": False,
        "resource_tracking_limit": 100_000,
        "tracking_reason": "identity-unavailable",
        "tracking_status": "partial",
        "untracked_reads": 2,
    }


def test_resource_tracking_is_bounded_and_reports_saturation(tmp_path) -> None:
    ledger = FilesystemLedger(enabled=True, resource_limit=1)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    ledger.file_content_read_unknown_size("reader", first)
    ledger.file_content_read_unknown_size("reader", second)

    resources = ledger.snapshot().to_dict()["content_resources"]
    assert resources["resource_tracking_limit"] == 1
    assert resources["resource_limit_reached"] is True
    assert resources["tracking_status"] == "partial"
    assert resources["tracking_reason"] == "resource-limit-reached"
    assert resources["observed_unique"] == 1
    assert resources["untracked_reads"] == 1


@pytest.mark.parametrize("limit", [0, -1, True])
def test_filesystem_resource_limit_must_be_positive(limit: object) -> None:
    with pytest.raises(ValueError, match="filesystem_resource_limit"):
        MeasurementConfig(filesystem_resource_limit=limit)  # type: ignore[arg-type]


def test_report_is_deterministic_source_free_and_exactly_round_trips() -> None:
    clock = ConstantClock()
    session = MeasurementSession(
        MeasurementConfig(enabled=True),
        wall_clock_ns=clock,
        process_cpu_clock_ns=clock,
        thread_cpu_clock_ns=clock,
        thread_identifier=lambda: 3,
    )
    with session.scope(MeasurementPhase.RISK, consumer="risk-analysis"):
        pass
    with session.scope(MeasurementPhase.ARCHITECTURE, consumer="architecture-analysis"):
        pass
    session.filesystem.metadata_looked_up("repository-inventory")
    report = session.report()
    payload = report.to_dict()
    encoded = report.to_json()

    assert encoded == report.to_json()
    assert MeasurementReport(
        samples=tuple(reversed(report.samples)),
        filesystem=report.filesystem,
        sampling=report.sampling,
    ).to_json() == encoded
    assert MeasurementReport.from_dict(payload).to_dict() == payload
    assert "C:\\" not in encoded
    assert "/home/" not in encoded
    assert "source" not in payload["samples"][0]
    assert [item["phase_id"] for item in payload["aggregates"]] == [
        "architecture.analysis",
        "risk.analysis",
    ]
    summary = report.to_text()
    assert "architecture.analysis: samples=1, succeeded=1, failed=0" in summary
    assert "unsupported=1" in summary
    assert "metadata_lookups: 1" in summary


@pytest.mark.parametrize("schema", [True, 1.0, "1"])
def test_report_schema_requires_an_exact_integer(schema: object) -> None:
    payload = MeasurementSession(MeasurementConfig(enabled=True)).report().to_dict()
    payload["schema_version"] = schema
    with pytest.raises(ValueError, match="schema"):
        MeasurementReport.from_dict(payload)


@pytest.mark.parametrize("schema", [True, 1.0, "1"])
def test_report_constructor_requires_an_exact_integer(schema: object) -> None:
    with pytest.raises(ValueError, match="schema"):
        MeasurementReport((), schema_version=schema)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["secret", None, True])
def test_measured_metric_requires_a_real_number(value: object) -> None:
    with pytest.raises(ValueError, match="numeric"):
        MetricValue(MetricStatus.MEASURED, MetricUnit.COUNT, value=value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (MetricStatus.UNSUPPORTED, MetricReason.COLLECTION_DISABLED),
        (MetricStatus.UNAVAILABLE, MetricReason.PLATFORM_UNSUPPORTED),
    ],
)
def test_metric_absence_status_and_reason_cannot_contradict(
    status: MetricStatus,
    reason: MetricReason,
) -> None:
    with pytest.raises(ValueError):
        MetricValue(status, MetricUnit.COUNT, reason=reason)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("thread_id", True),
        ("succeeded", 1),
    ],
)
def test_report_loader_rejects_schema_ambiguous_sample_types(
    field: str,
    value: object,
) -> None:
    session = MeasurementSession(MeasurementConfig(enabled=True))
    with session.scope(MeasurementPhase.PUBLICATION):
        pass
    payload = session.report().to_dict()
    payload["samples"][0][field] = value
    with pytest.raises(ValueError):
        MeasurementReport.from_dict(payload)


def test_report_loader_rejects_boolean_filesystem_counters() -> None:
    ledger = FilesystemLedger(enabled=True)
    ledger.content_read("reader", bytes_read=1)
    report = MeasurementReport((), ledger.snapshot())
    payload = report.to_dict()
    payload["filesystem"]["consumers"][0]["bytes_read"] = True
    payload["filesystem"]["totals"]["bytes_read"] = True
    with pytest.raises(ValueError):
        MeasurementReport.from_dict(payload)


def test_normative_schema_closes_source_free_filesystem_objects() -> None:
    schema = json.loads(
        (
            Path(__file__).parents[1]
            / "docs"
            / "schemas"
            / "atlas-performance-measurement-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    definitions = schema["$defs"]
    assert definitions["filesystemCounters"]["additionalProperties"] is False
    assert definitions["filesystemConsumer"]["additionalProperties"] is False
    assert definitions["filesystem"]["additionalProperties"] is False


def test_emitted_report_validates_against_normative_json_schema() -> None:
    schema = json.loads(
        (
            Path(__file__).parents[1]
            / "docs"
            / "schemas"
            / "atlas-performance-measurement-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    session = MeasurementSession(MeasurementConfig(enabled=True))
    with session.scope(MeasurementPhase.PUBLICATION) as scope:
        scope.add_units(1)
    Draft202012Validator(schema).validate(session.report().to_dict())


@pytest.mark.parametrize(
    "field",
    ["phase_ids", "phase_status", "sampling", "aggregates", "filesystem"],
)
def test_report_loader_rejects_noncanonical_derived_fields(field: str) -> None:
    session = MeasurementSession(MeasurementConfig(enabled=True))
    with session.scope(MeasurementPhase.PUBLICATION):
        pass
    payload = session.report().to_dict()
    if isinstance(payload[field], list):
        payload[field] = []
    else:
        payload[field] = {"consumers": [], "totals": {}}
    with pytest.raises(ValueError, match=field):
        MeasurementReport.from_dict(payload)


def test_aggregation_preserves_unavailable_and_unsupported_counts() -> None:
    clock = ConstantClock()
    session = MeasurementSession(
        MeasurementConfig(enabled=True),
        wall_clock_ns=clock,
        process_cpu_clock_ns=clock,
        thread_cpu_clock_ns=None,
    )
    for _ in range(2):
        with session.scope(MeasurementPhase.PUBLICATION):
            pass
    aggregate = session.report().aggregates[0]
    metrics = {item.name: item for item in aggregate.metrics}
    assert aggregate.sample_count == 2
    assert metrics["thread_cpu_time_ns"].unsupported_count == 2
    assert metrics["rss_bytes"].unavailable_count == 2
    assert metrics["wall_time_ns"].measured_count == 2
    assert metrics["wall_time_ns"].aggregation is MetricAggregation.SAMPLE_SUM
    assert metrics["rss_bytes"].aggregation is MetricAggregation.DISTRIBUTION
    assert metrics["rss_bytes"].total is None


def test_samples_and_metric_values_are_immutable() -> None:
    value = MetricValue.measured(1, MetricUnit.COUNT)
    with pytest.raises(FrozenInstanceError):
        value.value = 2  # type: ignore[misc]
    clock = ConstantClock()
    session = MeasurementSession(
        MeasurementConfig(enabled=True),
        wall_clock_ns=clock,
        process_cpu_clock_ns=clock,
        thread_cpu_clock_ns=clock,
    )
    with session.scope(MeasurementPhase.PERSISTENCE):
        pass
    sample = session.report().samples[0]
    with pytest.raises(FrozenInstanceError):
        sample.phase_id = "recovery"  # type: ignore[misc]


def test_deterministic_sampling_requires_a_non_retained_key() -> None:
    clock = ConstantClock()
    session = MeasurementSession(
        MeasurementConfig(enabled=True, sample_every=2),
        wall_clock_ns=clock,
        process_cpu_clock_ns=clock,
        thread_cpu_clock_ns=clock,
    )
    with pytest.raises(ValueError, match="sample_key is required"):
        with session.scope(MeasurementPhase.REACHABILITY):
            pass

    decisions = []
    for key in ("project-a", "project-b", "project-c", "project-d"):
        before = len(session.report().samples)
        with session.scope(MeasurementPhase.REACHABILITY, sample_key=key):
            pass
        decisions.append(len(session.report().samples) > before)
    second = MeasurementSession(
        MeasurementConfig(enabled=True, sample_every=2),
        wall_clock_ns=clock,
        process_cpu_clock_ns=clock,
        thread_cpu_clock_ns=clock,
    )
    repeated = []
    for key in ("project-a", "project-b", "project-c", "project-d"):
        before = len(second.report().samples)
        with second.scope(MeasurementPhase.REACHABILITY, sample_key=key):
            pass
        repeated.append(len(second.report().samples) > before)
    assert decisions == repeated
    sampling = session.report().sampling
    assert sampling.status is MetricStatus.MEASURED
    assert sampling.sample_every == 2
    assert sampling.eligible_scopes == 4
    assert sampling.sampled_scopes == sum(decisions)


def test_sampling_selection_does_not_depend_on_worker_assignment() -> None:
    def selected(worker_id: str) -> bool:
        session = MeasurementSession(
            MeasurementConfig(enabled=True, sample_every=2),
            wall_clock_ns=ConstantClock(),
            process_cpu_clock_ns=ConstantClock(),
            thread_cpu_clock_ns=ConstantClock(),
        )
        with session.scope(
            MeasurementPhase.PROJECT_ANALYSIS,
            worker_id=worker_id,
            sample_key="same-project",
        ):
            pass
        return bool(session.report().samples)

    assert selected("worker-1") == selected("worker-99")


def test_sampled_out_phase_is_distinct_from_never_recorded() -> None:
    report = None
    for key in ("a", "b", "c", "d", "e", "f"):
        session = MeasurementSession(
            MeasurementConfig(enabled=True, sample_every=2)
        )
        with session.scope(MeasurementPhase.RISK, sample_key=key):
            pass
        candidate = session.report()
        if not candidate.samples:
            report = candidate
            break
    assert report is not None
    statuses = {item["phase_id"]: item for item in report.phase_statuses}
    assert statuses[MeasurementPhase.RISK.value]["reason"] == "sampled-out"
    assert statuses[MeasurementPhase.ARCHITECTURE.value]["reason"] == "not-recorded"


def test_sampling_invariants_reject_contradictory_public_models() -> None:
    with pytest.raises(ValueError, match="unavailable sampling"):
        MeasurementSampling(
            MetricStatus.UNAVAILABLE,
            2,
            1,
            0,
        )
    with pytest.raises(ValueError, match="sample_every"):
        MeasurementSampling(
            MetricStatus.MEASURED,
            1,
            1,
            0,
        )

    session = MeasurementSession(MeasurementConfig(enabled=True))
    with session.scope(MeasurementPhase.RISK):
        pass
    with pytest.raises(ValueError, match="sampling"):
        MeasurementReport(session.report().samples)


def test_parallel_collection_keeps_independent_scope_stacks() -> None:
    session = MeasurementSession(MeasurementConfig(enabled=True))

    def collect() -> None:
        for _ in range(10):
            with session.scope(MeasurementPhase.JAVA_PARSING):
                pass

    threads = [Thread(target=collect) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    report = session.report()
    assert len(report.samples) == 40
    assert {item.scope_path for item in report.samples} == {
        ("language.java.parsing",),
    }


def test_default_memory_probe_always_reports_explicit_states() -> None:
    reading = CurrentProcessMemoryProbe().read()
    for value in (
        reading.rss_bytes,
        reading.working_set_bytes,
        reading.commit_bytes,
    ):
        assert value.status in {
            MetricStatus.MEASURED,
            MetricStatus.UNAVAILABLE,
            MetricStatus.UNSUPPORTED,
        }
