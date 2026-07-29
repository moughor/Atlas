# PR74 Test Report

Environment:

- Windows
- Python 3.12.13
- pytest 9.1.1
- Baseline commit: `750bf22e7c916101002f852a530120682e259141`

## Executed results

1. Unmodified PR73 baseline:
   `python -m pytest -p no:cacheprovider --basetemp=.pytest_pr73_baseline`
   — **2,942 passed in 3.04s**.
2. Focused PR74 recovery tests:
   `python -m pytest tests/test_pr74_workspace_recovery.py -p no:cacheprovider --basetemp=.pytest_pr74_focused -q`
   — **19 passed in 0.49s**.
3. PR70–PR74 integration tests:
   `python -m pytest tests/test_pr70_workspace_persistence.py tests/test_pr71_workspace_configuration.py tests/test_pr72_workspace_event_bus.py tests/test_pr73_concurrent_workspace_execution.py tests/test_pr74_workspace_recovery.py -p no:cacheprovider --basetemp=.pytest_pr70_pr74 -q`
   — **133 passed in 0.97s**.
4. Full suite with PR74:
   `python -m pytest -p no:cacheprovider --basetemp=.pytest_pr74_full -q`
   — **2,961 passed in 3.73s**.
5. Candidate patch replayed on a detached clean checkout of PR73:
   `python -m pytest -p no:cacheprovider --basetemp=.pytest_pr74_replay -q`
   — **2,961 passed in 4.83s**.

The initial attempts using an unavailable `python` command, a runtime without
dependencies, and a non-writable system pytest temp root were environment setup
failures and were not counted as passing test executions.

The final patch was regenerated after recording this result and subjected to a
second clean apply check.
