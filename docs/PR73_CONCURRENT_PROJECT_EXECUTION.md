# PR73 — Concurrent Project Execution

PR73 adds dependency-aware concurrent execution to the workspace analysis orchestrator.

## API

`WorkspaceAnalysisOrchestrator.execute()` and `execute_plan()` accept:

- `max_workers`: maximum number of concurrent analyzers. The default is `1`, preserving the existing sequential behavior.
- `fail_fast`: after the first analyzer failure, stop scheduling unrelated pending work. Dependency failures still produce `blocked` runs.

## Scheduling guarantees

- A project is scheduled only after every selected dependency has completed.
- Independent projects may execute concurrently.
- Analyzer inputs contain completed dependency results.
- Failed or cancelled dependencies block their dependents.
- Reports remain ordered according to the workspace topological order, regardless of task completion order.
- Cached valid results are reused without occupying worker threads.
- Successful results are cached; failed results are invalidated.
- Existing workspace events are emitted for concurrent execution.

## Example

```python
report = orchestrator.execute(
    analyzer,
    projects=["frontend", "backend"],
    max_workers=4,
    fail_fast=False,
)
```

Use `max_workers=1` when an analyzer is not thread-safe.
