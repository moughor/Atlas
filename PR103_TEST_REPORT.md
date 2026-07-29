# PR103 Test Report

Date: 2026-07-29

Baseline PR102 (`10679f2`): **3301 passed in 6.69s**.

Focused logging/integration matrix:

```text
python -m pytest tests/test_pr59_plugin_sdk.py tests/test_pr72_workspace_event_bus.py tests/test_pr73_concurrent_workspace_execution.py tests/test_pr74_workspace_recovery.py tests/test_pr75_unified_cli.py tests/test_pr103_structured_logging.py -p no:cacheprovider --basetemp=.pytest_pr103_focused -q
```

Result: **142 passed in 1.42s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr103_full -q
```

Result: **3310 passed in 7.94s**.

Clean replay from PR102 commit `10679f2` passed `git apply --check` and
`git diff --check`.

Result: **3310 passed in 8.37s**.
