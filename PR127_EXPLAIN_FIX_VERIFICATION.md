# PR127 Explain Integration Fix — Verification

From a clean checkout of `7004478`:

```powershell
git apply --check PR127_EXPLAIN_FIX.patch
git apply PR127_EXPLAIN_FIX.patch
python -m pytest -q tests/test_pr114_explain_engine.py `
  tests/test_pr109_prompt_builder.py `
  tests/test_pr127_repository_summary.py `
  tests/test_pr128_architecture_detection.py
```

Run `atlas ai explain` against a snapshot containing `repository_summary`.
Confirm the `atlas-repository-explanation-v1` template is selected for the
default workspace subject and that the prompt contains summary/architecture
metadata but no detailed `symbols` collection or raw source.
