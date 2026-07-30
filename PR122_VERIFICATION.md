# PR122 Verification

From a clean checkout of `2661b90`:

```powershell
git apply --check PR122.patch
git apply PR122.patch
python -m pytest -q
atlas analyze . --no-recover
atlas ai context .
```

Verify that the snapshot contains Python package, type, method, and field
symbols, plus deterministic type entries for annotated declarations.
