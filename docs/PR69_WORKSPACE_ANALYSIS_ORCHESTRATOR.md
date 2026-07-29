# PR69 — Workspace Analysis Orchestrator

PR69 adds deterministic workspace-level analysis execution on top of the PR67 project graph and PR68 incremental planner.

## Capabilities

- dependency-ordered project execution;
- selective execution with optional dependency expansion;
- valid-result reuse and explicit forced execution;
- dependency result injection into project analyzers;
- structured success, failure, blocked, reused, and cancelled states;
- failure isolation for independent projects;
- dependent-project blocking after failures or cancellation;
- cache invalidation and incremental-plan execution;
- deterministic reports and serialization.

The orchestrator is analyzer-agnostic: callers provide a function receiving a `Project` and a mapping of direct dependency results.
