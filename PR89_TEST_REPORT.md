# PR89 Test Report

Baseline: PR88 commit `e33a08e`

Focused PR86–PR89 rule SDK suite:

```text
python -m pytest tests/test_pr86_rule_authoring_api.py tests/test_pr87_rule_testing_framework.py tests/test_pr88_rule_metadata.py tests/test_pr89_auto_fix_framework.py -p no:cacheprovider --basetemp=.pytest_pr89_focused -q
```

Result: **60 passed in 0.15s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr89_full -q
```

Result: **3,163 passed in 4.21s**.

Clean replay:

```text
git apply --check PR89.patch
git apply PR89.patch
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr89_replay -q
```

Result: patch validation and application succeeded against `e33a08e`;
**3,163 passed in 6.67s**.
