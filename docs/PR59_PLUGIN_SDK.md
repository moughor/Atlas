# PR59 — Plugin SDK and Extension System

PR59 introduces a deterministic, transport-neutral plugin layer for Atlas.

## Capabilities

- Strict YAML and JSON plugin manifests.
- Semantic API compatibility constraints.
- Analyzer, policy-pack, and reporter extension points.
- Deterministic dependency resolution and cycle detection.
- Lifecycle hooks (`start` and `stop`).
- Dependency injection through `PluginContext`.
- Stable discovery, loading, diagnostics, and serialization.
- Safe rollback when a plugin fails during startup.

## Manifest example

```yaml
id: example.security
version: 1.0.0
api_version: ^1.0.0
name: Example Security Plugin
requires: []
extensions:
  - name: example-analyzer
    point: analyzer
    factory: example_plugin:build_analyzer
    capabilities: [java, security]
    config:
      strict: true
```

Factories use `module:attribute` syntax. The runtime first attempts
`factory(context=..., config=...)`, then `factory(config=...)`, then `factory()`.

## Compatibility

PR59 is additive and does not modify the PR58 distributed coordinator or any
existing public incremental-analysis API.
