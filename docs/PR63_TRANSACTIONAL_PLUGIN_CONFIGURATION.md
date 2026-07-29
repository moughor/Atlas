# PR63 — Transactional Plugin Configuration

PR63 adds immutable, versioned plugin configuration profiles and transactional runtime reconfiguration.

## Capabilities

- deterministic JSON profile serialization and parsing;
- strict schema and extension-name validation;
- merge-based extension configuration overrides;
- no-op detection;
- dependency-aware unload/restart orchestration;
- atomic manifest replacement;
- automatic rollback when construction or startup fails;
- stable event histories and machine-readable reports.

Existing manifests and PR59–PR62 runtime APIs remain compatible. Configuration profiles are optional and are applied explicitly through `PluginConfigurationManager`.
