# Performance Measurement API

`moughorai.measurement` is Atlas's reusable, source-free operational measurement
API. It is disabled by default and remains separate from semantic models, snapshots,
evidence, hashes, ordering, and cache keys.

## Session lifecycle

Create one session per Atlas run and pass it to existing services:

```python
from moughorai.measurement import MeasurementConfig, MeasurementPhase, MeasurementSession

session = MeasurementSession(MeasurementConfig(enabled=True))
with session.scope(
    MeasurementPhase.REPOSITORY_INVENTORY,
    consumer="repository-inventory",
    sample_key="workspace",
) as scope:
    result = build_inventory()
    scope.add_units(len(result.files))
    scope.add_objects_produced(len(result.files))

report = session.report()
```

The session owns immutable completed samples, a thread-safe run-local filesystem
ledger, per-context nested scope stacks, and deterministic sampling coverage. It does
not install a process-global collector. `report()` takes a consistent copy without
ending collection; `clear()` discards run-local observations.

Disabled scopes reuse an allocation-light no-op context. They perform no validation,
clock reads, memory probes, filesystem probes, hashing, or accounting. Scope counter
methods and filesystem helpers return without inspecting their input.

## Configuration

| Field | Default | Contract |
| --- | ---: | --- |
| `enabled` | `False` | Master opt-in. |
| `capture_process_cpu` | `True` | Process CPU clock at sampled boundaries. |
| `capture_thread_cpu` | `True` | Thread CPU where the runtime provides it. |
| `capture_process_memory` | `False` | Best-effort RSS/working-set/commit samples. |
| `capture_python_memory` | `False` | Read an already-active `tracemalloc` service. CLI ownership is separate. |
| `capture_filesystem` | `True` | Explicit filesystem ledger boundaries. |
| `worker_metrics_supported` | `False` | Allows facts only on scopes marked `worker_metrics=True`. |
| `sample_every` | `1` | Deterministic one-in-N scope sampling. |
| `filesystem_resource_limit` | `100000` | Maximum resource identities retained for repeat correlation. |
| `worker_id` | `main` | Default portable worker identifier. |

Boolean fields require actual booleans. Counts and limits require non-negative or
positive integers as appropriate. Consumer, phase, worker, and metric identifiers
must be lowercase portable identifiers; paths and arbitrary labels are rejected.

## Scope facts

Every sampled scope records wall time, process CPU, thread CPU, process utilization,
optional memory observations, worker/thread identifiers, success, and explicit work
counters. Producers can record:

- additive processed units and bytes;
- additive objects produced;
- a retained-object boundary estimate, which is not an object census or retained-byte
  measurement;
- queue wait, idle time, and queue depth only where the worker path supplies them.

Atlas's concurrent project executor defines queue wait from immediately before task
submission to worker start; queue depth as submitted-but-not-started tasks remaining
after that worker dequeues; service time as the project scope's wall time; and idle
time as the interval from the same worker thread's prior completion to its next start.
Nested scopes inherit the worker ID but not queue facts. Process CPU/utilization is
unavailable in concurrent worker contexts because it cannot be attributed reliably;
thread CPU remains available where supported.

All scopes are inclusive. `sample-sum` timing aggregates can overlap and are never an
exclusive end-to-end duration. Gauges, ratios, boundary memory values, peaks, and
retained counts are distributions with no additive total.

## Deterministic sampling

When `sample_every` is greater than one, every eligible scope supplies a stable
`sample_key`. Selection hashes the nested phase path, consumer, and key. Worker ID is
excluded because scheduling is nondeterministic. The key is never retained. Reports
publish exact global and per-phase eligible/sampled counts and never extrapolate
unsampled work. A phase with eligible scopes but no selected sample is
`unavailable/sampled-out`.

## Filesystem ledger

Use the helper matching evidence already available:

- `file_content_read_known_size()` when bytes are already in memory;
- `file_content_read_unknown_size()` to avoid an extra metadata probe;
- `file_content_read()` when a deliberate size lookup is acceptable;
- operation helpers for directory enumeration, metadata lookup, normalization,
  hashing, descriptor parsing, and language parsing.

File-aware calls transiently hash a normalized absolute path. Only aggregate
unique/repeated/consumer-overlap counts enter the report; neither paths nor digests
are serialized. Identity aliases and symlinks are not coalesced. Identity tracking is
bounded and reports limit state and untracked reads explicitly. The ledger is always
run-local and its enabled coverage is partial because it does not intercept every OS
or Python I/O operation.

## Failure isolation and extension rules

Measurement completion errors are swallowed at the instrumentation boundary so they
cannot replace an application exception or change success. Sidecar publication is
also best effort. Invalid explicit API inputs are still rejected when measurement is
enabled.

New integrations must:

1. reuse the existing session, models, status/reason vocabulary, and filesystem
   ledger;
2. add a stable phase only for a real producer boundary;
3. report unavailable or unsupported instead of estimating;
4. keep provider/LLM latency and source content outside Atlas semantic phases;
5. supply deterministic sampling keys that are not retained;
6. add exact round-trip, reordered-input, source-free, disabled-path, and failure
   isolation tests;
7. never use observations in semantic IDs, ordering, scheduling, cache validity, or
   adaptive history.

`MeasurementReport.from_dict()` is the canonical loader. Beyond the wire schema, it
verifies derived arrays, sampling/sample consistency, filesystem totals, repeat
evidence, status/reason pairs, and exact `to_dict()` round trips.
