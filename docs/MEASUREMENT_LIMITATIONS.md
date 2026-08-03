# Performance Measurement Limitations

M2.0 establishes measurement evidence; it does not implement a performance
optimization or claim enterprise-scale readiness.

- Memory probes sample the current process at scope boundaries. The CLI summary says
  `maximum_sampled_rss_bytes`; it is not an operating-system peak-RSS claim.
- Process-memory support is currently best effort on Windows and Linux. Unsupported
  platforms and failed probes remain explicit in the JSON.
- `process_utilization_percent` is process CPU divided by scope wall time. It is not
  normalized by logical CPU count and may exceed 100% when multiple threads execute.
- Python allocation sampling is separate and opt-in through
  `--profile-python-memory`. Atlas starts and stops `tracemalloc` only when it owns
  that tracer. Overlapping in-process Atlas profiling contexts share reference-counted
  ownership; an already-active tracer is sampled without being reset or stopped.
  Its peak can therefore include allocations made before Atlas profiling began.
- Per-core utilization, CPU topology, Intel performance/efficiency core type, GIL
  contention, operating-system process I/O counters or durations, page faults,
  storage latency, open-file count, thermal throttling, and energy use are not
  measured. Explicit filesystem counters cannot by themselves prove a phase is
  I/O-bound.
- Worker queue, idle, and service metrics remain unavailable unless the worker path
  supplies those facts. Support is scope-local; requested parallelism alone is not
  proof of utilization. A nested phase inherits the worker identifier but does not
  inherit queue facts it did not measure.
- Process CPU is process-wide. Atlas reports it unavailable with reason
  `concurrent-scope-attribution` inside concurrent worker scopes rather than assigning
  other workers' CPU to the current phase. Thread CPU remains attributable where the
  runtime supports it.
- Scope wall/CPU samples are inclusive. Their `sample-sum` aggregates may overlap
  across nested or concurrent scopes and cannot be added into an exclusive pipeline
  total. Gauges, ratios, boundary memory samples, and peaks use distribution-only
  aggregation and never claim a total.
- Filesystem counters cover explicit instrumented boundaries, not every Python or OS
  I/O operation. The JSON therefore marks enabled ledger coverage as partial.
  Physical byte sizes are exact only when already known or when a profiler-induced
  metadata lookup is used; those lookups are reported separately. Most decoded text
  producers avoid the extra lookup and report unavailable bytes. Resource-repeat
  evidence covers content-read boundaries only, not repeated enumeration, hashing,
  or parsing identities.
- Repeat-read identity tracking is bounded to 100,000 normalized path identities by
  default. Once the bound is reached, counters and byte observations continue while
  additional identity correlations are reported as untracked. The in-memory digest
  index can itself retain tens of MiB near the default cap. Consumer-overlap
  construction is quadratic in consumers touching one resource; Atlas-owned
  consumers are a small fixed set, and arbitrary untrusted consumer IDs are outside
  this API's trust boundary.
- A phase listed as unavailable was not measured. It must not be interpreted as zero
  cost or successful execution.
- Deterministic sampling is supported for embedded consumers but the CLI currently
  records every eligible scope. Aggregates are never extrapolated from a sample; use
  the serialized eligible/sampled counts when judging coverage.
- Instrumentation adds clock, probe, locking, aggregation, serialization, and fsync
  overhead. Benchmarks must compare equivalent measurement configurations.
- Sidecars are written during profile finalization, including after a partially
  measured command failure. Errors that occur before profile configuration can still
  prevent publication. A final sidecar I/O failure is reported on stderr and never
  changes or masks the Atlas command outcome. Invalid profile option paths are still
  rejected as configuration errors before execution.
- `latest.json` is an atomic latest-value sidecar, not an archive. External benchmark
  tooling must retain artifacts and record Atlas/repository revision, environment,
  worker count, cache mode, and run scope.
- The sidecar is source-free, but operational access controls remain the
  responsibility of the environment that stores it.
- Portable identifiers are structurally restricted, but arbitrary third-party plugin
  labels cannot be proven non-sensitive by syntax alone. Atlas-owned producers use
  fixed generic identifiers; plugin authors must do the same.
- The raw sidecar intentionally omits repository names and paths. Retain it with the
  benchmark manifest to record revisions, runtime inventory, execution mode, workers,
  and deterministic semantic-output hashes before comparing runs.

Optimization decisions require repeated pinned-repository measurements and unchanged
semantic determinism gates. A single sidecar is diagnostic evidence, not a benchmark
baseline.
