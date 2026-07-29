# PR80 Verification Instructions

From clean PR79 commit `5593d55`:

```text
git apply --check PR80.patch
git apply PR80.patch
python -m pip wheel . --no-deps --no-build-isolation --no-cache-dir --wheel-dir dist
python -m pytest tests/test_pr75_unified_cli.py tests/test_pr80_packaging.py -p no:cacheprovider --basetemp=.pytest_pr80_focused -q
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr80_full -q
```

Verify that the wheel contains `moughorai/atlas_cli.py` and
`moughorai/version.py`, its metadata version is `1.0.0`, and its `atlas`
console script targets `moughorai.atlas_cli:main`.

Expected focused total: **30 tests**.

Expected full-suite total: **3,053 tests**.

Recorded clean replay result: **3,053 passed in 6.10s**.
