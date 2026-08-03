# Performance Measurement Architecture

Atlas performance measurement is an optional operational subsystem. It observes
existing work; it does not change semantic analysis, scheduling, repository
identity, snapshots, reports, confidence, or evidence.

## Data flow

```text
atlas analyze --profile
        |
        v
run-local MeasurementSession
        |
        +-- instrumented phase scopes
        +-- run-local filesystem counters
        +-- optional process-memory probe
        |
        v
immutable MeasurementReport
        |
        +-- atomic JSON sidecar
        `-- compact stderr summary
```

The CLI creates one session before workspace discovery and passes the same session
through the analysis and snapshot-publication path. Instrumented components record
stable phase identifiers and numeric counters only. No process-global Atlas collector
is installed. Optional Python allocation mode temporarily owns the process-global
`tracemalloc` service only when it was not already active. Disabled helpers return
immediately: they perform no identifier validation, accounting, clocks, memory
probes, filesystem metadata probes, or resource hashing.

Samples are immutable and aggregation is deterministic with respect to the samples
collected. Runtime measurements themselves are observations and are not expected to
be byte-identical between executions. Timing scopes are inclusive. Additive work,
overlapping sample sums, and non-additive distributions are represented explicitly;
gauges and ratios never acquire fabricated totals.

## Stable phase model

| Phase ID | Boundary |
| --- | --- |
| `workspace.discovery` | Workspace and project discovery. |
| `project.ownership` | Project ownership and dependency graph establishment. |
| `project.analysis` | One project analyzer invocation and existing worker facts. |
| `repository.inventory` | Per-project file inventory and classification. |
| `filesystem.traversal` | Explicit directory/file enumeration. |
| `path.normalization` | Explicit path-resolution boundaries. |
| `build.parsing` | Workspace/build descriptor parsing. |
| `language.java.parsing` | Java frontend execution. |
| `language.kotlin.parsing` | Reserved; unavailable unless an authoritative Kotlin producer runs. |
| `language.python.parsing` | Python frontend execution. |
| `symbol.extraction` | Language and workspace symbol extraction/merge. |
| `dependency.intelligence` | Declared dependency extraction. |
| `knowledge_graph.build` | Canonical graph construction or restoration. |
| `architecture.analysis` | Existing specialized and repository architecture analysis. |
| `reachability.analysis` | Existing reachability analysis. |
| `risk.analysis` | Existing risk/hotspot analysis. |
| `repository.summary` | Repository Summary composition. |
| `repository.report` | Repository Report composition. |
| `explain.projection` | Deterministic Explain selection/rendering, excluding providers. |
| `semantic_snapshot.build` | ASS capture and workspace fingerprint association. |
| `serialization` | Canonical operational or semantic serialization boundaries. |
| `persistence` | Existing state/snapshot reads and durable state writes. |
| `recovery` | Existing journal validation and publication. |
| `publication` | Atomic semantic artifact publication. |

The current registry maps Java, Python, and TypeScript to stable parsing phases;
unrecognized registered languages collapse to `language.other.parsing`. PR130 pattern
detection currently emits the additive `design_patterns.analysis` extension.
Extensions must follow the same source-free identifier contract and do not modify
semantic identity. An absent phase is reported unavailable unless a producer supplies
authoritative unsupported evidence.

## Boundaries

- Measurement data is never added to semantic context or an ASS snapshot.
- Measurement data cannot affect canonical ordering, cache validity, recovery, or
  analysis success.
- Profiled analysis runs remain visible in history, but their instrumented durations
  are explicitly excluded from adaptive-worker inputs. This prevents measurement
  overhead from changing a later scheduling decision.
- Consumers and workers use portable identifiers, not repository paths.
- Unsupported and unavailable counters remain explicit instead of being estimated.
- Existing concurrent project workers provide queue/service facts only on their own
  project scopes. Nested scopes inherit their portable worker ID. Process-wide CPU is
  explicitly unavailable for attribution inside concurrent worker scopes; thread CPU
  remains usable where supported.
- The filesystem ledger records physical sizes and generic consumer IDs at explicit
  instrumentation boundaries. It retains only one-way in-memory resource digests,
  then publishes aggregate unique/repeated-read counts and generic consumer overlaps.
  It is intentionally marked partial and retains no path or resource digest. Identity
  tracking stops at 100,000 resources by default and reports any untracked reads.
- The existing PR96 `atlas profile` command remains a separate compatibility
surface. M2 measurement is exposed through opt-in `atlas analyze` and
`atlas ai explain` options.

Sidecar publication is operational best effort: failure emits a source-free stderr
diagnostic and cannot change or mask the Atlas result. The pre-existing PR96 profiler
remains a compatibility surface; consolidation behind the M2 model is deferred until
its public contract can be preserved without speculative refactoring.

The stable phase registry and public measurement models live in
`moughorai.measurement`. New instrumentation must reuse the run-local session rather
than introduce another profiler or metrics model.

See [Measurement API](../MEASUREMENT_API.md) for extension rules and
[Platform Matrix](../MEASUREMENT_PLATFORM_MATRIX.md) for counter support and normal
phase coverage.
