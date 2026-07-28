from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from moughorai.plugin_sdk import (
    ExtensionPoint,
    PluginCompatibilityError,
    PluginContext,
    PluginExtension,
    PluginLoadError,
    PluginManifest,
    PluginManifestError,
    PluginManifestLoader,
    PluginRegistry,
    PluginRuntime,
    manifest_to_json,
    manifest_to_yaml,
)


class DemoExtension:
    def __init__(self, context=None, config=None):
        self.context = context
        self.config = config or {}
        self.started = False
        self.stopped = False

    def start(self, context):
        self.started = True

    def stop(self, context):
        self.stopped = True


def demo_factory(context=None, config=None):
    return DemoExtension(context, config)


def broken_factory(context=None, config=None):
    raise RuntimeError("boom")


def manifest(plugin_id="demo", *, requires=(), api_version="^1.0.0", factory=None, extensions=True):
    ext = ()
    if extensions:
        ext = (PluginExtension("main", ExtensionPoint.ANALYZER, factory or f"{__name__}:demo_factory", ("java",), {"x": 1}),)
    return PluginManifest(plugin_id, "1.2.3", api_version, plugin_id.title(), ext, requires=requires)


def test_extension_normalizes_capabilities_and_config():
    ext = PluginExtension("x", ExtensionPoint.REPORTER, "a:b", ("z", "a", "z"), {"k": 1})
    assert ext.capabilities == ("a", "z")
    assert dict(ext.config) == {"k": 1}
    with pytest.raises(TypeError):
        ext.config["x"] = 2


@pytest.mark.parametrize("factory", ["bad", "", "module"])
def test_extension_rejects_invalid_factory(factory):
    with pytest.raises(PluginManifestError):
        PluginExtension("x", ExtensionPoint.ANALYZER, factory)


def test_manifest_rejects_duplicate_extension_names():
    ext = PluginExtension("x", ExtensionPoint.ANALYZER, "a:b")
    with pytest.raises(PluginManifestError):
        PluginManifest("p", "1.0.0", "*", "P", (ext, ext))


def test_manifest_sorts_extensions_and_dependencies():
    a = PluginExtension("z", ExtensionPoint.REPORTER, "a:b")
    b = PluginExtension("a", ExtensionPoint.ANALYZER, "a:b")
    item = PluginManifest("p", "1", "*", "P", (a, b), requires=("z", "a", "a"))
    assert [x.name for x in item.extensions] == ["a", "z"]
    assert item.requires == ("a", "z")


def test_loader_reads_yaml_and_json(tmp_path):
    payload = {
        "id": "demo", "version": "1.0.0", "api_version": "^1.0.0", "name": "Demo",
        "extensions": [{"name": "a", "point": "analyzer", "factory": f"{__name__}:demo_factory"}],
    }
    loader = PluginManifestLoader()
    assert loader.load_json(json.dumps(payload)).plugin_id == "demo"
    assert loader.load_yaml(manifest_to_yaml(loader.load_mapping(payload))).plugin_id == "demo"
    path = tmp_path / "plugin.json"
    path.write_text(json.dumps(payload))
    assert loader.load_path(path).name == "Demo"


def test_loader_rejects_unknown_root_field():
    data = {"id":"p","version":"1","api_version":"*","name":"P","extensions":[],"wat":1}
    with pytest.raises(PluginManifestError, match="unknown"):
        PluginManifestLoader().load_mapping(data)


def test_loader_rejects_unknown_extension_field():
    data = {"id":"p","version":"1","api_version":"*","name":"P","extensions":[{"name":"x","point":"analyzer","factory":"a:b","wat":1}]}
    with pytest.raises(PluginManifestError, match="unknown"):
        PluginManifestLoader().load_mapping(data)


@pytest.mark.parametrize("field", ["id", "version", "api_version", "name", "extensions"])
def test_loader_requires_fields(field):
    data = {"id":"p","version":"1","api_version":"*","name":"P","extensions":[]}
    del data[field]
    with pytest.raises(PluginManifestError, match="missing"):
        PluginManifestLoader().load_mapping(data)


def test_loader_rejects_invalid_extension_point():
    data = {"id":"p","version":"1","api_version":"*","name":"P","extensions":[{"name":"x","point":"wat","factory":"a:b"}]}
    with pytest.raises(PluginManifestError, match="unknown extension point"):
        PluginManifestLoader().load_mapping(data)


def test_loader_rejects_bad_yaml_and_json():
    loader = PluginManifestLoader()
    with pytest.raises(PluginManifestError): loader.load_json("{")
    with pytest.raises(PluginManifestError): loader.load_yaml("[not: valid")


def test_loader_rejects_unsupported_suffix(tmp_path):
    path = tmp_path / "plugin.txt"; path.write_text("x")
    with pytest.raises(PluginManifestError, match="unsupported"):
        PluginManifestLoader().load_path(path)


def test_registry_register_get_unregister():
    registry = PluginRegistry()
    item = manifest()
    registry.register(item)
    assert registry.get("demo") == item
    assert registry.unregister("demo") == item
    with pytest.raises(PluginManifestError): registry.get("demo")


def test_registry_rejects_duplicate_plugin():
    registry = PluginRegistry(); registry.register(manifest())
    with pytest.raises(PluginManifestError, match="already"):
        registry.register(manifest())


def test_registry_rejects_incompatible_api():
    registry = PluginRegistry(api_version="1.0.0")
    with pytest.raises(PluginCompatibilityError):
        registry.register(manifest(api_version=">=2.0.0"))


def test_registry_dependency_order_is_deterministic():
    registry = PluginRegistry()
    registry.register(manifest("child", requires=("base",)))
    registry.register(manifest("base"))
    assert [x.plugin_id for x in registry.resolve_order()] == ["base", "child"]


def test_registry_missing_dependency():
    registry = PluginRegistry(); registry.register(manifest("child", requires=("base",)))
    with pytest.raises(PluginManifestError, match="missing"):
        registry.resolve_order()


def test_registry_dependency_cycle():
    registry = PluginRegistry(); registry.register(manifest("a", requires=("b",))); registry.register(manifest("b", requires=("a",)))
    with pytest.raises(PluginManifestError, match="cycle"):
        registry.resolve_order()


def test_registry_filters_extension_points():
    registry = PluginRegistry(); registry.register(manifest())
    assert len(registry.extensions("analyzer")) == 1
    assert registry.extensions(ExtensionPoint.REPORTER) == ()


def test_registry_diagnostics_empty_plugin():
    registry = PluginRegistry(); registry.register(manifest(extensions=False))
    assert registry.diagnostics()[0].code == "empty-plugin"


def test_registry_diagnostics_duplicate_extension_names_across_plugins():
    registry = PluginRegistry(); registry.register(manifest("a")); registry.register(manifest("b"))
    assert any(d.code == "duplicate-extension-name" for d in registry.diagnostics())


def test_runtime_load_start_and_unload_stop():
    registry = PluginRegistry(); registry.register(manifest())
    runtime = PluginRuntime(registry, services={"db":"service"})
    loaded = runtime.load("demo")
    assert loaded[0].instance.started
    assert loaded[0].instance.context.require("db") == "service"
    runtime.unload("demo")
    assert loaded[0].instance.stopped


def test_runtime_is_idempotent():
    registry = PluginRegistry(); registry.register(manifest())
    runtime = PluginRuntime(registry)
    assert runtime.load("demo") is runtime.load("demo")


def test_runtime_loads_dependencies_first():
    registry = PluginRegistry(); registry.register(manifest("child", requires=("base",))); registry.register(manifest("base"))
    runtime = PluginRuntime(registry)
    runtime.load("child")
    assert [x.plugin_id for x in runtime.extensions()] == ["base", "child"]


def test_runtime_refuses_unload_with_loaded_dependents():
    registry = PluginRegistry(); registry.register(manifest("base")); registry.register(manifest("child", requires=("base",)))
    runtime = PluginRuntime(registry); runtime.load_all()
    with pytest.raises(PluginLoadError, match="dependents"):
        runtime.unload("base")


def test_runtime_unload_all_reverse_dependency_order():
    registry = PluginRegistry(); registry.register(manifest("base")); registry.register(manifest("child", requires=("base",)))
    runtime = PluginRuntime(registry); loaded = runtime.load_all(); runtime.unload_all()
    assert all(x.instance.stopped for x in loaded)


def test_runtime_reports_missing_factory():
    registry = PluginRegistry(); registry.register(manifest(factory="does.not.exist:factory"))
    with pytest.raises(PluginLoadError, match="resolve"):
        PluginRuntime(registry).load_all()


def test_runtime_wraps_factory_failure_and_rolls_back():
    good = PluginExtension("a", ExtensionPoint.ANALYZER, f"{__name__}:demo_factory")
    bad = PluginExtension("b", ExtensionPoint.REPORTER, f"{__name__}:broken_factory")
    registry = PluginRegistry(); registry.register(PluginManifest("p","1.0.0","*","P",(good,bad)))
    with pytest.raises(PluginLoadError, match="failed to load"):
        PluginRuntime(registry).load_all()


def test_context_require_and_copy():
    context = PluginContext({"x":1})
    assert context.get("x") == 1
    assert context.as_dict() == {"x":1}
    with pytest.raises(PluginLoadError): context.require("missing")


def test_serialization_is_deterministic_and_round_trips():
    item = manifest()
    first = manifest_to_json(item)
    second = manifest_to_json(item)
    assert first == second
    loaded = PluginManifestLoader().load_json(first)
    assert loaded.plugin_id == item.plugin_id
    assert manifest_to_json(loaded) == first


def test_loaded_extensions_have_stable_order():
    reporter = PluginExtension("z", ExtensionPoint.REPORTER, f"{__name__}:demo_factory")
    analyzer = PluginExtension("a", ExtensionPoint.ANALYZER, f"{__name__}:demo_factory")
    registry = PluginRegistry(); registry.register(PluginManifest("p","1.0.0","*","P",(reporter, analyzer)))
    runtime = PluginRuntime(registry); runtime.load_all()
    assert [x.extension.name for x in runtime.extensions()] == ["a", "z"]
