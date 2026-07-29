# PR96 Test Report

Date: 2026-07-29

Focused suite:

```text
python -m pytest tests/test_pr73_concurrent_workspace_execution.py tests/test_pr75_unified_cli.py tests/test_pr96_performance_profiler.py -p no:cacheprovider --basetemp=.pytest_pr96_focused -q
```

Result: **55 passed in 0.76s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr96_full -q
```

Result: **3250 passed in 7.04s**.

Clean replay from PR95 commit `92a0534` passed `git apply --check` and
`git diff --check`.

Result: **3250 passed in 8.75s**.
