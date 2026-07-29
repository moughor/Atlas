# PR97 — Adaptive Scheduler

Use `--adaptive` with `atlas analyze` or `atlas check`. Atlas computes maximum
safe parallelism from dependency waves, bounds it by the requested worker cap
and local CPU availability, and consults recent PR94 timings. When every
project is historically below the trivial-work threshold, it selects one
worker to avoid thread overhead.

The option only chooses the `max_workers` value passed to PR73. Dependency
ordering, failure semantics, report order, and default non-adaptive behavior
remain unchanged.
