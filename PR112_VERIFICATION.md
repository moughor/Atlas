# PR112 Verification

1. Apply `PR112.patch` to PR111 commit `27ac4e1`.
2. Run `python -m pytest -q --basetemp=.pytest_pr112_verify`.
3. Confirm CLI help, ASS context output, missing-snapshot errors, future-engine
   boundaries, and the complete suite pass.
