# PR128 Test Report

- Targeted architecture/Java-graph/summary/context suite:
  **24 passed** in 0.72s.
- Complete validation: **3439 passed, 1 skipped** in 8.88s.
- Clean patch replay on `47a3657`: patch applied and targeted suite completed
  with **24 passed** in 0.91s.

The targeted run emitted one cache-provider warning because the pre-existing
`.pytest_cache` directory was not writable. Test execution completed normally.
