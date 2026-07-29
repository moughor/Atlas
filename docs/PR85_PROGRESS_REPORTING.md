# PR85 Progress Reporting

`WorkDoneProgressReporter` emits standard LSP progress creation and
`$/progress` notifications. Tokens are stable within a server session
(`atlas-1`, `atlas-2`, ...).

A task emits `begin`, zero or more `report`, and one idempotent `end` value.
Known totals produce integer completion percentages. Tasks expose cancellation
state and the server accepts `window/workDoneProgress/cancel`.

`workspace/diagnostic` creates a progress stream and reports each open document
in deterministic URI order. Messages are delivered through the PR84 outgoing
notification queue and can be consumed with `drain_notifications()`.
