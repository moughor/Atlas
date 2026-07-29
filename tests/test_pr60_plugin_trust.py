from __future__ import annotations

import json
from pathlib import Path

import pytest

from moughorai.plugin_sdk import (
    ExtensionPoint,
    PluginDiscovery,
    PluginExtension,
    PluginManifest,
    PluginManifestLoader,
    PluginPermissionPolicy,
    PluginRegistry,
    PluginRuntime,
    PluginTrustError,
    PluginTrustRecord,
    PluginTrustStore,
    manifest_to_json,
    plugin_bundle_digest,
)


def manifest(plugin_id: str = "demo", *, version: str = "1.0.0", permissions=()) -> PluginManifest:
    return PluginManifest(
        plugin_id,
        version,
        "*",
        plugin_id.title(),
        (PluginExtension("main", ExtensionPoint.ANALYZER, f"{__name__}:factory"),),
        permissions=tuple(permissions),
    )


class Instance:
    def __init__(self):
        self.started = False

    def start(self, context):
        self.started = True


def factory(**kwargs):
    return Instance()


def write_plugin(root: Path, item: PluginManifest, *, source: str = "x = 1\n", name="plugin.json") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_text(manifest_to_json(item), encoding="utf-8")
    (root / "plugin_impl.py").write_text(source, encoding="utf-8")
    return path


def test_manifest_permissions_default_empty():
    assert manifest().permissions == ()


def test_manifest_permissions_are_sorted_and_deduplicated():
    assert manifest(permissions=("network", "filesystem", "network")).permissions == ("filesystem", "network")


def test_loader_reads_permissions():
    loaded = PluginManifestLoader().load_json(manifest_to_json(manifest(permissions=("network",))))
    assert loaded.permissions == ("network",)


def test_loader_rejects_non_list_permissions():
    payload = json.loads(manifest_to_json(manifest()))
    payload["permissions"] = "network"
    with pytest.raises(Exception, match="permissions"):
        PluginManifestLoader().load_mapping(payload)


def test_loader_rejects_blank_permission():
    payload = json.loads(manifest_to_json(manifest()))
    payload["permissions"] = [""]
    with pytest.raises(Exception, match="permissions"):
        PluginManifestLoader().load_mapping(payload)


def test_manifest_serialization_contains_permissions():
    payload = json.loads(manifest_to_json(manifest(permissions=("network",))))
    assert payload["permissions"] == ["network"]


def test_manifest_only_digest_is_deterministic():
    item = manifest()
    assert plugin_bundle_digest(item) == plugin_bundle_digest(item)


def test_manifest_digest_changes_with_version():
    assert plugin_bundle_digest(manifest(version="1.0.0")) != plugin_bundle_digest(manifest(version="1.0.1"))


def test_bundle_digest_is_independent_of_include_order(tmp_path):
    item = manifest()
    write_plugin(tmp_path, item)
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "a.txt").write_text("a")
    first = plugin_bundle_digest(item, tmp_path, include=("b.txt", "a.txt"))
    second = plugin_bundle_digest(item, tmp_path, include=("a.txt", "b.txt"))
    assert first == second


def test_bundle_digest_changes_when_file_changes(tmp_path):
    item = manifest(); write_plugin(tmp_path, item)
    first = plugin_bundle_digest(item, tmp_path)
    (tmp_path / "plugin_impl.py").write_text("x = 2\n")
    assert plugin_bundle_digest(item, tmp_path) != first


def test_bundle_digest_rejects_missing_root(tmp_path):
    with pytest.raises(PluginTrustError, match="not a directory"):
        plugin_bundle_digest(manifest(), tmp_path / "missing")


def test_bundle_digest_requires_root_for_include():
    with pytest.raises(PluginTrustError, match="root"):
        plugin_bundle_digest(manifest(), include=("x",))


def test_bundle_digest_rejects_escape(tmp_path):
    with pytest.raises(PluginTrustError, match="escapes"):
        plugin_bundle_digest(manifest(), tmp_path, include=("../escape",))


def test_trust_record_validates_digest():
    with pytest.raises(PluginTrustError, match="SHA-256"):
        PluginTrustRecord("p", "1", "bad")


def test_trust_store_add_get_and_records_order():
    a = PluginTrustRecord("a", "1", "a" * 64)
    b = PluginTrustRecord("b", "1", "b" * 64)
    store = PluginTrustStore((b, a))
    assert store.get("a", "1") == a
    assert [x.plugin_id for x in store.records()] == ["a", "b"]


def test_trust_store_rejects_duplicate():
    record = PluginTrustRecord("a", "1", "a" * 64)
    with pytest.raises(PluginTrustError, match="already exists"):
        PluginTrustStore((record, record))


def test_trust_store_replace():
    store = PluginTrustStore((PluginTrustRecord("a", "1", "a" * 64),))
    store.replace(PluginTrustRecord("a", "1", "b" * 64))
    assert store.get("a", "1").digest == "b" * 64


def test_trust_store_remove():
    record = PluginTrustRecord("a", "1", "a" * 64)
    store = PluginTrustStore((record,))
    assert store.remove("a", "1") == record
    with pytest.raises(PluginTrustError, match="not found"):
        store.remove("a", "1")


def test_trust_store_verify_success():
    item = manifest(); digest = plugin_bundle_digest(item)
    record = PluginTrustRecord(item.plugin_id, item.version, digest)
    assert PluginTrustStore((record,)).verify(item, digest) == record


def test_trust_store_detects_tampering():
    item = manifest(); store = PluginTrustStore((PluginTrustRecord(item.plugin_id, item.version, "a" * 64),))
    with pytest.raises(PluginTrustError, match="integrity"):
        store.verify(item, plugin_bundle_digest(item))


def test_trust_store_detects_untrusted_plugin():
    with pytest.raises(PluginTrustError, match="not trusted"):
        PluginTrustStore().verify(manifest(), "a" * 64)


def test_trust_store_json_round_trip_is_deterministic():
    record = PluginTrustRecord("a", "1", "a" * 64, signer="team", metadata={"z": "2", "a": "1"})
    text = PluginTrustStore((record,)).to_json()
    restored = PluginTrustStore.from_json(text)
    assert restored.to_json() == text


def test_trust_store_rejects_bad_json():
    with pytest.raises(PluginTrustError, match="invalid"):
        PluginTrustStore.from_json("{")


def test_trust_store_rejects_wrong_schema():
    with pytest.raises(PluginTrustError, match="schema"):
        PluginTrustStore.from_json('{"schema_version": 2, "records": []}')


def test_permission_policy_denies_by_default():
    decision = PluginPermissionPolicy().evaluate(manifest(permissions=("network",)))
    assert not decision.allowed and decision.denied == ("network",)


def test_permission_policy_allows_global_permission():
    decision = PluginPermissionPolicy(allowed=("network",)).evaluate(manifest(permissions=("network",)))
    assert decision.allowed and decision.granted == ("network",)


def test_permission_policy_explicit_deny_wins():
    decision = PluginPermissionPolicy(allowed=("network",), denied=("network",)).evaluate(
        manifest(permissions=("network",))
    )
    assert decision.denied == ("network",)


def test_permission_policy_default_allow():
    assert PluginPermissionPolicy(default_allow=True).evaluate(manifest(permissions=("network",))).allowed


def test_permission_policy_per_plugin_allow():
    policy = PluginPermissionPolicy(per_plugin={"demo": ("network",)})
    assert policy.evaluate(manifest(permissions=("network",))).allowed


def test_permission_policy_require_raises():
    with pytest.raises(PluginTrustError, match="denied permissions"):
        PluginPermissionPolicy().require(manifest(permissions=("network",)))


def test_runtime_enforces_permission_policy():
    registry = PluginRegistry(); registry.register(manifest(permissions=("network",)))
    runtime = PluginRuntime(registry, permission_policy=PluginPermissionPolicy())
    with pytest.raises(PluginTrustError, match="network"):
        runtime.load_all()


def test_runtime_loads_when_permissions_granted():
    registry = PluginRegistry(); registry.register(manifest(permissions=("network",)))
    runtime = PluginRuntime(registry, permission_policy=PluginPermissionPolicy(allowed=("network",)))
    assert runtime.load_all()[0].instance.started


def test_discovery_finds_direct_manifest(tmp_path):
    item = manifest(); path = write_plugin(tmp_path, item)
    result = PluginDiscovery().discover((tmp_path,))
    assert result.diagnostics == ()
    assert result.plugins[0].manifest_path == path


def test_discovery_finds_child_plugins_in_stable_order(tmp_path):
    write_plugin(tmp_path / "z", manifest("z"))
    write_plugin(tmp_path / "a", manifest("a"))
    result = PluginDiscovery().discover((tmp_path,))
    assert [x.manifest.plugin_id for x in result.plugins] == ["a", "z"]


def test_discovery_accepts_manifest_file_root(tmp_path):
    path = write_plugin(tmp_path, manifest())
    assert PluginDiscovery().discover((path,)).plugins[0].manifest.plugin_id == "demo"


def test_discovery_ignores_missing_root(tmp_path):
    result = PluginDiscovery().discover((tmp_path / "missing",))
    assert result.plugins == () and result.diagnostics == ()


def test_discovery_reports_invalid_manifest(tmp_path):
    root = tmp_path / "bad"; root.mkdir(); (root / "plugin.json").write_text("{}")
    result = PluginDiscovery().discover((tmp_path,))
    assert result.plugins == ()
    assert result.diagnostics[0].code == "plugin-quarantined"


def test_discovery_reports_duplicate_plugin_ids(tmp_path):
    write_plugin(tmp_path / "one", manifest())
    write_plugin(tmp_path / "two", manifest())
    result = PluginDiscovery().discover((tmp_path,))
    assert len(result.plugins) == 1
    assert any("duplicate discovered plugin" in x.message for x in result.diagnostics)


def test_discovery_marks_trusted_bundle(tmp_path):
    item = manifest(); write_plugin(tmp_path, item)
    digest = plugin_bundle_digest(item, tmp_path)
    store = PluginTrustStore((PluginTrustRecord(item.plugin_id, item.version, digest),))
    result = PluginDiscovery(trust_store=store, require_trust=True).discover((tmp_path,))
    assert result.plugins[0].trusted


def test_discovery_quarantines_tampered_bundle(tmp_path):
    item = manifest(); write_plugin(tmp_path, item)
    digest = plugin_bundle_digest(item, tmp_path)
    store = PluginTrustStore((PluginTrustRecord(item.plugin_id, item.version, digest),))
    (tmp_path / "plugin_impl.py").write_text("tampered")
    result = PluginDiscovery(trust_store=store, require_trust=True).discover((tmp_path,))
    assert result.plugins == ()
    assert "integrity" in result.diagnostics[0].message


def test_discovery_allows_untrusted_when_not_required(tmp_path):
    write_plugin(tmp_path, manifest())
    result = PluginDiscovery(trust_store=PluginTrustStore()).discover((tmp_path,))
    assert not result.plugins[0].trusted


def test_discovery_requires_trust_store_when_enforced(tmp_path):
    write_plugin(tmp_path, manifest())
    result = PluginDiscovery(require_trust=True).discover((tmp_path,))
    assert result.plugins == ()
    assert "not trusted" in result.diagnostics[0].message


def test_discovery_enforces_permissions(tmp_path):
    write_plugin(tmp_path, manifest(permissions=("network",)))
    result = PluginDiscovery(permission_policy=PluginPermissionPolicy()).discover((tmp_path,))
    assert result.plugins == ()
    assert "network" in result.diagnostics[0].message


def test_discovery_reports_granted_permissions(tmp_path):
    write_plugin(tmp_path, manifest(permissions=("network",)))
    policy = PluginPermissionPolicy(allowed=("network",))
    plugin = PluginDiscovery(permission_policy=policy).discover((tmp_path,)).plugins[0]
    assert plugin.granted_permissions == ("network",)
