# PR74 Release Notes — Workspace Recovery Manager

Baseline: PR73 commit `750bf22e7c916101002f852a530120682e259141`

PR74 adds opt-in, crash-safe recovery to workspace analysis.

## Highlights

- Durable atomic journal with checksum, schema, fingerprints, and timestamps.
- Deterministic classification of completed, running, failed, and pending projects.
- Selective resume: completed analyzers are not run again; unfinished work uses
  the existing dependency-aware concurrent scheduler.
- Strict invalidation for corrupt, inconsistent, stale, workspace-changed, or
  configuration-changed recovery data.
- Successful results are persisted through the PR70 workspace state store.
- Recovery settings use PR71 resolved configuration.
- Recovery lifecycle is observable through new PR72 event kinds.
- Journal updates are synchronized for PR73 concurrent workers.
- Existing orchestrator APIs and report ordering remain compatible.

## Public API

The `moughorai.workspace` package now exports:

- `RECOVERY_SCHEMA_VERSION`
- `RecoveryProject`
- `RecoveryProjectStatus`
- `WorkspaceRecoveryError`
- `WorkspaceRecoveryJournal`
- `WorkspaceRecoveryManager`
- `WorkspaceRecoveryReport`

See `docs/PR74_WORKSPACE_RECOVERY.md` for usage and configuration.
