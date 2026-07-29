# PR109 Verification

1. Apply `PR109.patch` to the PR108 commit.
2. Run `python -m pytest -q --basetemp=.pytest_pr109_verify`.
3. Confirm template, token-budget, compatibility, and full-suite tests pass.
