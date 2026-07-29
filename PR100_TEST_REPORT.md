# PR100 Test Report

Date: 2026-07-29

## Focused release matrix

The first focused run executed 120 tests: **119 passed, 1 failed** because the
README split the literal release name across a line break. The README was made
explicit; implementation behavior was unchanged.

Final result: **120 passed in 1.44s**.

## Wheel

The first isolated build failed before building because the sandbox could not
download `setuptools>=69` (`WinError 10013`). The offline build used the
installed backend:

```text
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir .pr100_dist
```

Result: `moughorai-2.0.0-py3-none-any.whl` built successfully. Inspection
confirmed runtime modules and both `atlas` and `moughorai` console scripts.

## Full suite

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr100_full -q
```

Result: **3286 passed in 6.63s**.

## Clean replay

`git apply --check` and `git diff --check` succeeded from PR99 commit
`8df621c`. The first replay wheel command failed because pip attempted to write
its global wheel cache and received `WinError 5`. Repeating with
`--no-cache-dir` built and inspected the Atlas 2.0 wheel successfully.

Full replay result: **3286 passed in 8.02s**.
