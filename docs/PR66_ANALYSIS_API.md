# PR66 — Analysis Service API

PR66 introduces a framework-neutral service and router for analysis jobs.

## Capabilities

- Validated analysis requests and normalized results.
- Pending, running, succeeded, failed, and cancelled job states.
- Request-id idempotency.
- Deterministic job listing and JSON serialization.
- Submit, run, get, list, cancel, and delete operations.
- Minimal HTTP-style router for `/v1/analysis/jobs` without a web-framework dependency.
- Structured 400, 404, and 409 errors.
