# PR94 Test Report

Date: 2026-07-29

## Focused suite

```text
python -m pytest tests/test_pr70_workspace_persistence.py tests/test_pr75_unified_cli.py tests/test_pr77_finding_baselines.py tests/test_pr92_git_diff_analysis.py tests/test_pr94_history_database.py -p no:cacheprovider --basetemp=.pytest_pr94_focused -q
```

Result: **101 passed in 2.72s**.

## Full suite

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr94_full -q
```

Result: **3236 passed in 6.13s**.

## Clean replay

The candidate patch was applied to a detached checkout of PR93 commit
`13eb2b1`. `git apply --check` and `git diff --check` succeeded.

Result: **3236 passed in 7.54s**.
