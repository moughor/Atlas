# PR93 Verification

1. Check out PR92 commit `d4865c1`.
2. Apply `PR93.patch` with `git apply --check PR93.patch` and
   `git apply PR93.patch`.
3. Run `git diff --check`.
4. Run:

   ```text
   python -m pytest -p no:cacheprovider --basetemp=.pytest_pr93_replay -q
   ```

5. Expect 3225 passing tests.
6. Run `atlas ci github --root <temporary-repository>` and verify that
   `.github/workflows/atlas.yml` is created.
7. Run the command again without `--force` and verify exit code 2.
