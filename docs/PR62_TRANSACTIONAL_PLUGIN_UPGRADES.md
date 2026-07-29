# PR62 — Transactional Plugin Upgrades

PR62 adds a deterministic, dependency-aware upgrade coordinator to the plugin SDK.

## Guarantees

- Validates API and semantic-version compatibility before changing runtime state.
- Rejects equal versions and downgrades unless explicitly allowed.
- Drains and unloads loaded dependents in reverse dependency order.
- Exports extension state before replacement and imports it into the new version.
- Replaces manifests atomically through `PluginRegistry.replace`.
- Restarts dependents in dependency order.
- Rolls back the manifest, runtime, and exported state when loading or restoration fails.
- Produces immutable, deterministic upgrade events and JSON reports.

## Optional hooks

Extensions may implement:

- `begin_drain(context)` before shutdown;
- `export_state()` to provide migration state;
- `import_state(state)` to restore it after loading.

The existing `start(context)` and `stop(context)` lifecycle hooks are unchanged.

## Policy

`PluginUpgradePolicy` controls downgrade allowance, strict state restoration, and whether loaded dependents may be restarted automatically.
