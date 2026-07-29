# PR105 Test Report

Date: 2026-07-29

Baseline PR104 (`ab0929a`): **3316 passed in 7.02s**.

The first focused run exposed an incorrect expected issue order in the new
test: **84 passed, 1 failed in 0.27s**. The assertion was corrected to match
the documented deterministic name ordering.

Focused API and SDK matrix after correction:

```text
python -m pytest tests/test_pr59_plugin_sdk.py
tests/test_pr66_analysis_api.py tests/test_pr86_rule_authoring_api.py
tests/test_pr105_public_api.py -p no:cacheprovider
--basetemp=.pytest_pr105_focused_pass -q
```

Result: **85 passed in 0.24s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr105_full -q
```

Result: **3320 passed in 6.94s**.

Clean replay from PR104 commit `ab0929a` passed `git apply --check` and
`git diff --check`.

Result: **3320 passed in 8.24s**.
