# PR78 Verification Instructions

From clean PR77 commit `127a073`:

```text
git apply --check PR78.patch
git apply PR78.patch
python -m pytest tests/test_pr75_unified_cli.py tests/test_pr78_watch_mode.py -p no:cacheprovider --basetemp=.pytest_pr78_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr78_full -q
```

Manual smoke checks:

```text
atlas watch . --iterations 2 --interval 0
atlas watch . --continuous --workers 4
```

Expected focused total: **32 tests**.

Expected full-suite total: **3,039 tests**.

Recorded clean replay result: **3,039 passed in 5.96s**.
