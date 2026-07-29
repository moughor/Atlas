# PR102 Verification

1. Check out PR101 commit `fc46e30`.
2. Check and apply `PR102.patch`; run `git diff --check`.
3. Run `python -m pytest -p no:cacheprovider
   --basetemp=.pytest_pr102_replay -q`.
4. Expect 3301 passing tests.
5. Run `tests/test_pr102_global_symbol_concurrency.py` repeatedly to exercise
   writer contention, duplicate races, concurrent reads, and source removal.
6. Confirm `GlobalSymbolDatabase.validate()` reports no index inconsistency.
