# PR118 — Git Context

`GitContextService` captures the current branch and HEAD, changed files, bounded
commit history, optional blame facts, pull-request metadata supplied by a host
integration, and ASS IDs for snapshot comparison. Output is deterministic JSON.

`atlas ai git-context ROOT` exposes local context without network access.
