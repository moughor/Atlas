# PR110 Test Report

## Focused integration suite

`15 passed in 0.26s`

## Full suite

`3351 passed, 1 skipped in 8.55s`

Both runs also reported one non-test pytest cache permission warning. HTTP
tests used `httpx.MockTransport` and did not require network access.

## Clean replay

`PR110.patch` applied to commit `c19e9ef` and the clean worktree suite
completed with `3351 passed, 1 skipped in 9.08s`.
