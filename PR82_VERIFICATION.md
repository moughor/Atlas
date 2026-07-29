# PR82 Verification Instructions

From clean PR81 commit `a87b7e0`:

```text
git apply --check PR82.patch
git apply PR82.patch
python -m pytest tests/test_pr65_language_server.py tests/test_pr81_workspace_lsp.py tests/test_pr82_incremental_editor_analysis.py -p no:cacheprovider --basetemp=.pytest_pr82_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr82_full -q
```

Expected focused total: **51 tests**.

Expected full-suite total: **3,074 tests**.

Recorded clean replay result: **3,074 passed in 5.57s**.
