# PR95 Verification

1. Check out PR94 commit `5cb183d`.
2. Check and apply `PR95.patch`; run `git diff --check`.
3. Run `python -m pytest -p no:cacheprovider
   --basetemp=.pytest_pr95_replay -q`.
4. Expect 3242 passing tests.
5. Run `atlas dashboard <workspace>` and open
   `<workspace>/.atlas/dashboard.html`.
6. Verify the document contains no remote script, stylesheet, or font
   dependencies.
