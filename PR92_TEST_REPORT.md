# PR92 Test Report

Baseline: PR91 commit `b180b25`

Three focused development runs each reported **58 passed, 1 failed** while the
non-repository fixture was corrected for nested Git discovery and exact stderr
matching. The complete focused CLI, baseline, and Git-diff suite was then
rerun:

```text
python -m pytest tests/test_pr75_unified_cli.py tests/test_pr77_finding_baselines.py tests/test_pr92_git_diff_analysis.py -p no:cacheprovider --basetemp=.pytest_pr92_focused_pass -q
```

Result: **59 passed in 1.75s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr92_full -q
```

Result: **3,210 passed in 5.88s**.

Clean replay:

```text
git apply --check PR92.patch
git apply PR92.patch
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr92_replay -q
```

Result: patch validation and application succeeded against `b180b25`;
**3,210 passed in 6.79s**.
