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

The recovery manager obtains one strong content-fingerprint snapshot when it creates
a journal. It retains that verified set for the execution and refreshes only the
project that just completed before checkpointing its result. This avoids re-reading
and re-hashing every other project after each completion without reducing journal
save frequency, state-save durability, or result-to-content invalidation.

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

M2.1 advances the analysis-result producer fingerprint to v5. Schema-v1 journals
and PR70 state remain readable, but v4 payloads are deliberately invalidated because
an interrupted semantic checkpoint could contain report metadata instead of the full
encoded analysis result.

## Run-scoped verification snapshot

Recovery freshness is still verified with content hashes, never with filenames,
timestamps, or metadata heuristics. A new recovery run computes the complete
workspace snapshot before writing its journal. A resumed run computes a fresh
snapshot and makes it available to state persistence only after the journal's stored
workspace fingerprint matches.

The verified fingerprint set is run-local evidence rather than a persistent cache:

- it is retained only during one `execute()` or `resume()` operation;
- each completed project receives one current content fingerprint before its result
  is published to the journal and PR70 state;
- it is cleared at the operation boundary, including exceptional exits;
- it is not shared between processes or recovery managers;
- it introduces no new on-disk format;
- the PR70 state and PR74 journal schemas remain unchanged.

The integration remains private to the recovery/persistence package and rejects a
verified snapshot unless its project set and order exactly match the current
deterministic workspace. The public `WorkspaceStateStore.capture()` signature and
its fresh-fingerprint behavior remain unchanged.

The journal workspace fingerprint evolves with completion-time project fingerprints.
A content change that remains present can therefore be resumed under matching
evidence, while a later change is rejected by resume or state restore. See
`docs/stability/M2_1_RECOVERY_CHECKPOINT_INVESTIGATION.md` for measurements,
correctness boundaries, and limitations.

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
