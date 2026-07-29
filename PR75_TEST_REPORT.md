# PR75 Test Report

Baseline: PR74 commit `86aa386`

Executed focused tests:

```text
python -m pytest tests/test_pr75_unified_cli.py -p no:cacheprovider --basetemp=.pytest_pr75_focused -q
```

Result: **25 passed in 0.32s**.

Executed full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr75_full -q
```

Result: **2,986 passed in 3.64s**.

Clean replay:

- Baseline: `86aa3863d64b6b5ab06d29b9f5d9bae713660301`
- `git apply --check PR75.patch`: passed
- Replayed full suite: **2,986 passed in 4.91s**
