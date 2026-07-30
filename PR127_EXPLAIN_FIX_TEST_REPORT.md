# PR127 Explain Integration Fix — Test Report

- Targeted explain/prompt/summary/architecture suite:
  **20 passed** in 0.59s.
- JUnit snapshot inspection:
  - repository summary present;
  - 41 projects present;
  - dedicated repository template selected;
  - detailed symbols omitted;
  - estimated input reduced to **7,373 tokens**.
- Complete validation: **3442 passed, 1 skipped** in 9.13s.
- Clean patch replay on `7004478`: patch applied and targeted suite completed
  with **20 passed** in 0.79s.

Pytest emitted one cache-provider warning because the pre-existing
`.pytest_cache` directory was not writable. Test execution completed normally.
