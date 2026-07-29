# PR97 Verification

1. Check out PR96 commit `331fe2c`.
2. Check and apply `PR97.patch`; run `git diff --check`.
3. Run `python -m pytest -p no:cacheprovider
   --basetemp=.pytest_pr97_replay -q`.
4. Expect 3259 passing tests.
5. Compare `atlas analyze <workspace> --workers 4` with the same command plus
   `--adaptive`; both reports must retain identical deterministic ordering.
