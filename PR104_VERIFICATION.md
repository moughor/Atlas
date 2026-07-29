# PR104 Verification

1. Check out PR103 commit `b409037`.
2. Check and apply `PR104.patch`; run `git diff --check`.
3. Run `python -m pytest -p no:cacheprovider
   --basetemp=.pytest_pr104_replay -q`.
4. Run `python -m benchmarks.benchmark_large_workspace`.
5. Confirm 23,000 files are indexed and the command emits one JSON report.
6. Re-run the benchmark and confirm `content_checksum` is unchanged.
