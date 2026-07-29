# PR82 Incremental Editor Analysis

`IncrementalWorkspaceLanguageServer` applies LSP `contentChanges` in their
declared order. Each change may replace the full document or a validated range.
Document versions must increase monotonically.

An incremental analyzer receives:

```text
(current_document, project, resolved_configuration, change_set)
```

`DocumentChangeSet` contains the previous and current documents plus normalized
`TextChange` values. Findings returned by the callback are converted and sorted
by the existing diagnostic publisher. If no incremental callback is provided,
the PR81 full workspace analyzer runs against the updated document.

Positions currently use Python Unicode code-point offsets, matching the
existing Atlas LSP model.
