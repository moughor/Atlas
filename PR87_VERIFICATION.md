# PR87 Verification Instructions

From clean PR86 commit `db0212c`:

```text
git apply --check PR87.patch
git apply PR87.patch
python -m pytest tests/test_pr86_rule_authoring_api.py tests/test_pr87_rule_testing_framework.py -p no:cacheprovider --basetemp=.pytest_pr87_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr87_full -q
```

Expected focused total: **29 tests**.

Expected full-suite total: **3,132 tests**.

Recorded clean replay result: **3,132 passed in 5.79s**.
