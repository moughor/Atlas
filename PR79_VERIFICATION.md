# PR79 Verification Instructions

From clean PR78 commit `2be45e9`:

```text
git apply --check PR79.patch
git apply PR79.patch
python -m pytest tests/test_pr75_unified_cli.py tests/test_pr77_finding_baselines.py tests/test_pr79_quality_gates.py -p no:cacheprovider --basetemp=.pytest_pr79_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr79_full -q
```

Smoke checks:

```text
atlas check . --fail-on high --finding-exit-code 7
atlas check . --max-findings 0 --analysis-exit-code 9
```

Expected focused total: **55 tests**.

Expected full-suite total: **3,048 tests**.

Recorded clean replay result: **3,048 passed in 6.08s**.
