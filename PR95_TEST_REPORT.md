# PR95 Test Report

Date: 2026-07-29

Focused command:

```text
python -m pytest tests/test_pr75_unified_cli.py tests/test_pr94_history_database.py tests/test_pr95_dashboard.py -p no:cacheprovider --basetemp=.pytest_pr95_focused -q
```

Result: **42 passed in 0.86s**.

Full command:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr95_full -q
```

Result: **3242 passed in 6.21s**.

Clean replay from PR94 commit `5cb183d` passed `git apply --check` and
`git diff --check`.

Result: **3242 passed in 7.71s**.
