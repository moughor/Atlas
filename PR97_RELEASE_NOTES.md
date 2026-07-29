# PR97 Release Notes

PR97 adds opt-in adaptive worker selection for workspace analysis. The policy
uses dependency-wave width, local CPU capacity, the requested worker cap, and
recent PR94 project timings.

Use `--adaptive` with `atlas analyze` or `atlas check`. Default worker
semantics and deterministic report ordering remain unchanged.
