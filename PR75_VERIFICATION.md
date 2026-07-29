# PR75 Verification Instructions

Apply `PR75.patch` to a clean checkout of PR74 commit `86aa386`:

```text
git apply --check PR75.patch
git apply PR75.patch
python -m pytest tests/test_pr75_unified_cli.py -p no:cacheprovider --basetemp=.pytest_pr75_focused
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr75_full
```

Verify the command surface:

```text
atlas --help
atlas analyze --help
atlas check --help
atlas watch --help
atlas config --help
atlas plugins --help
```

Expected focused total: **25 tests**.

Expected full-suite total: **2,986 tests**.

Recorded clean replay on `86aa3863d64b6b5ab06d29b9f5d9bae713660301`:
**2,986 passed in 4.91s**.
