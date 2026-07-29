# PR86 Test Report

Baseline: PR85 commit `6753cfe`

Focused rule-authoring SDK suite:

```text
python -m pytest tests/test_pr86_rule_authoring_api.py -p no:cacheprovider --basetemp=.pytest_pr86_focused -q
```

Result: **14 passed in 0.05s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr86_full -q
```

Result: **3,117 passed in 4.25s**.

Clean replay:

```text
git apply --check PR86.patch
git apply PR86.patch
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr86_replay -q
```

Result: patch validation and application succeeded against `6753cfe`;
**3,117 passed in 5.75s**.
