# PR83 Test Report

Baseline: PR82 commit `ac581b1`

Focused PR65 and PR81–PR83 LSP suite:

```text
python -m pytest tests/test_pr65_language_server.py tests/test_pr81_workspace_lsp.py tests/test_pr82_incremental_editor_analysis.py tests/test_pr83_code_actions.py -p no:cacheprovider --basetemp=.pytest_pr83_focused -q
```

Result: **61 passed in 0.20s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr83_full -q
```

Result: **3,084 passed in 4.18s**.

Clean replay:

```text
git apply --check PR83.patch
git apply PR83.patch
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr83_replay -q
```

Result: patch validation and application succeeded against `ac581b1`;
**3,084 passed in 5.63s**.
