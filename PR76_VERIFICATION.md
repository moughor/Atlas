# PR76 Verification Instructions

From clean PR75 commit `236d2fd`:

```text
git apply --check PR76.patch
git apply PR76.patch
python -m pytest tests/test_pr75_unified_cli.py tests/test_pr76_cli_output_formats.py -p no:cacheprovider --basetemp=.pytest_pr76_focused
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr76_full
```

Manual smoke checks:

```text
atlas analyze . --format json
atlas analyze . --format jsonl
atlas check . --format sarif
```

Expected focused total: **50 tests**.

Expected full-suite total: **3,011 tests**.

Recorded clean replay on `236d2fd1396634570913e7ee5fd5f66d1bd0c06d`:
**3,011 passed in 5.87s**.
