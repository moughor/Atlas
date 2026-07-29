# PR76 — CLI Output Formats

PR76 adds `--format` to `atlas analyze` and `atlas check`:

```text
atlas analyze . --format text
atlas analyze . --format json
atlas analyze . --format jsonl
atlas check . --format sarif
```

## Text

`text` is the default and preserves PR75 output exactly.

## JSON

JSON contains the request, deterministic analysis order, success state, and
ordered project runs. Timing fields are intentionally omitted so identical
analysis results serialize identically.

## JSONL

JSONL emits one compact record per project in analysis order, followed by a
summary record. Each line is independently valid JSON.

## SARIF

SARIF output conforms to version 2.1.0. Analyzer results may expose a `findings`
array. Supported finding keys include:

- `rule_id` or `ruleId`
- `message` or `description`
- `level` or `severity`
- `path` or `file`
- `line`, `column`, `end_line`, and `end_column`

Results and rule descriptors are sorted deterministically. Severity values are
normalized to SARIF `error`, `warning`, `note`, or `none`.

The formatter uses only the Python standard library and does not change existing
workspace or analyzer public APIs.
