# PR87 Test Report

Baseline: PR86 commit `db0212c`

Focused PR86–PR87 rule SDK suite:

```text
python -m pytest tests/test_pr86_rule_authoring_api.py tests/test_pr87_rule_testing_framework.py -p no:cacheprovider --basetemp=.pytest_pr87_focused -q
```

Result: **29 passed in 0.07s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr87_full -q
```

Result: **3,132 passed in 4.37s**.

Clean replay:

```text
git apply --check PR87.patch
git apply PR87.patch
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr87_replay -q
```

Result: patch validation and application succeeded against `db0212c`;
**3,132 passed in 5.79s**.
