# PR75 — Unified CLI

PR75 introduces the `atlas` executable while preserving the existing
`moughorai` entry point.

## Commands

```text
atlas analyze [ROOT]
atlas check [ROOT]
atlas watch [ROOT]
atlas config [ROOT]
atlas plugins [ROOT]
```

All commands use deterministic plain-text output and return exit code `2` for
invalid workspace input or configuration errors.

### `atlas analyze`

Runs dependency-aware workspace analysis. Repeated `--project` options select
projects, `--workers` controls PR73 concurrency, `--force` disables reuse, and
`--recover` enables PR74 interrupted-run recovery (the default).

### `atlas check`

Runs the same workspace pipeline and returns exit code `1` when any project
fails or is blocked. This is the stable automation-oriented entry point.

### `atlas watch`

Loads the workspace and initializes a deterministic watcher snapshot, reporting
project and tracked-file counts. Continuous analysis is intentionally deferred
to PR78.

### `atlas config`

Without `--project`, lists workspace options. With `--project`, resolves the
PR71 workspace/project configuration and prints flattened keys in sorted order.

### `atlas plugins`

Discovers plugin manifests beneath `ROOT/plugins`, or beneath repeated explicit
`--plugin-root` values. Plugins and diagnostics use the deterministic ordering
provided by the existing plugin SDK.

## Compatibility and scope

The existing script remains unchanged:

```text
moughorai ask "request"
```

PR75 provides only plain text. JSON, JSONL, and SARIF output are PR76 work and
are not preimplemented here.
