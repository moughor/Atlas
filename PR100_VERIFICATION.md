# PR100 Verification

1. Check out PR99 commit `8df621c`.
2. Run `git apply --check PR100.patch`, apply it, and run `git diff --check`.
3. Build offline:

   ```text
   python -m pip wheel . --no-deps --no-build-isolation --no-cache-dir --wheel-dir .pr100_dist
   ```

4. Verify one `moughorai-2.0.0-*.whl`, both console scripts, and the stabilized
   runtime modules.
5. Run `python -m pytest -p no:cacheprovider
   --basetemp=.pytest_pr100_replay -q`.
6. Expect 3286 passing tests.
7. Verify `atlas --version` prints `Atlas 2.0.0` and SARIF reports tool version
   `2.0.0`.
