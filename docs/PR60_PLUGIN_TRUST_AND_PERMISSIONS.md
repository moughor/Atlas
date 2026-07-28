# PR60 — Plugin Trust, Integrity, and Permission Enforcement

PR60 adds an opt-in security layer to the PR59 plugin SDK. Existing manifests remain valid; plugins only need a `permissions` field when they request protected capabilities, and runtimes only enforce a policy when one is supplied.

## Capabilities

- Deterministic SHA-256 digests for plugin manifests and bundle files
- Versioned trust records and deterministic JSON trust stores
- Constant-time digest verification
- Global allow/deny permission rules
- Per-plugin permission grants
- Explicit deny precedence
- Runtime permission enforcement
- Secure plugin discovery from manifest files or plugin directories
- Stable discovery ordering and duplicate-plugin detection
- Tampered, invalid, untrusted, or unauthorized plugin quarantine diagnostics
- Rejection of bundle path traversal and symbolic links

## Manifest permissions

```yaml
id: acme.security
version: 1.0.0
api_version: "^1.0.0"
name: Acme Security
permissions:
  - filesystem.read
  - network.client
extensions:
  - name: analyzer
    point: analyzer
    factory: acme_plugin:build
```

Permissions are normalized, sorted, and deduplicated. Empty or non-string permissions are rejected by the strict manifest loader.

## Trust records

```python
from moughorai.plugin_sdk import (
    PluginTrustRecord,
    PluginTrustStore,
    plugin_bundle_digest,
)

digest = plugin_bundle_digest(manifest, plugin_root)
store = PluginTrustStore((
    PluginTrustRecord(manifest.plugin_id, manifest.version, digest, signer="Acme"),
))
store.verify(manifest, digest)
```

Trust is keyed by plugin id and version. Updating a plugin requires a new digest record.

## Permission enforcement

```python
from moughorai.plugin_sdk import PluginPermissionPolicy, PluginRuntime

policy = PluginPermissionPolicy(
    allowed=("filesystem.read",),
    denied=("process.execute",),
    per_plugin={"acme.security": ("network.client",)},
)
runtime = PluginRuntime(registry, permission_policy=policy)
runtime.load_all()
```

Explicit denies always win. The default policy denies requested permissions unless `default_allow=True` or a global/per-plugin grant exists.

## Secure discovery

```python
from moughorai.plugin_sdk import PluginDiscovery

result = PluginDiscovery(
    trust_store=store,
    permission_policy=policy,
    require_trust=True,
).discover(("plugins",))
```

Valid plugins appear in `result.plugins`. Rejected plugins appear as deterministic `plugin-quarantined` diagnostics without stopping discovery of independent plugins.

## Compatibility

- PR59 manifests without `permissions` load unchanged.
- `PluginRuntime` behavior is unchanged when no permission policy is passed.
- Trust enforcement is opt-in through `PluginDiscovery(require_trust=True)`.
