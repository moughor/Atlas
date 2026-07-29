# PR84 Test Report

Baseline: PR83 commit `7659555`

Focused PR65 and PR81–PR84 LSP suite:

```text
python -m pytest tests/test_pr65_language_server.py tests/test_pr81_workspace_lsp.py tests/test_pr82_incremental_editor_analysis.py tests/test_pr83_code_actions.py tests/test_pr84_configuration_sync.py -p no:cacheprovider --basetemp=.pytest_pr84_focused_all -q
```

Result: **71 passed in 0.24s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr84_full -q
```

Result: **3,094 passed in 4.28s**.

Clean replay:

```text
git apply --check PR84.patch
git apply PR84.patch
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr84_replay -q
```

Result: patch validation and application succeeded against `7659555`;
**3,094 passed in 5.75s**.
