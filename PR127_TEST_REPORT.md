# PR127 Test Report

- Atlas 2.x roadmap baseline: **3429 passed, 1 skipped** in 8.71s.
- Clean JUnit runtime validation: **41 projects**, including root
  `junit-team`; `succeeded: yes`.
- Focused summary/inventory/dependency/context suite:
  **30 passed** in 0.71s.
- Full PR127 suite: **3434 passed, 1 skipped** in 8.74s.
- Clean patch replay on `ce36dbc`: **3434 passed, 1 skipped** in 10.40s.

Pytest emitted one cache-provider warning because the pre-existing
`.pytest_cache` directory was not writable. Test execution completed normally.
