# PR94 Verification

1. Check out PR93 commit `13eb2b1`.
2. Run `git apply --check PR94.patch`, apply the patch, and run
   `git diff --check`.
3. Run:

   ```text
   python -m pytest -p no:cacheprovider --basetemp=.pytest_pr94_replay -q
   ```

4. Expect 3236 passing tests.
5. Run `atlas analyze <workspace> --no-recover`, then `atlas history
   <workspace>`, and verify that one successful run is listed.
