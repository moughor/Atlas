# PR94 — Historical Database

Atlas records completed `analyze` and `check` reports in
`.atlas/history.sqlite3`. The versioned SQLite schema stores each run and its
ordered per-project results in one transaction. Baseline and Git-diff filters
are applied before recording, so stored findings match CLI output.

List recent runs with:

```text
atlas history .
atlas history . --limit 5
```

The Python API supports `record`, `list`, `get`, and `prune`. Queries are
ordered deterministically by descending run identifier. Missing databases
produce an empty history without creating a file.
