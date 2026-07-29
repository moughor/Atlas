# PR90 Verification Instructions

From clean PR89 commit `960343d`:

```text
git apply --check PR90.patch
git apply PR90.patch
python -m pytest tests/test_pr86_rule_authoring_api.py tests/test_pr87_rule_testing_framework.py tests/test_pr88_rule_metadata.py tests/test_pr89_auto_fix_framework.py tests/test_pr90_rule_pack_builder.py -p no:cacheprovider --basetemp=.pytest_pr90_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr90_full -q
```

Expected focused total: **80 tests**.

Expected full-suite total: **3,183 tests**.

Recorded clean replay result: **3,183 passed in 6.64s**.
