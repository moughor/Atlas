# PR128 Confidence Fix — Verification

From a clean checkout of `07e88e7`:

```powershell
git apply --check PR128_CONFIDENCE_FIX.patch
git apply PR128_CONFIDENCE_FIX.patch
python -m pytest -q tests/test_pr114_explain_engine.py `
  tests/test_pr127_repository_summary.py `
  tests/test_pr128_architecture_detection.py
```

Regenerate a semantic snapshot and verify that architecture findings include
confidence/evidence, dependency analysis includes execution state, repository
dependency totals use declared-record and manifest labels, and framework
evidence includes project and scope.
