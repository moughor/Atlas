# PR80 Atlas 1.0 Packaging

Atlas 1.0 is distributed as the `moughorai` Python package and requires Python
3.12 or newer. The canonical runtime version is exposed as
`moughorai.__version__` and by `atlas --version`.

Build a wheel without resolving runtime dependencies:

```text
python -m pip wheel . --no-deps --no-build-isolation --no-cache-dir --wheel-dir dist
```

The wheel contains all `moughorai` packages and registers:

```text
atlas = moughorai.atlas_cli:main
moughorai = moughorai.cli:main
```

Release verification must inspect or import from the wheel outside the source
tree so local modules cannot hide packaging omissions.
