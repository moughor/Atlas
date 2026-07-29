# PR85 Test Report

Baseline: PR84 commit `13506ba`

Focused PR65 and PR81–PR85 LSP suite:

```text
python -m pytest tests/test_pr65_language_server.py tests/test_pr81_workspace_lsp.py tests/test_pr82_incremental_editor_analysis.py tests/test_pr83_code_actions.py tests/test_pr84_configuration_sync.py tests/test_pr85_progress_reporting.py -p no:cacheprovider --basetemp=.pytest_pr85_focused -q
```

Result: **80 passed in 0.28s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr85_full -q
```

Result: **3,103 passed in 4.31s**.

Clean replay:

```text
git apply --check PR85.patch
git apply PR85.patch
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr85_replay -q
```

Result: patch validation and application succeeded against `13506ba`;
**3,103 passed in 5.84s**.
