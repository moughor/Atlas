# PR124 Verification

From a clean checkout of `a75de96`:

```powershell
git apply --check PR124.patch
git apply PR124.patch
python -m pytest -q
```

Verify that `AnalyzerRegistry().registrations()` contains Java and Python,
custom analyzers receive only their declared extensions, conflicting
registrations fail deterministically, and `SemanticProjectAnalyzer` remains
callable through its existing constructor.
