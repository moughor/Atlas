# PR123 Test Report

- Baseline on `a36a03f`: **3405 passed, 1 skipped** in 8.43s.
- Focused identity/index/workspace suite after the JUnit runtime corrections:
  **58 passed** in 0.47s.
- Full PR123 suite: **3413 passed, 1 skipped** in 8.80s.

Pytest also reported one cache-provider warning because the existing
`.pytest_cache` directory was not writable; this did not affect test execution.

The focused tests include JUnit-style independent projects containing the same
default-package type and the same fully qualified type, plus same-project
duplicate rejection with project and source-path diagnostics.

Runtime validation against the external JUnit checkout was executed with:

```powershell
python -m moughorai.atlas_cli analyze C:\Users\MoughorOC\Documents\AITest\JUnit\junit-team --no-recover --format json
```

All **40 projects succeeded**, including the independently scoped
`jupiter-tests` and `platform-tests` projects. The report returned
`"succeeded": true`.

The generated patch was applied to a detached clean checkout of `a36a03f`.
The replayed full suite completed with **3413 passed, 1 skipped** in 10.00s.
