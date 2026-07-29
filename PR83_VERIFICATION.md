# PR83 Verification Instructions

From clean PR82 commit `ac581b1`:

```text
git apply --check PR83.patch
git apply PR83.patch
python -m pytest tests/test_pr65_language_server.py tests/test_pr81_workspace_lsp.py tests/test_pr82_incremental_editor_analysis.py tests/test_pr83_code_actions.py -p no:cacheprovider --basetemp=.pytest_pr83_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr83_full -q
```

Expected focused total: **61 tests**.

Expected full-suite total: **3,084 tests**.

Recorded clean replay result: **3,084 passed in 5.63s**.
