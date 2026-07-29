from __future__ import annotations

import json
import sys
import types

import pytest

from moughorai.plugin_sdk import (
    ExtensionPoint, PluginConfigurationError, PluginConfigurationManager,
    PluginConfigurationProfile, PluginExtension, PluginManifest, PluginManifestError,
    PluginRegistry, PluginRuntime, ReconfigurationStatus,
)


class Demo:
    created = []
    fail = False

    def __init__(self, config=None, **kwargs):
        if self.fail or (config or {}).get("fail"):
            raise RuntimeError("boom")
        self.config = dict(config or {})
        self.started = False
        self.stopped = False
        type(self).created.append(self)

    def start(self, context): self.started = True
    def stop(self, context): self.stopped = True


@pytest.fixture(autouse=True)
def module_fixture():
    Demo.created = []
    Demo.fail = False
    module = types.ModuleType("pr63_demo")
    module.Demo = Demo
    sys.modules["pr63_demo"] = module
    yield
    sys.modules.pop("pr63_demo", None)


def manifest(pid="core", *, requires=(), config=None, names=("main",)):
    return PluginManifest(
        pid, "1.0.0", ">=1.0.0,<2.0.0", pid.title(),
        tuple(PluginExtension(name, ExtensionPoint.ANALYZER, "pr63_demo:Demo", config=config or {}) for name in names),
        requires=requires,
    )


def setup_runtime(*manifests):
    registry = PluginRegistry()
    for item in manifests: registry.register(item)
    runtime = PluginRuntime(registry)
    runtime.load_all()
    return registry, runtime


def test_profile_rejects_empty_name():
    with pytest.raises(PluginManifestError): PluginConfigurationProfile(" ")


def test_profile_rejects_empty_extension_name():
    with pytest.raises(PluginManifestError): PluginConfigurationProfile("x", {"": {}})


def test_profile_rejects_non_mapping_config():
    with pytest.raises(PluginManifestError): PluginConfigurationProfile("x", {"main": 3})


def test_profile_is_immutable():
    profile = PluginConfigurationProfile("x", {"main": {"a": 1}})
    with pytest.raises(TypeError): profile.values["main"]["a"] = 2


def test_profile_json_roundtrip():
    profile = PluginConfigurationProfile("prod", {"main": {"workers": 4}})
    assert PluginConfigurationProfile.from_json(profile.to_json()) == profile


def test_profile_json_is_deterministic():
    profile = PluginConfigurationProfile("prod", {"z": {"b": 2}, "a": {"a": 1}})
    assert profile.to_json() == profile.to_json()
    assert list(json.loads(profile.to_json())["values"]) == ["a", "z"]


def test_profile_rejects_unknown_fields():
    with pytest.raises(PluginManifestError): PluginConfigurationProfile.from_dict({"name": "x", "values": {}, "extra": 1})


def test_profile_rejects_schema_version():
    with pytest.raises(PluginManifestError): PluginConfigurationProfile.from_dict({"schema_version": 2, "name": "x", "values": {}})


def test_profile_rejects_invalid_json():
    with pytest.raises(PluginManifestError): PluginConfigurationProfile.from_json("{")


def test_profile_rejects_non_object_json():
    with pytest.raises(PluginManifestError): PluginConfigurationProfile.from_json("[]")


def test_apply_updates_extension_config_and_restarts_loaded_plugin():
    registry, runtime = setup_runtime(manifest(config={"a": 1}))
    first = Demo.created[-1]
    report = PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("prod", {"main": {"b": 2}}))
    assert report.status is ReconfigurationStatus.APPLIED
    assert report.changed_extensions == ("main",)
    assert first.stopped
    assert Demo.created[-1].config == {"a": 1, "b": 2}
    assert dict(registry.get("core").extensions[0].config) == {"a": 1, "b": 2}


def test_apply_to_unloaded_plugin_does_not_load_it():
    registry = PluginRegistry(); registry.register(manifest(config={"a": 1}))
    runtime = PluginRuntime(registry)
    report = PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("prod", {"main": {"a": 2}}))
    assert report.status is ReconfigurationStatus.APPLIED
    assert runtime.extensions() == ()


def test_no_change_returns_no_change_without_restart():
    registry, runtime = setup_runtime(manifest(config={"a": 1}))
    before = Demo.created[-1]
    report = PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("same", {"main": {"a": 1}}))
    assert report.status is ReconfigurationStatus.NO_CHANGE
    assert Demo.created[-1] is before
    assert not before.stopped


def test_partial_profile_preserves_other_extensions():
    registry, runtime = setup_runtime(manifest(names=("a", "b"), config={"x": 1}))
    PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("p", {"b": {"y": 2}}))
    configs = {e.name: dict(e.config) for e in registry.get("core").extensions}
    assert configs == {"a": {"x": 1}, "b": {"x": 1, "y": 2}}


def test_unknown_extension_is_rejected_before_mutation():
    registry, runtime = setup_runtime(manifest())
    old = registry.get("core")
    with pytest.raises(PluginConfigurationError):
        PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("x", {"missing": {}}))
    assert registry.get("core") is old


def test_loaded_direct_dependent_is_restarted():
    registry, runtime = setup_runtime(manifest("core"), manifest("child", requires=("core",)))
    old_child = next(x.instance for x in runtime.extensions() if x.plugin_id == "child")
    report = PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("x", {"main": {"v": 2}}))
    assert report.restarted_plugins == ("child",)
    assert old_child.stopped


def test_loaded_transitive_dependents_are_restarted_in_dependency_order():
    registry, runtime = setup_runtime(manifest("core"), manifest("child", requires=("core",)), manifest("leaf", requires=("child",)))
    report = PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("x", {"main": {"v": 2}}))
    assert report.restarted_plugins == ("child", "leaf")


def test_unloaded_dependents_are_not_started():
    registry = PluginRegistry()
    for item in (manifest("core"), manifest("child", requires=("core",))): registry.register(item)
    runtime = PluginRuntime(registry); runtime.load("core")
    report = PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("x", {"main": {"v": 2}}))
    assert report.restarted_plugins == ()
    assert {x.plugin_id for x in runtime.extensions()} == {"core"}


def test_failed_new_configuration_rolls_back_manifest_and_runtime():
    registry, runtime = setup_runtime(manifest(config={"a": 1}))
    report = PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("bad", {"main": {"fail": True}}))
    assert report.status is ReconfigurationStatus.ROLLED_BACK
    assert dict(registry.get("core").extensions[0].config) == {"a": 1}
    assert Demo.created[-1].config == {"a": 1}


def test_failed_reconfiguration_reports_error():
    registry, runtime = setup_runtime(manifest())
    report = PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("bad", {"main": {"fail": True}}))
    assert "boom" in report.error


def test_events_have_stable_sequence_numbers():
    registry, runtime = setup_runtime(manifest())
    report = PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("x", {"main": {"v": 2}}))
    assert [e.sequence for e in report.events] == list(range(1, len(report.events) + 1))


def test_report_json_is_deterministic():
    registry, runtime = setup_runtime(manifest())
    report = PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("x", {"main": {"v": 2}}))
    assert report.to_json() == report.to_json()
    assert json.loads(report.to_json())["status"] == "applied"


@pytest.mark.parametrize("value", [None, False, 0, "", [], {"nested": True}])
def test_configuration_values_are_preserved(value):
    registry, runtime = setup_runtime(manifest())
    PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("x", {"main": {"value": value}}))
    assert Demo.created[-1].config["value"] == value


def test_profile_extension_order_does_not_affect_output():
    a = PluginConfigurationProfile("x", {"b": {"x": 2}, "a": {"x": 1}})
    b = PluginConfigurationProfile("x", {"a": {"x": 1}, "b": {"x": 2}})
    assert a.to_json() == b.to_json()


def test_changed_extensions_are_sorted():
    registry, runtime = setup_runtime(manifest(names=("z", "a")))
    report = PluginConfigurationManager(runtime).apply("core", PluginConfigurationProfile("x", {"z": {"v": 1}, "a": {"v": 1}}))
    assert report.changed_extensions == ("a", "z")
