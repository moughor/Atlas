# PR64 — Policy Pack Lifecycle Manager

PR64 adds a transactional lifecycle manager for versioned policy packs.

## Capabilities

- install, activate, deactivate, uninstall, upgrade and optional downgrade;
- dependency-aware cascade operations;
- semantic engine compatibility through the `engine_api` metadata key;
- active rule conflict detection;
- transactional validation and automatic upgrade rollback;
- deterministic events and JSON reports;
- deterministic lifecycle state export/import;
- direct construction of a `PolicyPackRegistry` from active packs.

Existing loaders, registries, resolvers and policy-pack formats remain compatible.
