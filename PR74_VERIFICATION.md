# PR74 Verification Instructions

## Apply to PR73

Start from commit `750bf22e7c916101002f852a530120682e259141` with a
clean worktree:

```text
git checkout 750bf22e7c916101002f852a530120682e259141
git apply --check PR74.patch
git apply PR74.patch
```

`PR74.patch` contains the implementation, public exports, event kinds,
documentation, release notes, verification instructions, and focused tests.

## Install and test

Use Python 3.12 or newer:

```text
python -m pip install -e ".[dev]"
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr74_verify
```

Expected collection after applying PR74: **2,961 tests**.

## Focused behavior

```text
python -m pytest tests/test_pr74_workspace_recovery.py -p no:cacheprovider --basetemp=.pytest_pr74_focused
```

Expected focused collection: **19 tests**. These cover interruption, journal
durability, all four project states, unfinished-only resume, invalidation,
persistence, configuration, events, concurrent execution, serialization, and
backward-compatible disabled behavior.

## Artifact integrity

After extracting `PR74_Delivery.zip`, compare the included `PR74.patch` to the
repository copy and inspect archive contents:

```text
git apply --check PR74.patch
```

The candidate patch was replayed in a detached clean worktree at
`750bf22e7c916101002f852a530120682e259141`. The full replayed suite actually
executed and passed: **2,961 tests in 4.83s**. After recording the result, the
final patch was regenerated and passed a second `git apply --check` against a
fresh detached PR73 worktree.
