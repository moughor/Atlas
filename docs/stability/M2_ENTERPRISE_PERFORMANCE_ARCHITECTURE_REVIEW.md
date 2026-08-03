# Atlas Enterprise Performance Architecture Review

Status: M2 candidate, measurement gate

Date: 2026-08-03

Reviewed Atlas revision: `17ba50864b5fd7dd737eb5a722c823ff9b964d90`

## Decision

Atlas is not ready for an enterprise optimization implementation yet. It has strong
correctness, deterministic-output, replay, artifact-size, and end-to-end wall-time
evidence. It does not yet measure enough of the pipeline to attribute enterprise cost
or choose safely between filesystem, parser, graph, serialization, memory-layout, and
scheduling changes.

This review therefore authorizes **measurement infrastructure and controlled
experiments only**. It authorizes no persistent cache, parser rewrite, graph rewrite,
snapshot-format change, process pool, core affinity, or PR135+ functionality.

The first M2 decision gate is:

1. collect comparable phase, CPU, memory, I/O, allocation, and worker-scaling data;
2. reproduce it on the same pinned inputs and environment;
3. preserve every deterministic output gate;
4. select at most one or two generic optimizations whose benefit is then measured
   against the unchanged baseline.

## Evidence labels

This document uses these labels throughout:

- **Measured fact**: produced by an executed Atlas benchmark or profiler and retained
  with an identifiable scope.
- **Engineering inference**: supported by code structure or measured adjacent work,
  but not yet demonstrated by an isolated performance measurement.
- **Future recommendation**: a proposed experiment or architecture, not current
  behavior and not an implementation authorization.

Measurements from different Atlas commits, repositories, worker counts, or scopes are
not combined into a single pipeline total.

## Executive summary

### What is already known

- **Measured fact:** accepted M1.1 Maven and Quarkus baselines provide three repeated,
  clean-state, one-worker end-to-end wall times and exact deterministic artifacts.
- **Measured fact:** the only retained full Maven phase profile identified Java parsing
  as the dominant CPU candidate, followed by repeated filesystem scans and semantic
  context construction. Its cumulative profiler values overlap and are historical,
  not current M2 baselines.
- **Measured fact:** large snapshots are already expensive. Elasticsearch produced a
  544,047,044-byte diagnostic snapshot; the combined load, validation, portable
  projection, explanation, and hashing workflow took about 241 seconds in each of two
  runs.
- **Measured fact:** a synthetic one-million-node/two-million-edge PR134 graph run
  reached 3,415,515,136 bytes process peak RSS. Warm indexed lookup remained fast;
  cold construction and indexing were the costly part.
- **Measured fact:** Atlas's built-in profiler records elapsed workspace and project
  times only. It does not record CPU time, RSS, I/O, allocations, retained objects,
  worker idle time, per-core use, GIL behavior, or stage timings.
- **Measured fact:** accepted fresh repository baselines use one worker. Atlas has no
  retained 1/2/4/8/12/16/20/24 worker scaling curve.
- **Engineering inference from code:** the shared production `AnalyzerRegistry` owns
  one `JavaLanguageAnalyzer`, which owns one stateful `JavaParser`. `parse()` mutates
  `_tokens` and `_position`. High-worker Java scaling must not be benchmarked or
  promoted until this shared-state concurrency prerequisite is isolated and covered
  by reproducibility stress tests.
- **Measured fact:** no end-to-end 47,000-file, 4,000,000-line, mixed-language corpus
  has been measured. Kotlin has no registered production analyzer in the current
  analyzer registry, so Kotlin semantic throughput cannot currently be profiled.

### Architectural conclusion

The largest evidence-backed M2 investigation priorities are:

1. snapshot materialization, serialization, loading, and transient memory;
2. Java lexing and parsing;
3. repeated file inventory, source reads, path normalization, and manifest parsing;
4. cold graph/resolver/report index construction and retained graph representation;
5. incremental artifact reuse, only after formal invalidation semantics exist.

These are profiling priorities, not approved optimizations. Warm Explain lookup and
bounded context selection are already fast and are not M2 optimization targets.

## Retained measured evidence

### Accepted M1.1 fresh baselines

The following tracked manifests were captured on Atlas commit
`7565042439ef3f3607c7ba4849d445f79e9ef550`, Windows 11 AMD64, CPython 3.12.13,
one worker, and `force-no-recover`. They predate the reviewed HEAD and must not be
used as current-output hash expectations.

| Workload | Tracked files | Projects | Samples (ms) | Median | Mean | Population standard deviation | Nearest-rank p95 | Raw ASS |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| Apache Maven | 10,122 | 92/92 | 23,922; 23,615; 23,662 | 23,662 ms | 23,733 ms | 135.01 ms | 23,922 ms | 31,168,556 B |
| Quarkus | 31,433 | 1,442/1,442 | 347,620; 346,927; 348,588 | 347,620 ms | 347,711.67 ms | 681.19 ms | 348,588 ms | 337,100,718 B |

The corresponding tracked-file throughputs are approximately 427.77 and 90.42 files
per second. These figures use Git tracked-file counts, not parsed semantic source
counts; they demonstrate workload sensitivity and are not parser throughput.

Accepted replay medians were 16,937 ms for Maven and 100,700 ms for Quarkus. Replay
excludes fresh discovery and analysis and must not be compared as if it were a warm
fresh run.

Sources:

- `benchmarks/baselines/apache-maven-fresh.json`
- `benchmarks/baselines/quarkus-fresh.json`
- `docs/stability/M1_1_VALIDATION_REPORT.md`

### Historical phase evidence

The historical one-worker Maven cProfile review measured these overlapping cumulative
times:

| Subsystem | Historical measurement | Scope warning |
| --- | ---: | --- |
| Workspace discovery | 0.83 s | Historical unpinned Maven archive |
| Maven model parsing | 0.56 s / 2,070 parses | Multiple consumers; cumulative calls |
| Filesystem traversal/matching | 8.14 s / 276 scans | Analysis, summary, and fingerprint scopes overlap |
| Java parsing | 35.21 s / 2,791 units | Dominant measured CPU candidate |
| Java/global symbol indexing | about 0.35 s | Not a current enterprise sample |
| Dependency intelligence | 0.43 s | Maven-specific sample |
| Semantic-context collection | 21.86 s | Contains several child phases |
| Context model construction | 5.98 s | Symbol projection dominated |
| Repository summary | 11.26 s | Includes filesystem work |
| Snapshot capture | 4.53 s | Includes workspace fingerprinting |
| Serialization/save | 2.43 s / 30,783,110 B | Small compared with later corpora |

These values cannot be summed. They establish candidates for isolation, not a current
end-to-end decomposition. Source: `docs/ATLAS_PERFORMANCE_ENGINEERING_REVIEW.md`.

### Scale diagnostics

- A one-sample synthetic 23,000-file/23-project index-and-fingerprint benchmark took
  22.138827 seconds, reported 1,038.9 files/s, and reached 16.77 MiB peak traced Python
  allocation. It did not perform full Atlas analysis.
- Elasticsearch diagnostic runs produced 353,403 symbols, 355,782 graph nodes,
  388,613 edges, and a 544,047,044-byte ASS. Snapshot sections included approximately
  169.8 MB of symbols, 136.7 MB of semantic graph, and 56.8 MB of design patterns.
  The combined retained-snapshot workflow took 241.4 and 240.8 seconds. It was not
  phase-separated and did not measure peak memory.
- PR134's synthetic one-million-node/two-million-edge graph used 3,415,515,136 bytes
  peak RSS. Cold resolver indexing p95 was 16.386452 seconds; warm lookup was about
  71.6 microseconds per subject. This is a graph/query benchmark, not one million
  source symbols or a full analysis.
- IntelliJ source selection improved from 39.654453 to 8.519099 seconds through an
  already completed correctness-preserving source-root isolation change. No successful
  IntelliJ snapshot or peak-memory sample exists because module identity remains a
  semantic limitation.

Sources:

- `PR104_TEST_REPORT.md`
- `docs/stability/ELASTICSEARCH_FAILURE_INVESTIGATION.md`
- `docs/PR134_VERIFICATION.md`
- `docs/stability/INTELLIJ_FIXTURE_SOURCE_ROOT_INVESTIGATION.md`

## Measurement gaps

The M2 optimization gate is currently blocked by missing evidence in all of these
areas:

| Requested evidence | Current state |
| --- | --- |
| Stage wall and CPU time | Only workspace/project wall time is built in |
| CPU percentage and per-core utilization | Not measured |
| P-core versus E-core use | Not measured |
| Worker idle and queue wait | Not measured |
| GIL-held versus native/GIL-released time | Not measured |
| Threads versus processes | No controlled comparison |
| Peak process RSS and committed memory | Missing for successful large fresh analyses |
| Python allocated and retained objects | Only isolated `tracemalloc` measurements exist |
| I/O bytes, operations, faults, and metadata calls | Not measured |
| Exact per-file touch/read/parse counts | Not measured |
| 2–24 worker scaling | Not measured |
| Cold filesystem versus warm filesystem | Not controlled portably |
| Python startup versus steady state | Not separated |
| Incremental hit rate and avoided work | Not measured |
| 1M/5M/10M semantic-symbol memory | Not measured |
| Mixed Java/Kotlin/Python enterprise run | Not available; Kotlin analyzer absent |

The current `atlas profile` command constructs the workspace before starting its
workspace timer, and stops after project orchestration. It therefore excludes
discovery, history recording, semantic collection, repository summary, canonical and
specialized analyses, report construction, snapshot capture/serialization/write,
recovery checkpoint overhead, and Explain.

No optimization should be selected from static call counts alone.

## Atlas pipeline profile

The classifications below are engineering inferences except where a retained
measurement is cited.

| Stage | Current profile | Resource hypothesis | Required M2 counters |
| --- | --- | --- | --- |
| Workspace discovery | Historical Maven: 0.83 s | I/O, path, XML, sorting | entries visited, descriptors read, bytes, CPU/wall |
| Project ownership | Not isolated | Path canonicalization and containment | paths resolved, ownership candidates, CPU/wall |
| Repository inventory | Part of repeated 276 scans | I/O/metadata and allocations | walks, stat calls, duplicate records, retained inventory |
| Filesystem traversal | Historical Maven: 8.14 s cumulative | I/O plus Python matching | directories/files visited, exclusions, metadata calls |
| Build parsing | Maven POM: 0.56 s/2,070 historical parses | XML/text CPU and repeated reads | per-descriptor reads/parses/cache identity |
| Java parsing | Historical Maven: 35.21 s/2,791 units | CPU and allocation; likely GIL-sensitive | lexer/parser CPU, tokens/nodes, RSS, GIL/process scaling |
| Kotlin parsing | Unavailable | Unknown | Must wait for an authoritative analyzer |
| Python parsing | Production analyzer exists; no retained profile | CPU/allocation hypothesis | AST CPU, nodes, GIL/process scaling |
| Symbol extraction | Historical Java/global build about 0.35 s | CPU/allocation | symbols/members, temporary and retained bytes |
| Dependency intelligence | Historical Maven: 0.43 s | Descriptor I/O/parse | unique manifests, repeated parse count, dependencies |
| KnowledgeGraph | Not isolated end-to-end | Allocation, hashing, sorting | nodes/edges, insert/merge/sort/hash time, peak RSS |
| Architecture | Historical Maven: 1.62 s | Graph CPU | evidence/edge counts, traversal time |
| Reachability | Historical Maven: 1.52 s | Graph traversal and maps | roots, visited nodes/edges, bounds, retained maps |
| Risk | Synthetic/component evidence only | Graph/metrics CPU | subjects, findings, each producer time |
| Repository report | Component benchmarks exist | Sorting/projection/allocation | facts/items, section lineage, build/select time |
| Explain | Warm lookup/selection already fast | Cold index allocation; provider external | cold index, warm lookup, selection; exclude LLM latency |
| Snapshot capture | Historical Maven: 4.53 s | Hashing and full workspace fingerprint reads | bytes hashed, files reread, allocation |
| Serialization | Historical 30.8 MB save 2.43 s; large combined workflows costly | CPU, allocation, write I/O | object-to-dict, canonical encode, checksum, final encode, write |
| Compression | No production compression stage | Not applicable | Evaluate only after serialization evidence |
| Persistence | Not isolated | Full-project fingerprinting and JSON I/O | fingerprints, encoded bytes, read/write/verify time |
| Recovery | Not isolated | Journal I/O plus state restore | journal bytes/events, restore/validation time |

### Static repeated-work evidence

The normal production path currently exposes these potential repetitions:

- `AnalyzerRegistry` calls `project_files()` once per project and reads language
  sources.
- `RepositorySummaryService` calls `project_files()` again, stats files, reparses
  dependency manifests, and rereads Java/Python/JavaScript/TypeScript sources to find
  entry points.
- `WorkspaceCache` performs another project walk and reads every selected file to
  compute content fingerprints when persistence/recovery captures or validates state.
- Recovery synchronously captures and saves workspace state after each completed
  project. Because capture fingerprints every project by walking and reading its
  files, a successful recovered run with `P` projects can perform approximately
  `P + 2` whole-workspace fingerprint passes, with journal validation able to add
  another. This is a code-derived upper-path count, not a timing measurement.
- Recovery also rewrites and fsyncs its journal on project state transitions and
  rewrites a growing encoded workspace state after every completed project.
- Nested project roots can be walked before repository summary removes files owned by
  child projects.
- `SemanticContextCollector` converts the context to dictionaries and reconstructs the
  canonical graph from serialized form for downstream analyses.
- Snapshot serialization constructs a semantic payload, canonical checksum input, and
  final JSON text; large payloads may therefore coexist transiently.

These are code-path observations. M2 must count actual touches, bytes, allocations,
and retained objects before consolidating any of them.

## Measurement architecture

### Run identity

Every M2 sample must record:

- exact Atlas and repository commits;
- benchmark schema and instrumentation producer version;
- Python implementation/version and complete dependency inventory;
- OS, architecture, logical CPU count, effective memory/cgroup/job limit;
- worker model and count, affinity mode, and queue bounds;
- configuration, source-selection, and analyzer fingerprints;
- fresh/replay/incremental mode;
- Atlas-state-cold, process-cold, filesystem-warm, or controlled-filesystem-cold mode;
- exact deterministic output hashes and counts.

Raw source paths, hostnames, usernames, source content, and enterprise identifiers must
not enter a retained manifest.

### Phase sample

Each bounded phase should record at least:

- wall and process/thread CPU nanoseconds;
- calls, units, files, bytes, symbols, nodes, and edges;
- process RSS/commit before, after, and sampled peak;
- Python allocated current/peak only when `tracemalloc` is intentionally enabled;
- I/O read/write bytes and operation counts where the OS exposes them;
- queue wait, service time, worker idle, and maximum in-flight bytes;
- produced and retained object/byte counts at explicit phase boundaries;
- serialization bytes and stable result digest.

Instrumentation must be run-local, bounded, disabled by default, and excluded from
semantic identity. Metric aggregation must be deterministic even though timing values
are observations.

### Sampling protocol

1. Pin the machine power policy and record—not assume—the available topology.
2. Measure Python startup independently.
3. Perform one unrecorded warm-up for component benchmarks.
4. Use five samples for bounded components and at least three for expensive fresh
   analyses, matching the existing performance policy.
5. Record every sample; report median, mean, population variance, standard deviation,
   and diagnostic nearest-rank p95.
6. Randomize or alternate candidate/baseline order within one stable session.
7. Repeat any optimization result in a second independent batch.
8. Never combine process-cold, Atlas-state-cold, filesystem-warm, and truly cold
   filesystem samples.

Portable code cannot reliably flush the OS filesystem cache. Controlled cold-cache
runs therefore belong on dedicated runners with an explicitly documented OS-specific
procedure; normal developer runs should be labeled filesystem-warm or uncontrolled.

### File-access ledger

Before introducing a shared inventory, M2 should measure file use through a bounded
run-local ledger keyed by source-free repository-relative identity. It should count:

- directory enumeration;
- metadata lookup;
- canonicalization;
- content read and bytes;
- content hash;
- descriptor parse;
- language parse;
- downstream consumer names.

The ledger is diagnostic only and must not become a persistent semantic cache.

## CPU and concurrency assessment

### Current architecture

Atlas schedules dependency-ready projects through `ThreadPoolExecutor`. Results are
stored and reported in deterministic project order rather than completion order.
`AdaptiveWorkspaceScheduler` caps workers by `os.cpu_count()`, the caller's limit, and
the maximum dependency wave. It has no measured CPU saturation feedback and no hybrid
core awareness.

The scheduling order is deterministic, but Java parsing has a correctness prerequisite:
one shared analyzer registry reuses one `JavaParser`, and that parser stores the active
token tuple and cursor in mutable instance fields. Concurrent calls can therefore
interleave parser state. This review does not claim a reproduced failure, but it does
classify task-local or otherwise isolated parser state plus stress testing as mandatory
before performance scaling.

The project-level concurrency model also has two unproven performance limits:

- CPU-bound CPython work may not scale through threads because of the GIL;
- a large monolithic project exposes little project-wave parallelism.

### Required worker experiment

Run identical pinned workloads at:

```text
1, 2, 4, 8, 12, 16, 20, and 24 workers
```

For each worker count record wall time, CPU time, utilization, peak RSS, I/O, context
switches, queue wait, idle time, and exact output hashes. Test project threads first.
Only if parser CPU is dominant and thread scaling plateaus should Atlas compare a
bounded process-pool prototype.

Nested project and file-level pools must not operate independently. A single run-level
resource budget must prevent oversubscription and cap in-flight fragment bytes.

### Deterministic parallel architecture

If measurements justify subproject parallelism, workers should produce immutable
fragments:

```text
inventory key
  -> parsed language fragment
  -> local symbols and evidence
  -> local specialized-graph fragment
  -> canonical ordered reduction
  -> global duplicate/collision validation
  -> graph and finding producers
  -> final canonical serialization and atomic publication
```

Required invariants:

- IDs derive only from semantic inputs, never worker IDs or completion order.
- Workers never mutate a shared canonical graph.
- Fragments are merged by canonical scope/path/symbol order.
- Duplicate detection occurs deterministically during reduction and is never weakened.
- Diagnostics and failures are sorted by semantic identity.
- Queues are bounded by item count and estimated bytes.
- Final graph, reports, snapshot, hashes, and publication remain coordinator-owned.

### Intel hybrid assessment

Atlas should not hardcode Intel model names, P-core counts, E-core counts, processor
groups, or affinity masks.

Candidate phase preference for an experiment—not default policy—is:

- CPU-heavy parsing, graph reduction, canonical encoding, and hashing may benefit from
  performance cores;
- filesystem enumeration, descriptor prefetch, and background artifact writes may
  tolerate efficiency cores, although I/O-bound work may gain nothing from affinity;
- collision resolution, final canonical ordering, integrity verification, and atomic
  publication remain logically sequential even if their internal primitives later use
  deterministic chunks.

Windows scheduler placement is the correct default. Affinity remains off unless a
controlled experiment demonstrates a repeatable end-to-end improvement without worse
tail latency, memory, portability, or thermals. Linux, macOS, AMD, containers, and CI
must receive the same semantic scheduler; topology information may tune a cap but may
not affect output.

Worker autotuning should eventually select from measured throughput and memory curves,
not `cpu_count()` alone. It must respect OS/container memory and CPU limits and retain
an explicit user cap.

## Memory assessment

### Measured facts

- The synthetic 23,000-file inventory/fingerprint run reported 16.77 MiB peak traced
  Python allocation, but it excluded full parsing and semantic graph construction.
- Maven's 30.8 MB snapshot load/checksum historically reached approximately 157.7 MB
  peak traced allocation.
- Elasticsearch's snapshot is 544.0 MB; peak process memory was not measured.
- Quarkus PR133 report replay observed approximately 3.79 GB process peak working set,
  but the value includes snapshot and graph load over the process lifetime.
- The synthetic PR134 one-million-node/two-million-edge run reached about 3.18 GiB
  peak RSS.

### 1M/5M/10M planning estimate

Using only the PR134 synthetic graph shape and assuming perfectly linear scaling gives:

| Graph nodes | Linear peak-RSS estimate |
| ---: | ---: |
| 1 million | 3.18 GiB measured |
| 5 million | approximately 15.9 GiB inferred |
| 10 million | approximately 31.8 GiB inferred |

This is not a semantic-symbol budget or a capacity guarantee. Edge density, string
duplication, evidence size, Python allocator behavior, temporary canonical JSON, and
partitioning can move the result materially in either direction. It demonstrates that
a naive monolithic Python-object representation cannot be assumed safe at ten million
nodes.

### Provisional run budget

Until a measured object census exists, use a configurable soft budget rather than a
fixed workstation-specific number:

- Atlas soft limit: at most 50% of effective available/cgroup/job memory;
- Atlas hard scheduling limit: at most 60%; stop admitting work before paging;
- retained semantic model and graph: target at most 55% of the Atlas budget;
- parser/fragments in flight: at most 15%;
- indexes and deterministic merge state: at most 10%;
- serialization/checksum working data: at most 10%;
- runtime, diagnostics, and safety headroom: at least 10%.

These percentages are future operational defaults to validate, not measured Atlas
requirements.

Potential techniques remain conditional:

- run-local interning only after duplicate-string counts are known;
- compact fixed-length IDs only after ID/string retention is measured;
- `slots` only for high-count objects shown by an object census;
- arrays/columnar structures only for measured homogeneous hot indexes;
- streaming serialization only if exact canonical bytes and checksum remain identical;
- partitioning/lazy loading only when query and replay contracts are defined;
- compression only if reduced I/O exceeds added CPU and preserves format compatibility.

Global `sys.intern()` and unbounded process-lifetime caches should not be used because
they can retain enterprise identifiers indefinitely.

## Filesystem assessment

The first filesystem objective is not a cache. It is to determine exactly how often
each semantic input is enumerated, resolved, read, hashed, and parsed.

If the ledger proves substantial duplication, the lowest-risk experiment is a
run-scoped immutable inventory with explicit freshness boundaries:

1. enumerate disjoint project ownership once;
2. assign stable repository-relative identities;
3. capture metadata and content digest through one authoritative reader;
4. let parsers publish compact source-free facts needed by summaries, avoiding a
   second source read for entry-point detection;
5. let dependency consumers share one parsed manifest model during the same run;
6. validate that inputs did not change before publication; abort or retry on drift;
7. discard the inventory at run end.

Do not use mtime alone for correctness. Do not preserve raw source in snapshots or
persistent caches. Do not merge analyzer, persistence, and snapshot freshness
boundaries until their contracts are explicit.

## Enterprise incremental analysis

Persistent reuse is permitted only after every key and dependency is formalized.

| Artifact | Reuse key | Invalidation causes |
| --- | --- | --- |
| File inventory fact | relative identity, content digest, ownership/config producer | content, include/exclude, ownership, descriptor, producer |
| Parsed language fragment | content digest, parser version, language options, scope | any key change |
| Exported symbol surface | parsed-fragment ID and symbol producer | declaration/signature/visibility change |
| Local graph fragment | fragment IDs and graph producer | local semantic/evidence change |
| Declared dependencies | manifest digest and parser/config producer | manifest or interpretation change |
| Cross-project relations | source export digest, target export digest, dependency lineage | either endpoint or dependency change |
| Architecture/pattern/reachability/risk | canonical input partition digests and configuration | relevant graph/evidence/config change |
| Report section | finding/summary lineage set and report producer | any contributing lineage change |
| Explain index | snapshot/graph digest and resolver producer | graph or resolver change |
| Snapshot chunk | exact canonical semantic fragment and schema producer | any fragment/schema change |

Always recompute or verify:

- workspace/configuration/producer compatibility;
- change detection and content integrity;
- global duplicate and identity collision checks;
- dependency/topological consistency;
- deterministic global reduction and ordering;
- final report/graph/snapshot hashes;
- source-free projection checks and atomic publication.

Sometimes recompute:

- dependents when exported symbols or dependencies change;
- cross-module graph partitions when endpoint evidence changes;
- reachability and risk partitions affected by changed roots/edges;
- report sections whose lineage changed.

Never recompute when an exact, checksum-verified fragment key and all dependency
lineages match—but persistent storage for those fragments remains deferred until this
invalidation model has adversarial tests, producer versioning, bounded eviction,
corruption handling, and byte-identical fresh-versus-incremental validation.

## Optimization ranking

The `Expected gain` column describes opportunity, not a promised percentage.

| Rank | Opportunity | Evidence | Expected gain | Complexity | Memory effect | Determinism risk | Decision |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 0 | Phase/CPU/RSS/I/O/file-touch instrumentation | Measurement gap is proven | Enables every later decision | Medium | Small diagnostic overhead | Low if excluded from identity | First M2 work |
| 1 | Isolate Java parser state and stress deterministic concurrency | Shared mutable parser is proven by code inspection | Correctness prerequisite, not speed claim | Low–medium | Small | Prevents concurrency corruption | Before worker scaling |
| 2 | Recovery checkpoint amplification experiment | Per-project whole-workspace capture and growing fsync writes are proven by code inspection | Potentially high with many projects | Medium | Potential reduction | High durability/freshness risk | Instrument recover on/off first |
| 3 | Snapshot materialization/serialization/load experiment | 544 MB Elastic ASS; ~241 s combined retained workflow | Potentially high at large scale | High | Potentially large reduction | High: exact bytes/checksum | Profile subphases first |
| 4 | Java parser/thread/process scaling experiment | Historical 35.21 s Maven parse hotspot | Potentially high for Java-heavy corpora | High | Processes may multiply RSS | Medium | Only after rank 1 |
| 5 | Run-scoped inventory and manifest model | 276 scans/8.14 s historical; repeated consumers visible | Moderate, workload-dependent | Medium | Small to moderate | Medium freshness risk | Count touches first |
| 6 | Compact cold indexes/string/path ownership | 1M graph peak 3.18 GiB | High memory potential | High | Intended reduction | Medium | Object census first |
| 7 | Incremental immutable fragments | Long-lived CI target; no hit-rate data | Potentially very high on repeated runs | Very high | Persistent storage cost | Very high invalidation risk | Design/validate, do not cache yet |
| 8 | P/E-core affinity | No measurements | Unknown | High portability cost | Neutral | Low semantic/high operational | Defer |

Explicit non-targets:

- warm subject lookup and bounded context selection;
- Maven reactor traversal;
- global symbol indexing on the historical Maven sample;
- POM micro-optimization without a new measured regression;
- repository-specific shortcuts;
- unbounded persistent caching.

## Implementation recommendation

Implement **zero optimizations** in this investigation.

The next implementation should add non-semantic measurement only. After the complete
profile and worker matrix exist, select at most two candidates. Current evidence makes
snapshot transient memory/serialization and Java parsing the strongest likely
candidates; the run-scoped inventory may be safer if touch counts confirm it. The
choice must be made from the new profile, not this ranking.

An optimization is accepted only when:

- the baseline and candidate are comparable under the existing performance policy;
- improvement exceeds observed noise and is reproduced in a second batch;
- peak memory remains within the declared budget;
- every correctness hash, report, graph, snapshot, Explain projection, project order,
  and duplicate result is identical where the producer contract says it must be;
- Maven, Quarkus, Spring, Elasticsearch, and IntelliJ non-regression checks pass;
- the private enterprise run retains only source-free metrics and digests.

## Migration strategy and M2 candidate roadmap

This is a candidate engineering sequence, not a modification to the official roadmap
and not PR numbering.

### M2.0 — Measurement contract

- Extend the existing profiler concept to phase/counter samples.
- Add portable process CPU/RSS/I/O backends with explicit unsupported states.
- Add diagnostic file-touch and queue/worker ledgers.
- Measure recovery-on and recovery-off checkpoint amplification separately.
- Version the measurement manifest independently of semantic snapshots.

### M2.1 — Enterprise baseline

- Pin a private 47,000-file/4,000,000-line corpus without retaining source or paths.
- Add a public deterministic synthetic companion for harness validation.
- Capture cold/warm/startup/steady-state cohorts and the full 1–24 worker matrix.
- Establish memory budgets and current producer goldens.

### M2.2 — First optimization experiment

- First satisfy the Java parser-state correctness prerequisite if concurrency is in
  scope.
- Select one measured hotspot.
- Create an unchanged-output A/B benchmark.
- Implement the smallest generic change.
- Reproduce twice and retain only compact metrics.

### M2.3 — Second optimization experiment

- Proceed only if a second hotspot remains material after M2.2.
- Repeat the same decision and validation gates.

### M2.4 — Incremental correctness model

- Specify fragment keys, dependency lineage, invalidation, eviction, and corruption
  behavior.
- Prove byte-identical fresh and incremental results through adversarial tests.
- Introduce no persistent cache until that proof passes.

### M2.5 — Scale gates

- Validate 1M, 5M, and 10M semantic-object/graph projections with bounded queues.
- Validate Windows, Linux, macOS, AMD, containers, and constrained CI.
- Promote only portable scheduling policy; keep affinity diagnostic and optional.

## Expected enterprise scaling

No reliable 47,000-file/4,000,000-line prediction can be made from current evidence.
Using tracked-file counts alone, the historical Maven and Quarkus baselines would
extrapolate 47,000 files to roughly 110 and 520 seconds respectively. That fivefold
range proves that file count is not a sufficient cost model; language mix, LOC, symbol
density, project topology, graph density, and snapshot contents dominate.

M2 should fit a measured cost model using at least:

```text
files by language
lines/tokens
projects/modules/source scopes
symbols and members
graph nodes and edges by relation
evidence and finding counts
serialized section bytes
worker count and peak in-flight bytes
```

At 100 million lines, Atlas should not assume that one monolithic Python object graph
and one fully materialized JSON document will remain viable. That is an engineering
inference from current graph-memory and snapshot-size evidence, not authorization to
replace the canonical graph or snapshot format now.

## Five-year architecture recommendations

1. Preserve the current canonical KnowledgeGraph and specialized analyzer authority;
   scale them through immutable partitions rather than a competing graph.
2. Make every expensive artifact content-addressed by deterministic producer,
   configuration, scope, input, and dependency lineage.
3. Separate execution representation from stable interchange representation while
   retaining exact deterministic serialization and replay.
4. Use bounded immutable map/reduce fragments and coordinator-owned canonical merge.
5. Treat memory and in-flight bytes as scheduler resources alongside CPU workers.
6. Prefer run-scoped reuse before persistent caching.
7. Move to persistent incremental fragments only after formal fail-closed invalidation.
8. Keep the public scheduler portable; allow optional host-specific telemetry but no
   topology-specific semantic behavior.
9. Retain raw profiles as short-lived CI artifacts and commit only compact,
   source-free, comparable baselines.
10. Optimize deterministic end-to-end latency and bounded memory, not headline CPU
    utilization.

## Review outcome

- Production code changed: no.
- Roadmap changed: no.
- Benchmark or accepted golden changed: no.
- Profiling artifact committed: no.
- Optimization implemented: no.
- Tests run: none; this change is architecture documentation only.
- Repository source or benchmark source exposed: no.
