# PR93 Test Report

Date: 2026-07-29

## Focused suite

Command:

```text
python -m pytest tests/test_pr75_unified_cli.py tests/test_pr79_quality_gates.py tests/test_pr91_sarif.py tests/test_pr93_ci_templates.py -p no:cacheprovider --basetemp=.pytest_pr93_focused -q
```

Result: **63 passed in 0.56s**.

## Full suite

Command:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr93_full -q
```

Result: **3225 passed in 6.04s**.

## Clean replay

The candidate patch was applied to a detached checkout of PR92 commit
`d4865c1`. `git apply --check` and `git diff --check` succeeded, followed by:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr93_replay -q
```

Result: **3225 passed in 6.87s**.
