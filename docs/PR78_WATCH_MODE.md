# PR78 Watch Mode

`atlas watch` now supports continuous workspace analysis. The existing command
without options remains a deterministic one-shot snapshot.

Use `atlas watch . --continuous` for an unbounded loop, or
`atlas watch . --iterations 10` for a bounded run suitable for automation.
`--interval` controls polling frequency and `--workers` retains concurrent
project execution.

Changed files are debounced by `WorkspaceWatcher`. `WorkspaceWatchManager`
passes each event batch to the incremental planner, invalidates affected cached
results, and analyzes only the changed projects and their dependents. Idle
polls do not create reports.

The manager accepts injected sleep and stop callbacks so hosts can implement
cooperative shutdown and deterministic tests without changing public analysis
APIs.
