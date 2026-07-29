# PR75 Release Notes — Unified CLI

Baseline: PR74 commit `86aa386`

PR75 adds a new `atlas` executable with five unified commands:

- `atlas analyze`
- `atlas check`
- `atlas watch`
- `atlas config`
- `atlas plugins`

The CLI reuses the workspace orchestrator, recovery manager, layered
configuration, watcher, and plugin SDK. It preserves deterministic ordering,
supports concurrent project analysis, and leaves the existing `moughorai`
entry point unchanged.

Structured output formats and continuous watch analysis are intentionally not
included because they belong to PR76 and PR78 respectively.
