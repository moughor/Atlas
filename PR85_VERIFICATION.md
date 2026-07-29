# PR85 Verification Instructions

From clean PR84 commit `13506ba`:

```text
git apply --check PR85.patch
git apply PR85.patch
python -m pytest tests/test_pr65_language_server.py tests/test_pr81_workspace_lsp.py tests/test_pr82_incremental_editor_analysis.py tests/test_pr83_code_actions.py tests/test_pr84_configuration_sync.py tests/test_pr85_progress_reporting.py -p no:cacheprovider --basetemp=.pytest_pr85_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr85_full -q
```

Expected focused total: **80 tests**.

Expected full-suite total: **3,103 tests**.

Recorded clean replay result: **3,103 passed in 5.84s**.
