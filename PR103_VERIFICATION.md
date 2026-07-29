# PR103 Verification

1. Check out PR102 commit `10679f2`.
2. Check and apply `PR103.patch`; run `git diff --check`.
3. Run `python -m pytest -p no:cacheprovider
   --basetemp=.pytest_pr103_replay -q`.
4. Expect 3310 passing tests.
5. Run an analysis with JSON logging and a fixed correlation ID.
6. Verify lifecycle records share that ID and sensitive test fields are
   rendered as `[REDACTED]`.
7. Run without logging options and confirm stderr remains empty.
