# PR91 Verification Instructions

From clean PR90 commit `16c37c2`:

```text
git apply --check PR91.patch
git apply PR91.patch
python -m pytest tests/test_pr76_cli_output_formats.py tests/test_pr91_sarif.py -p no:cacheprovider --basetemp=.pytest_pr91_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr91_full -q
```

Expected focused total: **39 tests**.

Expected full-suite total: **3,197 tests**.

Recorded clean replay result: **3,197 passed in 6.54s**.
