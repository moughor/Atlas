# PR101 Verification

1. Check out PR100 commit `a072bf9`.
2. Check and apply `PR101.patch`, then run `git diff --check`.
3. Run:

   ```text
   python -m pytest -p no:cacheprovider --basetemp=.pytest_pr101_replay -q
   ```

4. Expect 3294 passing tests.
5. Run the 5,000-entry benchmark documented in
   `docs/PR101_SEMANTIC_TABLE_BUILDERS.md`.
6. Confirm built tables remain immutable and detached from later builder
   mutations.
