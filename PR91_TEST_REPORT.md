# PR91 Test Report

Baseline: PR90 commit `16c37c2`

Focused PR76 and PR91 SARIF suite:

```text
python -m pytest tests/test_pr76_cli_output_formats.py tests/test_pr91_sarif.py -p no:cacheprovider --basetemp=.pytest_pr91_focused -q
```

Result: **39 passed in 0.29s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr91_full -q
```

Result: **3,197 passed in 4.14s**.

Clean replay:

```text
git apply --check PR91.patch
git apply PR91.patch
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr91_replay -q
```

Result: patch validation and application succeeded against `16c37c2`;
**3,197 passed in 6.54s**.
