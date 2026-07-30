# PR122 Test Report

- Baseline on `2661b90`: **3400 passed, 1 skipped** in 10.08s.
- Focused Python/persistence/recovery tests: **64 passed** in 1.20s.
- CLI regression tests: **30 passed** in 0.84s.
- Final full suite: **3405 passed, 1 skipped** in 8.46s.
- Clean replay on baseline `2661b90`: **3405 passed, 1 skipped** in 11.86s.
- Atlas runtime validation: **10203 Python symbols**, **5171 types**, zero diagnostics.

The first full PR122 run exposed three duplicate-module regressions in
multi-project workspaces. They were corrected before the successful regression
and final full-suite runs above.
