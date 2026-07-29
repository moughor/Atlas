# PR58 — Distributed Analysis Coordinator

PR58 adds a transport-neutral coordinator for distributing incremental analysis jobs across workers while retaining deterministic scheduling and result ordering.

## Capabilities

- Worker registration, capabilities, metadata, heartbeat, and stale-worker detection.
- Deterministic dependency-aware leasing with bounded lease durations.
- Capability filtering and stable path ordering.
- Retry and lease-expiration rescheduling.
- Terminal failure propagation and transitive dependent cancellation.
- Lease ownership validation.
- Deterministic snapshots, metrics, assignments, failures, cancellations, and merged results.
- An in-process execution adapter for testing and single-host deployments.

## Design boundary

The coordinator deliberately does not impose a network framework. HTTP, RPC, message-queue, or database adapters can expose the coordinator methods while preserving the same scheduling semantics. This keeps Atlas free from transport dependencies and makes the core behavior testable.

## Basic use

```python
from pathlib import Path
from moughorai.incremental_analysis import DistributedAnalysisCoordinator, DistributedJob

coordinator = DistributedAnalysisCoordinator(lease_seconds=30)
coordinator.register_worker("worker-1", capabilities=("python",))
coordinator.submit([
    DistributedJob(Path("src/a.py"), "a" * 64, required_capabilities=("python",)),
])
lease = coordinator.lease("worker-1")[0]
coordinator.complete("worker-1", lease.lease_id, {"findings": []})
```

## Compatibility

PR55 sequential execution, PR56 parallel scheduling, and PR57 resilient checkpoint APIs are unchanged.
