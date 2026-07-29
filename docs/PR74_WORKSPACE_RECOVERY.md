# PR74 — Workspace Recovery Manager

PR74 adds durable recovery for workspace analysis that is interrupted by a process
exit, crash, or other `BaseException`. Recovery is opt-in, so existing
`WorkspaceAnalysisOrchestrator` callers and reports remain compatible.

## Journal

`WorkspaceRecoveryManager` writes
`.atlas/workspace-recovery.json` by default. Each update uses an atomic temporary
file replacement and a SHA-256 checksum. The journal contains:

- schema, workspace, and resolved-configuration fingerprints;
- the sorted request and deterministic topological analysis order;
- `completed`, `running`, `failed`, or `pending` state for every project;
- encoded successful results and timezone-aware timestamps.

A project is marked `running` before its analyzer is invoked. Successful results
are marked `completed` and are also captured by the PR70
`WorkspaceStateStore`. Failed projects remain retryable. Blocked and cancelled
projects return to `pending`.

## Usage

```python
from moughorai.workspace import (
    WorkspaceAnalysisOrchestrator,
    WorkspaceRecoveryManager,
    WorkspaceService,
)

service = WorkspaceService("/workspace")
orchestrator = WorkspaceAnalysisOrchestrator(service)
recovery = WorkspaceRecoveryManager(service)

# Use this in place of orchestrator.execute(...) for a recoverable run.
report = recovery.execute(orchestrator, analyze, max_workers=4)

# In a later process, resume if a valid journal exists.
orchestrator = WorkspaceAnalysisOrchestrator(service)
report, recovery_report = WorkspaceRecoveryManager(service).resume(
    orchestrator,
    analyze,
    max_workers=4,
)
```

`resume` restores completed results without calling their analyzer. It schedules
only unfinished projects, while PR73's dependency-aware executor may include
completed dependencies as deterministic `reused` entries in its report.

Use `inspect()` to obtain sorted status groups without starting analysis:

```python
status = recovery.inspect()
print(status.completed, status.running, status.failed, status.pending)
```

## Configuration

A PR71 `ResolvedConfiguration` can be supplied to the manager:

```yaml
recovery:
  enabled: true
  path: /workspace/.atlas/custom-recovery.json
  max_age_seconds: 86400
```

- `recovery.enabled` defaults to `true`. When false, `execute` delegates directly
  to the existing orchestrator and does not write a journal.
- `recovery.path` overrides the default journal path.
- `recovery.max_age_seconds` invalidates journals older than the configured age.

The complete resolved configuration is fingerprinted. Changing it prevents
results created under different analysis settings from being reused.

## Validation and invalidation

The manager deletes a journal and emits `recovery_invalidated` when it detects:

- malformed JSON, an invalid envelope, or a checksum mismatch;
- an unsupported schema or inconsistent project/status data;
- changed workspace content or project membership;
- changed resolved configuration;
- a journal older than `max_age_seconds`;
- a result that the configured decoder cannot restore.

Invalid journals are never partially reused. `WorkspaceRecoveryReport` records
the exact invalidation reason.

## Events

PR74 extends the PR72 event bus with:

- `recovery_started`
- `recovery_journal_saved`
- `recovery_resumed`
- `recovery_invalidated`
- `recovery_completed`

Journal mutation is guarded by a re-entrant lock, allowing PR73 worker completion
events to update durable recovery state safely. Existing event kinds and
subscribers remain unchanged.

## Custom result serialization

Pass matching `encoder` and `decoder` callables when analyzer values are not JSON
serializable. They are also supplied to the underlying PR70 state store.

```python
manager = WorkspaceRecoveryManager(
    service,
    encoder=lambda value: value.to_dict(),
    decoder=Result.from_dict,
)
```
