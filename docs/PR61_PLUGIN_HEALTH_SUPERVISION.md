# PR61 — Plugin Health Supervision and Circuit Breaking

PR61 adds an optional health-supervision layer to the plugin SDK introduced in PR59 and secured in PR60.

## Capabilities

- deterministic health probes for loaded extensions;
- configurable consecutive failure and recovery thresholds;
- healthy, degraded, unhealthy, quarantined, and unknown states;
- guarded extension invocation with circuit-breaking for unhealthy extensions;
- manual quarantine and release operations;
- lifecycle synchronization that removes records for unloaded extensions;
- stable, monotonically sequenced health events;
- deterministic JSON snapshots and status counts.

Extensions may expose `health_check()` or `health_check(context)`. Supported results are a boolean, a `(boolean, message)` tuple, a mapping with `healthy` and optional `message`, or `None`. Extensions without a health probe are considered healthy when probed.

The feature is additive. Existing plugin manifests, registries, runtimes, trust stores, and permission policies require no changes.
