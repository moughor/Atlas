# PR125 Verification

From a clean checkout of `f64c150`:

```powershell
git apply --check PR125.patch
git apply PR125.patch
python -m pytest -q
```

Analyze a project containing `.java`, `.py`, and `.ts` files. Confirm
`.atlas/ass/latest.ass` contains `semantic_context.semantic_graph`, all three
languages, stable project-scoped IDs, and deterministic ownership/import edges.
