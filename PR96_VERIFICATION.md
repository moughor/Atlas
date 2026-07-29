# PR96 Verification

1. Check out PR95 commit `92a0534`.
2. Check and apply `PR96.patch`; run `git diff --check`.
3. Run `python -m pytest -p no:cacheprovider
   --basetemp=.pytest_pr96_replay -q`.
4. Expect 3250 passing tests.
5. Run `atlas profile <workspace> --workers 2` and verify JSON metrics include
   `workspace` and one `project:<name>` entry per executed project.
