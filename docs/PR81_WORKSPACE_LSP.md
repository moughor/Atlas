# PR81 Workspace LSP

`WorkspaceLanguageServer` extends the PR65 protocol server with Atlas workspace
awareness:

```python
server = WorkspaceLanguageServer(root, analyzer)
```

The analyzer receives `(document, project, resolved_configuration)`. File URIs
are mapped to the most-specific configured project, including nested projects.
Documents outside the workspace publish an empty diagnostic set.

Initialization advertises inter-file and workspace diagnostics plus
workspace-folder notifications. `workspace/diagnostic` returns full reports
for open documents in stable URI order. Workspace folder additions and
removals are normalized, deduplicated, and sorted.

This PR intentionally performs full document analysis. Incremental editor
analysis belongs to PR82.
