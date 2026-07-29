# PR77 Test Report

Baseline: PR76 commit `d0567b1`

Focused PR76–PR77 suite:

```text
python -m pytest tests/test_pr76_cli_output_formats.py tests/test_pr77_finding_baselines.py -p no:cacheprovider --basetemp=.pytest_pr77_focused -q
```

Result: **46 passed in 0.32s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr77_full -q
```

Result: **3,032 passed in 4.27s**.

Clean replay:

```text
git apply --check PR77.patch
git apply PR77.patch
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr77_replay -q
```

Result: patch validation and application succeeded against `d0567b1`;
**3,032 passed in 5.07s**.
