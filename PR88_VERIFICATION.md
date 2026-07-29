# PR88 Verification Instructions

From clean PR87 commit `0132ccb`:

```text
git apply --check PR88.patch
git apply PR88.patch
python -m pytest tests/test_pr86_rule_authoring_api.py tests/test_pr87_rule_testing_framework.py tests/test_pr88_rule_metadata.py -p no:cacheprovider --basetemp=.pytest_pr88_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr88_full -q
```

Expected focused total: **45 tests**.

Expected full-suite total: **3,148 tests**.

Recorded clean replay result: **3,148 passed in 5.80s**.
