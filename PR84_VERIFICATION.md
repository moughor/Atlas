# PR84 Verification Instructions

From clean PR83 commit `7659555`:

```text
git apply --check PR84.patch
git apply PR84.patch
python -m pytest tests/test_pr65_language_server.py tests/test_pr81_workspace_lsp.py tests/test_pr82_incremental_editor_analysis.py tests/test_pr83_code_actions.py tests/test_pr84_configuration_sync.py -p no:cacheprovider --basetemp=.pytest_pr84_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr84_full -q
```

Expected focused total: **71 tests**.

Expected full-suite total: **3,094 tests**.

Recorded clean replay result: **3,094 passed in 5.75s**.
