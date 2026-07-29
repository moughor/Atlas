# PR121 Test Report

Runtime:
`C:\Users\MoughorOC\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`

## Successful executions

- Baseline: **3393 passed, 1 skipped** in 8.59s.
- Focused CLI and AI context tests: **31 passed** in 0.86s.
- PR70/PR74/history/pipeline integration: **93 passed** in 1.79s.
- Full PR121 suite: **3397 passed, 1 skipped** in 8.43s.
- Clean replay on baseline `6deea92`: **3397 passed, 1 skipped** in 11.84s.

Pytest emitted a non-failing cache warning because `.pytest_cache` was not
writable. Every successful run used an explicit writable `--basetemp`.

## Non-test command errors

- The first baseline command did not run because `python` was absent from PATH;
  it was immediately rerun with the bundled runtime.
- One integration selection named nonexistent historical test files and
  collected zero tests; the correct PR70, PR74, and PR94 filenames were then
  used for the successful 93-test run above.
- Two intermediate focused runs exposed JSON persistence/history integration
  failures. Those defects were fixed before the successful focused,
  integration, and full-suite executions listed above.
