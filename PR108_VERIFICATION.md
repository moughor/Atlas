# PR108 Verification

1. Apply `PR108.patch` to the PR107 commit.
2. Run `python -m pytest -q --basetemp=.pytest_pr108_verify`.
3. Confirm deterministic ordering tests and the complete suite pass.
