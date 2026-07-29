# PR94 Release Notes

PR94 adds a versioned SQLite historical database at
`.atlas/history.sqlite3`. Atlas records filtered `analyze` and `check` reports
transactionally and exposes deterministic list, lookup, pagination, and
retention APIs.

The new `atlas history` command lists recent runs without changing existing
report formats or exit-code behavior.
