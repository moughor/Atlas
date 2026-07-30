# PR124 Test Report

- Baseline on `a75de96`: **3413 passed, 1 skipped** in 8.51s.
- Focused registry/context/Java/Python suite: **31 passed** in 0.77s.
- Full PR124 suite: **3422 passed, 1 skipped** in 10.09s.

Pytest emitted one cache-provider warning because the existing `.pytest_cache`
directory was not writable. Test execution completed normally.

The patch was applied to a detached clean checkout of `a75de96`; its full suite
completed with **3422 passed, 1 skipped** in 9.99s.
