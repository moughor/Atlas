# PR80 Test Report

Baseline: PR79 commit `5593d55`

Wheel build:

```text
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist
```

Result: `moughorai-1.0.0-py3-none-any.whl`, 423,043 bytes,
SHA-256 `a07a2cf5ec813859043aea12ffb5be64447ab40e1b229e3a7e5991676d89304a`.

External wheel import verified version `1.0.0` and entry point
`moughorai.atlas_cli:main`.

Focused packaging and unified-CLI suite:

```text
python -m pytest tests/test_pr75_unified_cli.py tests/test_pr80_packaging.py -p no:cacheprovider --basetemp=.pytest_pr80_focused -q
```

Result: **30 passed in 0.39s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr80_full -q
```

Result: **3,053 passed in 4.70s**.

The first clean wheel rebuild attempt was denied access to pip's user cache.
It was rerun with `--no-cache-dir`; the patch remained applied in the same
clean worktree.

Clean replay:

```text
git apply --check PR80.patch
git apply PR80.patch
python -m pip wheel . --no-deps --no-build-isolation --no-cache-dir --wheel-dir dist
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr80_replay -q
```

Result: patch application and wheel build succeeded against `5593d55`;
**3,053 passed in 6.10s**.
