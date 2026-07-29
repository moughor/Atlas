# PR98 Test Report

Date: 2026-07-29

The first focused run executed 75 tests: **74 passed, 1 failed** because the
test expected a different assignment order than PR58's deterministic leasing
cycle. The expectation was corrected; implementation was unchanged.

Final focused result: **75 passed in 0.54s**.

```text
python -m pytest tests/test_pr58_distributed_coordinator.py tests/test_pr73_concurrent_workspace_execution.py tests/test_pr97_adaptive_scheduler.py tests/test_pr98_distributed_workers.py -p no:cacheprovider --basetemp=.pytest_pr98_focused_pass -q
```

Full result: **3266 passed in 6.44s**.

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr98_full -q
```

Clean replay from PR97 commit `6fd406f` passed `git apply --check` and
`git diff --check`.

Result: **3266 passed in 7.82s**.
