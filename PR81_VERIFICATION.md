# PR81 Verification Instructions

From clean PR80 commit `491c400`:

```text
git apply --check PR81.patch
git apply PR81.patch
python -m pytest tests/test_pr65_language_server.py tests/test_pr81_workspace_lsp.py -p no:cacheprovider --basetemp=.pytest_pr81_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr81_full -q
```

Expected focused total: **40 tests**.

Expected full-suite total: **3,063 tests**.

Recorded clean replay result: **3,063 passed in 5.73s**.
