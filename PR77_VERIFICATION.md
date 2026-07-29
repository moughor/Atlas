# PR77 Verification Instructions

From clean PR76 commit `d0567b1`:

```text
git apply --check PR77.patch
git apply PR77.patch
python -m pytest tests/test_pr76_cli_output_formats.py tests/test_pr77_finding_baselines.py -p no:cacheprovider --basetemp=.pytest_pr77_focused
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr77_full
```

Smoke test:

```text
atlas analyze . --write-baseline .atlas/findings.json
atlas check . --baseline .atlas/findings.json --format sarif
```

Expected focused total: **46 tests**.

Expected full-suite total: **3,032 tests**.

Recorded clean replay result: **3,032 passed in 5.07s**.
