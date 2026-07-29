# PR86 Verification Instructions

From clean PR85 commit `6753cfe`:

```text
git apply --check PR86.patch
git apply PR86.patch
python -m pytest tests/test_pr86_rule_authoring_api.py -p no:cacheprovider --basetemp=.pytest_pr86_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr86_full -q
```

Expected focused total: **14 tests**.

Expected full-suite total: **3,117 tests**.

Recorded clean replay result: **3,117 passed in 5.75s**.
