from __future__ import annotations

import json
from dataclasses import replace

import pytest

from moughorai.plugin_sdk import (
    ExtensionPoint,
    PluginExtension,
    PluginHealthError,
    PluginHealthPolicy,
    PluginHealthStatus,
    PluginHealthSupervisor,
    PluginManifest,
    PluginRegistry,
    PluginRuntime,
)


class ProbeExtension:
    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [True])
        self.calls = 0

    def health_check(self):
        value = self.outcomes.pop(0) if self.outcomes else True
        if isinstance(value, Exception):
            raise value
        return value

    def execute(self, value=1):
        self.calls += 1
        if value == "fail":
            raise RuntimeError("execution failed")
        return value * 2


class ContextProbe:
    def health_check(self, context):
        return context.require("healthy"), "from context"


def build_supervisor(instance, *, policy=None, name="main"):
    manifest = PluginManifest(
        "demo", "1.0.0", "^1.0.0", "Demo",
        (PluginExtension(name, ExtensionPoint.ANALYZER, "tests.test_pr61_plugin_health:ProbeExtension"),),
    )
    registry = PluginRegistry()
    registry.register(manifest)
    runtime = PluginRuntime(registry)
    runtime._loaded["demo"] = (
        replace(runtime.load("demo")[0], instance=instance),
    )
    return PluginHealthSupervisor(runtime, policy=policy)


def test_policy_defaults():
    assert PluginHealthPolicy() == PluginHealthPolicy(3, 2, True)


@pytest.mark.parametrize("field,value", [("failure_threshold", 0), ("recovery_threshold", 0)])
def test_policy_rejects_invalid_thresholds(field, value):
    with pytest.raises(ValueError):
        PluginHealthPolicy(**{field: value})


def test_loaded_extension_starts_unknown():
    supervisor = build_supervisor(ProbeExtension())
    assert supervisor.record("demo", "main").status is PluginHealthStatus.UNKNOWN


def test_successful_probe_marks_healthy():
    supervisor = build_supervisor(ProbeExtension([True]))
    assert supervisor.probe("demo", "main").status is PluginHealthStatus.HEALTHY


def test_false_probe_marks_degraded_before_threshold():
    supervisor = build_supervisor(ProbeExtension([False]))
    assert supervisor.probe("demo", "main").status is PluginHealthStatus.DEGRADED


def test_failures_cross_unhealthy_threshold():
    supervisor = build_supervisor(ProbeExtension([False, False]), policy=PluginHealthPolicy(2, 2))
    supervisor.probe("demo", "main")
    record = supervisor.probe("demo", "main")
    assert record.status is PluginHealthStatus.UNHEALTHY
    assert record.total_failures == 2


def test_exception_probe_is_failure():
    supervisor = build_supervisor(ProbeExtension([RuntimeError("boom")]))
    record = supervisor.probe("demo", "main")
    assert record.last_message == "boom"


@pytest.mark.parametrize(
    "outcome,expected_message",
    [((True, "ok"), "ok"), ({"healthy": True, "message": "map"}, "map"), (None, "")],
)
def test_supported_probe_shapes(outcome, expected_message):
    supervisor = build_supervisor(ProbeExtension([outcome]))
    assert supervisor.probe("demo", "main").last_message == expected_message


def test_invalid_probe_shape_is_failure():
    supervisor = build_supervisor(ProbeExtension(["bad"]))
    assert "health check must return" in supervisor.probe("demo", "main").last_message


def test_recovery_requires_configured_successes():
    supervisor = build_supervisor(
        ProbeExtension([False, False, True, True]), policy=PluginHealthPolicy(2, 2)
    )
    supervisor.probe("demo", "main")
    supervisor.probe("demo", "main")
    assert supervisor.probe("demo", "main").status is PluginHealthStatus.DEGRADED
    assert supervisor.probe("demo", "main").status is PluginHealthStatus.HEALTHY


def test_success_resets_failure_streak():
    supervisor = build_supervisor(ProbeExtension([False, True]))
    supervisor.probe("demo", "main")
    record = supervisor.probe("demo", "main")
    assert record.consecutive_failures == 0


def test_failure_resets_success_streak():
    supervisor = build_supervisor(ProbeExtension([True, False]))
    supervisor.probe("demo", "main")
    record = supervisor.probe("demo", "main")
    assert record.consecutive_successes == 0


def test_total_probe_count_includes_invocations():
    supervisor = build_supervisor(ProbeExtension())
    supervisor.invoke("demo", "main", "execute", 2)
    assert supervisor.record("demo", "main").total_probes == 1


def test_guarded_invoke_returns_result():
    supervisor = build_supervisor(ProbeExtension())
    assert supervisor.invoke("demo", "main", "execute", 4) == 8


def test_failed_invoke_updates_health_and_reraises():
    supervisor = build_supervisor(ProbeExtension())
    with pytest.raises(RuntimeError, match="execution failed"):
        supervisor.invoke("demo", "main", "execute", "fail")
    assert supervisor.record("demo", "main").status is PluginHealthStatus.DEGRADED


def test_unhealthy_extension_is_blocked():
    supervisor = build_supervisor(ProbeExtension([False]), policy=PluginHealthPolicy(1, 1))
    supervisor.probe("demo", "main")
    with pytest.raises(PluginHealthError, match="unhealthy"):
        supervisor.invoke("demo", "main", "execute")


def test_unhealthy_extension_can_be_allowed():
    supervisor = build_supervisor(
        ProbeExtension([False]), policy=PluginHealthPolicy(1, 1, block_unhealthy=False)
    )
    supervisor.probe("demo", "main")
    assert supervisor.invoke("demo", "main", "execute", 3) == 6


def test_missing_method_is_reported():
    supervisor = build_supervisor(ProbeExtension())
    with pytest.raises(PluginHealthError, match="method is unavailable"):
        supervisor.invoke("demo", "main", "missing")


def test_manual_quarantine_blocks_probe_and_invoke():
    supervisor = build_supervisor(ProbeExtension())
    supervisor.quarantine("demo", "main", "operator decision")
    assert supervisor.probe("demo", "main").status is PluginHealthStatus.QUARANTINED
    with pytest.raises(PluginHealthError, match="quarantined"):
        supervisor.invoke("demo", "main", "execute")


def test_quarantine_requires_reason():
    supervisor = build_supervisor(ProbeExtension())
    with pytest.raises(ValueError):
        supervisor.quarantine("demo", "main", " ")


def test_release_resets_quarantine_state():
    supervisor = build_supervisor(ProbeExtension())
    supervisor.quarantine("demo", "main", "reason")
    record = supervisor.release("demo", "main")
    assert record.status is PluginHealthStatus.UNKNOWN
    assert record.quarantined_reason == ""


def test_events_have_stable_sequence():
    supervisor = build_supervisor(ProbeExtension([True, False]))
    supervisor.probe("demo", "main")
    supervisor.probe("demo", "main")
    assert [event.sequence for event in supervisor.events()] == [1, 2]


def test_event_tracks_status_transition():
    supervisor = build_supervisor(ProbeExtension([False]))
    supervisor.probe("demo", "main")
    event = supervisor.events()[0]
    assert event.previous_status is PluginHealthStatus.UNKNOWN
    assert event.status is PluginHealthStatus.DEGRADED


def test_snapshot_json_is_deterministic():
    supervisor = build_supervisor(ProbeExtension([True]))
    supervisor.probe("demo", "main")
    assert supervisor.snapshot().to_json() == supervisor.snapshot().to_json()
    assert json.loads(supervisor.snapshot().to_json())["schema_version"] == 1


def test_status_counts_include_all_states():
    supervisor = build_supervisor(ProbeExtension([True]))
    supervisor.probe("demo", "main")
    counts = supervisor.status_counts()
    assert counts["healthy"] == 1
    assert set(counts) == {status.value for status in PluginHealthStatus}


def test_status_counts_are_read_only():
    supervisor = build_supervisor(ProbeExtension())
    with pytest.raises(TypeError):
        supervisor.status_counts()["healthy"] = 1


def test_missing_extension_is_reported():
    supervisor = build_supervisor(ProbeExtension())
    with pytest.raises(PluginHealthError, match="not loaded"):
        supervisor.record("demo", "missing")


def test_probe_all_is_deterministic():
    supervisor = build_supervisor(ProbeExtension([True]))
    assert [(r.plugin_id, r.extension_name) for r in supervisor.probe_all()] == [("demo", "main")]


def test_context_probe_receives_runtime_context():
    manifest = PluginManifest(
        "demo", "1.0.0", "^1.0.0", "Demo",
        (PluginExtension("main", ExtensionPoint.ANALYZER, "tests.test_pr61_plugin_health:ContextProbe"),),
    )
    registry = PluginRegistry(); registry.register(manifest)
    runtime = PluginRuntime(registry, services={"healthy": True}); runtime.load_all()
    supervisor = PluginHealthSupervisor(runtime)
    assert supervisor.probe("demo", "main").last_message == "from context"


def test_extension_without_probe_is_healthy():
    supervisor = build_supervisor(object())
    assert supervisor.probe("demo", "main").status is PluginHealthStatus.HEALTHY


def test_unloaded_extensions_are_pruned():
    supervisor = build_supervisor(ProbeExtension())
    assert len(supervisor.records()) == 1
    supervisor.runtime._loaded.clear()
    assert supervisor.records() == ()


def test_event_source_identifies_operation():
    supervisor = build_supervisor(ProbeExtension())
    supervisor.invoke("demo", "main", "execute")
    supervisor.quarantine("demo", "main", "reason")
    supervisor.release("demo", "main")
    assert [event.source for event in supervisor.events()] == ["invoke", "quarantine", "release"]


def test_quarantine_preserves_metrics():
    supervisor = build_supervisor(ProbeExtension([False]))
    supervisor.probe("demo", "main")
    before = supervisor.record("demo", "main")
    after = supervisor.quarantine("demo", "main", "reason")
    assert after.total_probes == before.total_probes
    assert after.total_failures == before.total_failures


def test_record_key_property():
    supervisor = build_supervisor(ProbeExtension())
    assert supervisor.record("demo", "main").key == ("demo", "main")


def test_snapshot_records_are_sorted():
    supervisor = build_supervisor(ProbeExtension(), name="z")
    assert [record.extension_name for record in supervisor.snapshot().records] == ["z"]


def test_probe_false_default_message():
    supervisor = build_supervisor(ProbeExtension([False]))
    assert supervisor.probe("demo", "main").last_message == "health check returned false"


def test_successful_invoke_can_recover_degraded_extension():
    supervisor = build_supervisor(ProbeExtension([False]), policy=PluginHealthPolicy(3, 1))
    supervisor.probe("demo", "main")
    supervisor.invoke("demo", "main", "execute")
    assert supervisor.record("demo", "main").status is PluginHealthStatus.HEALTHY
