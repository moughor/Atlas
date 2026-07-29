# PR111 — Atlas Semantic Snapshot (ASS)

Atlas Semantic Snapshot persists verified semantic knowledge independently of
any LLM provider. A snapshot contains the deterministic PR108 context,
workspace fingerprint, analyzer version, optional history reference, schema
version, and a content-derived identifier.

`SemanticSnapshotStore` writes immutable timestamped artifacts under
`.atlas/ass/` and atomically replaces `latest.ass` only after the historical
snapshot is durable. Checksums and content identifiers detect corruption or
tampering. Identical semantic inputs produce identical snapshot bytes; creation
time affects only the historical filename.

```python
context = WorkspaceContextBuilder().build(workspace, diagnostics=diagnostics)
store = SemanticSnapshotStore(workspace)
path = store.save(store.capture(context, history_reference=run_id))

loaded = store.load()
context = WorkspaceContextBuilder.from_snapshot(loaded)
```

The format contains no provider configuration or source text added by the
snapshot layer. Existing history, workspace-state, and recovery files remain
unchanged.
