# PR128 Confidence Fix — Test Report

- Targeted explain/summary/architecture suite:
  **17 passed** in 0.55s.
- JUnit runtime validation:
  **41 projects**, including root `junit-team`; `succeeded: yes`.
- JUnit snapshot assertions:
  - only modular-monolith architecture reported;
  - microservices, CQRS, and hexagonal not reported;
  - dependency analysis marked not executed;
  - 35 declared dependency records and 16 distinct manifests;
  - Spring scoped to documentation test/sample evidence;
  - compact explanation context approximately 6,663 tokens.
- Complete validation:
  **3443 passed, 1 skipped, 1 warning** in 9.40s.
  The warning is a `PytestCacheWarning` caused by denied write access to
  `.pytest_cache`; it did not affect test execution.
- An initial full-suite launch was interrupted by the command runner after
  1.1s before pytest produced a result. It is not counted as a test result.
- Clean patch replay:
  patch applied successfully to detached baseline `07e88e7`; targeted replay
  suite **17 passed** in 0.75s.
