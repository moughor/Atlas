from __future__ import annotations

import json
from dataclasses import replace

import pytest

from moughorai.plugin_sdk import (
    ExtensionPoint, PluginExtension, PluginManifest, PluginRegistry, PluginRuntime,
    PluginUpgradeError, PluginUpgradeManager, PluginUpgradePolicy, UpgradeStatus,
)

EVENTS: list[str] = []
FAIL_NEW = False
FAIL_ROLLBACK = False


class Stateful:
    version = "base"
    def __init__(self): self.value = 0
    def start(self, context):
        EVENTS.append(f"start:{self.version}")
        if self.version == "new" and FAIL_NEW: raise RuntimeError("new failed")
        if self.version == "old" and FAIL_ROLLBACK: raise RuntimeError("rollback failed")
    def stop(self, context): EVENTS.append(f"stop:{self.version}")
    def begin_drain(self, context): EVENTS.append(f"drain:{self.version}")
    def export_state(self): return {"value": self.value}
    def import_state(self, state): self.value = state["value"]; EVENTS.append(f"restore:{self.version}")

class Old(Stateful): version = "old"
class New(Stateful): version = "new"
class BrokenRestore(Stateful):
    version = "new"
    import_state = None
class Stateless:
    def start(self, context): EVENTS.append("stateless:start")
    def stop(self, context): EVENTS.append("stateless:stop")
class Dependent:
    def start(self, context): EVENTS.append("dep:start")
    def stop(self, context): EVENTS.append("dep:stop")
    def begin_drain(self, context): EVENTS.append("dep:drain")


def manifest(version="1.0.0", factory=f"{__name__}:Old", *, plugin_id="base", requires=()):
    return PluginManifest(plugin_id, version, "^1.0.0", plugin_id, (
        PluginExtension("main", ExtensionPoint.ANALYZER, factory),
    ), requires=requires)


def setup_runtime(*, dependent=False, loaded=True):
    registry = PluginRegistry()
    registry.register(manifest())
    if dependent:
        registry.register(manifest("1.0.0", f"{__name__}:Dependent", plugin_id="dep", requires=("base",)))
    runtime = PluginRuntime(registry)
    if loaded: runtime.load_all()
    return registry, runtime


def test_successful_upgrade_restores_state():
    registry, runtime = setup_runtime()
    runtime.extensions()[0].instance.value = 42
    report = PluginUpgradeManager(runtime).upgrade(manifest("2.0.0", f"{__name__}:New"))
    assert report.status is UpgradeStatus.SUCCEEDED
    assert report.restored_state is True
    assert runtime.extensions()[0].instance.value == 42
    assert registry.get("base").version == "2.0.0"


def test_upgrade_unloaded_plugin_does_not_load_it():
    registry, runtime = setup_runtime(loaded=False)
    report = PluginUpgradeManager(runtime).upgrade(manifest("2.0.0", f"{__name__}:New"))
    assert report.status is UpgradeStatus.SUCCEEDED
    assert runtime.extensions() == ()
    assert registry.get("base").version == "2.0.0"


def test_equal_version_rejected():
    _, runtime = setup_runtime()
    with pytest.raises(PluginUpgradeError, match="already"):
        PluginUpgradeManager(runtime).upgrade(manifest())


def test_downgrade_rejected_by_default():
    registry, runtime = setup_runtime()
    registry.replace(manifest("2.0.0"))
    with pytest.raises(PluginUpgradeError, match="downgrade"):
        PluginUpgradeManager(runtime).upgrade(manifest("1.0.0"))


def test_downgrade_allowed():
    registry, runtime = setup_runtime(loaded=False)
    registry.replace(manifest("2.0.0"))
    report = PluginUpgradeManager(runtime, policy=PluginUpgradePolicy(allow_downgrade=True)).upgrade(manifest())
    assert report.status is UpgradeStatus.SUCCEEDED


def test_incompatible_api_rejected():
    _, runtime = setup_runtime()
    bad = replace(manifest("2.0.0"), api_version=">=9.0.0")
    with pytest.raises(Exception, match="requires API"):
        PluginUpgradeManager(runtime).upgrade(bad)


def test_dependents_are_restarted():
    _, runtime = setup_runtime(dependent=True)
    report = PluginUpgradeManager(runtime).upgrade(manifest("2.0.0", f"{__name__}:New"))
    assert report.restarted_plugins == ("dep",)
    assert [x.plugin_id for x in runtime.extensions()] == ["base", "dep"]
    assert "dep:drain" in EVENTS


def test_dependents_can_block_upgrade():
    _, runtime = setup_runtime(dependent=True)
    manager = PluginUpgradeManager(runtime, policy=PluginUpgradePolicy(restart_dependents=False))
    with pytest.raises(PluginUpgradeError, match="dependents"):
        manager.upgrade(manifest("2.0.0", f"{__name__}:New"))


def test_failed_new_version_rolls_back():
    global FAIL_NEW
    FAIL_NEW = True
    try:
        registry, runtime = setup_runtime()
        runtime.extensions()[0].instance.value = 7
        report = PluginUpgradeManager(runtime).upgrade(manifest("2.0.0", f"{__name__}:New"))
        assert report.status is UpgradeStatus.ROLLED_BACK
        assert registry.get("base").version == "1.0.0"
        assert runtime.extensions()[0].instance.value == 7
        assert "new failed" in report.error
    finally:
        FAIL_NEW = False


def test_rollback_failure_reported():
    global FAIL_NEW, FAIL_ROLLBACK
    FAIL_NEW = True
    try:
        _, runtime = setup_runtime()
        FAIL_ROLLBACK = True
        report = PluginUpgradeManager(runtime).upgrade(manifest("2.0.0", f"{__name__}:New"))
        assert report.status is UpgradeStatus.FAILED
        assert "rollback failed" in report.error
    finally:
        FAIL_NEW = FAIL_ROLLBACK = False


def test_required_restore_rejects_stateless_old_plugin():
    registry = PluginRegistry(); registry.register(manifest(factory=f"{__name__}:Stateless"))
    runtime = PluginRuntime(registry); runtime.load_all()
    report = PluginUpgradeManager(runtime, policy=PluginUpgradePolicy(require_state_restore=True)).upgrade(
        manifest("2.0.0", f"{__name__}:New")
    )
    assert report.status is UpgradeStatus.ROLLED_BACK
    assert "did not export" in report.error


def test_required_restore_rejects_missing_import_hook():
    _, runtime = setup_runtime()
    report = PluginUpgradeManager(runtime, policy=PluginUpgradePolicy(require_state_restore=True)).upgrade(
        manifest("2.0.0", f"{__name__}:BrokenRestore")
    )
    assert report.status is UpgradeStatus.ROLLED_BACK
    assert "cannot restore" in report.error


def test_report_json_is_deterministic():
    _, runtime = setup_runtime()
    report = PluginUpgradeManager(runtime).upgrade(manifest("2.0.0", f"{__name__}:New"))
    assert report.to_json() == report.to_json()
    payload = json.loads(report.to_json())
    assert payload["schema_version"] == 1
    assert payload["status"] == "succeeded"


def test_event_sequences_are_contiguous():
    _, runtime = setup_runtime(dependent=True)
    report = PluginUpgradeManager(runtime).upgrade(manifest("2.0.0", f"{__name__}:New"))
    assert [event.sequence for event in report.events] == list(range(1, len(report.events) + 1))


def test_registry_replace_returns_old_manifest():
    registry = PluginRegistry(); old = manifest(); registry.register(old)
    new = manifest("2.0.0")
    assert registry.replace(new) is old
    assert registry.get("base") is new


@pytest.mark.parametrize("version", ["1.0.1", "1.1.0", "2.0.0", "10.0.0"])
def test_upgrade_versions(version):
    _, runtime = setup_runtime(loaded=False)
    assert PluginUpgradeManager(runtime).upgrade(manifest(version)).requested_version == version


@pytest.mark.parametrize("field", ["plugin_id", "previous_version", "requested_version", "active_version", "status", "events"])
def test_report_contains_stable_fields(field):
    _, runtime = setup_runtime(loaded=False)
    report = PluginUpgradeManager(runtime).upgrade(manifest("2.0.0"))
    assert field in report.to_dict()


@pytest.mark.parametrize("loaded", [True, False])
def test_manifest_is_replaced_for_loaded_and_unloaded_plugins(loaded):
    registry, runtime = setup_runtime(loaded=loaded)
    PluginUpgradeManager(runtime).upgrade(manifest("2.0.0", f"{__name__}:New"))
    assert registry.get("base").version == "2.0.0"


def setup_function():
    EVENTS.clear()
