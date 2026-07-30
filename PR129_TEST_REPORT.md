# PR129 Test Report

## Targeted validation

- Initial legacy PR27, PR125, and PR128 compatibility:
  **25 passed** in 0.52s.
- PR129 node/edge tests plus adjacent graph compatibility:
  **29 passed** in 0.55s.
- Snapshot/context consumer compatibility:
  **30 passed** in 0.79s.
- Final focused graph, snapshot, architecture, and pipeline set:
  **38 passed** in 0.77s.

Each run emitted one non-blocking `PytestCacheWarning` because the local
`.pytest_cache` path is not writable.

## Pre-review complete validation

**3447 passed, 1 skipped, 1 warning** in 10.24s.

The warning is the same non-blocking `PytestCacheWarning` caused by denied
write access to `.pytest_cache`; it did not affect test execution.

## Blocker-fix validation

- Relationship/build-system/dependency/round-trip focused suite:
  **37 passed** in 0.59s.
- Final graph/snapshot/architecture/pipeline focused suite:
  **54 passed** in 0.87s.
- Python and analyzer-registry compatibility:
  **14 passed** in 0.44s.
- Two earlier targeted commands referenced nonexistent persistence-test file
  names and therefore executed zero tests; they are not counted as results.
- Corrected complete validation:
  **3451 passed, 1 skipped, 1 warning** in 8.90s.
  The warning was the non-blocking `PytestCacheWarning` for denied write
  access to `.pytest_cache`.
- Corrected clean replay:
  patch applied to detached baseline `dfac541`; production/compatibility
  replay suite **68 passed** in 1.33s.

## JUnit snapshot size

Baseline `dfac541`, 41 successful projects:

- total snapshot: 13,682,363 bytes;
- semantic graph: 4,044,669 bytes;
- nodes: 13,200;
- edges: 11,649.

Corrected PR129, same workspace and configuration, 41 successful projects:

- total snapshot: 15,418,187 bytes (**+12.69%**);
- semantic graph: 4,929,300 bytes (**+21.87%**);
- nodes: 13,335 (**+1.02%**);
- edges: 14,105 (**+21.08%**).

Populated edge counts:

- `inheritance`: 379;
- `overrides`: 342;
- `depends_on`: 39;
- `ownership`: 1,696;
- `member_of`: 11,649.
