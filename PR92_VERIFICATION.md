# PR92 Verification Instructions

From clean PR91 commit `b180b25`:

```text
git apply --check PR92.patch
git apply PR92.patch
python -m pytest tests/test_pr75_unified_cli.py tests/test_pr77_finding_baselines.py tests/test_pr92_git_diff_analysis.py -p no:cacheprovider --basetemp=.pytest_pr92_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr92_full -q
```

Expected focused total: **59 tests**.

Expected full-suite total: **3,210 tests**.

Recorded clean replay result: **3,210 passed in 6.79s**.
