# PR126 Verification

From a clean checkout of `a7475d1`:

```powershell
git apply --check PR126.patch
git apply PR126.patch
python -m pytest -q
```

Analyze fixtures containing all supported manifests and inspect
`.atlas/ass/latest.ass`. Confirm `semantic_context.dependencies` is sorted,
source-relative, deterministic, and survives a recovered workspace run.
