# PR89 Verification Instructions

From clean PR88 commit `e33a08e`:

```text
git apply --check PR89.patch
git apply PR89.patch
python -m pytest tests/test_pr86_rule_authoring_api.py tests/test_pr87_rule_testing_framework.py tests/test_pr88_rule_metadata.py tests/test_pr89_auto_fix_framework.py -p no:cacheprovider --basetemp=.pytest_pr89_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr89_full -q
```

Expected focused total: **60 tests**.

Expected full-suite total: **3,163 tests**.

Recorded clean replay result: **3,163 passed in 6.67s**.
