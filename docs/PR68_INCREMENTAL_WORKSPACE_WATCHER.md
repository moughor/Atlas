# PR68 — Incremental Workspace Watcher

PR68 adds a portable, deterministic file-watching and incremental planning layer on top of the PR67 workspace model.

## Capabilities

- Polling-based snapshots with no platform-specific dependency.
- Creation, modification, deletion, and rename events.
- Include/exclude-aware project file enumeration.
- Nested-project ownership resolution.
- Deterministic event ordering and serialization.
- Configurable debounce windows and event coalescing.
- Incremental invalidation of directly changed projects and all dependents.
- Stable analysis order inherited from the workspace dependency graph.
- Explicit validity tracking for selective cache refresh workflows.

## Main APIs

- `WorkspaceWatcher.start()` captures an initial snapshot.
- `WorkspaceWatcher.poll()` detects and optionally flushes changes.
- `WorkspaceWatcher.flush()` emits mature debounced events.
- `IncrementalWorkspacePlanner.plan()` converts events into an ordered invalidation plan.
- `IncrementalWorkspacePlanner.mark_plan_valid()` marks successfully re-analysed projects valid again.

The implementation deliberately avoids native OS watcher APIs so tests and behavior remain consistent on Windows, Linux, and macOS.
