# PR76 Release Notes — CLI Output Formats

Baseline: PR75 commit `236d2fd`

PR76 adds deterministic text, JSON, JSONL, and SARIF 2.1.0 output to the unified
`atlas analyze` and `atlas check` commands. Plain text remains the default.

Structured output preserves project ordering, excludes timing-dependent data,
and keeps existing exit-code behavior. SARIF includes normalized findings,
locations, rule metadata, and analysis status.
