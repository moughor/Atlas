# PR108 — Workspace Context Builder

`WorkspaceContextBuilder` converts authoritative Atlas results into compact,
deterministic semantic JSON for AI consumers. It accepts workspace projects,
diagnostics, historical runs, global symbols, semantic type tables, and profile
metrics. Collections and mapping keys are normalized into stable order.

The builder does not analyze source code and does not let model output replace
Atlas facts. Unsupported values and unstable semantic node keys fail explicitly
instead of leaking process-specific representations into prompts or reports.
