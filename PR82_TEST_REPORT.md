# PR82 Test Report

Baseline: PR81 commit `a87b7e0`

Focused PR65, PR81, and PR82 LSP suite:

```text
python -m pytest tests/test_pr65_language_server.py tests/test_pr81_workspace_lsp.py tests/test_pr82_incremental_editor_analysis.py -p no:cacheprovider --basetemp=.pytest_pr82_focused -q
```

Result: **51 passed in 0.17s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr82_full -q
```

Result: **3,074 passed in 4.24s**.

Clean replay:

```text
git apply --check PR82.patch
git apply PR82.patch
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr82_replay -q
```

Result: patch validation and application succeeded against `a87b7e0`;
**3,074 passed in 5.57s**.
