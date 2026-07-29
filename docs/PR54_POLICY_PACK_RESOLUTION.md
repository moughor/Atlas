# PR54 — Policy Pack Dependency Resolution and Lockfiles

PR54 adds reproducible dependency management to the versioned policy packs introduced in PR53.

## Features

- Semantic versions (`major.minor.patch`) with exact, comparison, caret, tilde, and compound constraints.
- Required and optional pack dependencies.
- Deterministic topological ordering with dependencies before dependants.
- Missing dependency, incompatible version, duplicate pack, and cycle diagnostics.
- SHA-256 pack integrity digests over canonical serialized content.
- Deterministic JSON lockfiles with dependency metadata.
- Lockfile verification to detect version, content, or dependency drift.
- Registry helpers for resolving selected roots, generating locks, and building engines from resolved packs.

## Pack format

```yaml
name: web-security
version: 2.1.0
dependencies:
  - name: core-security
    constraint: ^1.4.0
  - name: cloud-extensions
    constraint: ~3.2.0
    optional: true
policies: []
```

Dependencies are optional, so every valid PR53 pack remains valid in PR54.

## Version constraints

Supported forms include `*`, `1.2.3`, `==1.2.3`, `>=1.0.0`, `<2.0.0`, `>=1.0.0,<2.0.0`, `^1.2.3`, and `~1.2.3`.

## Lockfiles

`PolicyPackResolver.lock()` produces a deterministic `PolicyPackLock`. Each locked pack records its name, version, SHA-256 digest, and declared dependencies. `verify()` fails when installed packs no longer reproduce the lock.

## Compatibility

PR54 extends `PolicyPack` with a default-empty `dependencies` field and keeps the existing loader, registry, serialization, and taint-engine APIs backward compatible.
