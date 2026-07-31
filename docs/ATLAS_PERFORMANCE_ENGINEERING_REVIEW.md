# Atlas Performance Engineering Review

## Executive summary

Apache Maven remains fully analyzable: Atlas discovers 92 projects and all 92
succeed. The review found one measurable, low-risk filesystem hot path and two
smaller repeated path-resolution costs. The changes preserve matching,
ordering, snapshot, and public API behavior.

A direct comparison in detached worktrees decreased mean benchmark time from
48.77 seconds at `992a806` to 33.91 seconds for the consolidated worktree, an
improvement of approximately 30.5%. cProfile time in the earlier investigation
decreased from 88.89 to 65.87 seconds (profiled function time, approximately
25.9%). Profiling adds substantial overhead, so normal and profiled timings must
not be compared to one another.

## Method and limits

- Repository: an Apache Maven source archive. The archive contains no `.git`
  metadata, so its exact upstream revision cannot be recovered; future benchmark
  captures must record a pinned revision.
- Environment: Windows 11 build 26200, CPython 3.12.10, one worker, forced
  analysis, and recovery disabled.
- Command from the Maven repository root:
  `python -m moughorai.atlas_cli analyze . --force --no-recover`.
- Baseline: detached Atlas worktree at `992a806`; two unprofiled runs.
- Candidate: consolidated Atlas worktree; two unprofiled runs after the full
  test suite. Earlier cProfile runs were evaluated separately.
- cProfile cumulative times overlap: a parent service includes its child
  services and must not be added to them.
- Repository explanation measurements cover deterministic snapshot loading,
  context selection, and prompt construction. External LLM latency was not
  measured because it is provider- and network-dependent.
- No permanent timing instrumentation was added.

## Approximate performance breakdown

The following values come from the optimized cProfile run unless noted.

| Subsystem | Approximate cumulative time | Observation |
| --- | ---: | --- |
| Workspace discovery | 0.83 s | Includes project detection and nested-project exclusions. |
| Maven reactor discovery | 0.07 s | Recursive reactor traversal is not a hotspot. |
| Maven POM model parsing | 0.56 s | 2,070 parses across discovery and inventory/framework consumers. |
| Filesystem traversal and matching | 8.14 s | 276 project scans; overlaps analysis, summary, and fingerprinting. |
| Java parsing | 35.21 s | 2,791 compilation units; lexer/tokenization dominates. |
| Java/global symbol indexing | about 0.35 s | Java index build 0.09 s; global symbol build about 0.27 s. |
| Dependency intelligence | 0.43 s | Maven extraction accounts for about 0.39 s. |
| AI semantic-context collection | 21.86 s | Includes repository summary, graph, architecture, patterns, and reachability. |
| AI context model construction | 5.98 s | Symbol projection is the majority of this cost. |
| Repository summary | 11.26 s | Includes its filesystem scans; path memoization was applied afterward. |
| Snapshot capture | 4.53 s | Includes workspace fingerprinting. |
| Snapshot serialization/save | 2.43 s | Canonical serialization of a 30.78 MB snapshot. |
| Repository explanation context | about 1.0 ms | Source-free compact context projection only. |
| Repository explanation prompt | about 0.66 ms | 176,558 characters / estimated 44,140 input tokens. |
| CLI report generation | about 1 ms | Not a hotspot. |

## Top performance hotspots

1. Java lexing and parsing: 35.21 seconds cumulative.
2. Repeated project filesystem scans: 8.14 seconds after optimization.
3. AI context symbol projection: 4.60 seconds within a 5.98-second build.
4. Workspace fingerprint reads and hashing: 4.44 seconds.
5. Snapshot canonical serialization and save: 2.43 seconds.
6. Repository module hierarchy construction: 1.97 seconds in the measured
   profile before its final local path memoization.
7. Architecture detection: 1.62 seconds.
8. Reachability analysis: 1.52 seconds.
9. Design-pattern analysis: 0.68 seconds.
10. Maven POM parsing and dependency extraction: approximately 0.95 seconds
    combined, with overlapping XML work.

## Optimizations implemented

### Literal subtree pruning

`project_files()` now prevents `os.walk()` from entering directories excluded
by literal `path/**/*` patterns. Wildcard-containing directory prefixes keep
their existing general matching path. This avoids discovering files that must
later be rejected.

### Fast paths for common patterns

Patterns are normalized and classified once per project scan. The universal
`**/*` include is accepted without `Path.match()`. Literal subtree exclusions
use an exact prefix check and do not fall through to the general matcher when
that prefix does not match. Patterns containing wildcard directory components
retain the existing `Path.match()` path. Under cProfile, `_matches` decreased
from 15.41 to 0.56 seconds and `project_files()` decreased from 30.10 to 8.14
cumulative seconds.

### Local resolved-path reuse

Workspace nested-project exclusion and repository-summary hierarchy/path
selection now resolve each project or file once within the operation instead of
repeating canonicalization inside quadratic loops. No result is cached across
runs, so filesystem freshness semantics are unchanged.

## Optimizations considered but rejected

- A persistent `project_files()` cache was rejected because analysis,
  fingerprinting, and snapshot capture have distinct freshness boundaries.
- Cross-service POM caching was rejected: XML work is below one second, while a
  correct cache would need explicit invalidation and shared model semantics.
- A `deque` for the Maven discovery queue was measured earlier and did not
  improve this 92-project workload reliably.
- A Java source-root filtering rewrite that resolved every input path eagerly
  was measured and showed no repeatable improvement.
- Java lexer micro-optimizations were rejected without dedicated lexer
  benchmarks; this is the largest hotspot but also a high-correctness-risk area.
- Parallel Java or POM analysis was not implemented. Project execution already
  supports concurrency, and adding nested parallelism requires memory, error
  isolation, and deterministic scheduling measurements first.
- Snapshot compression or schema changes were rejected because they affect
  persistence compatibility and require a separate design and benchmark.

## Runtime and memory observations

- Direct baseline runs at `992a806`: 49.006 and 48.526 seconds; mean 48.766.
- Direct consolidated runs: 33.996 and 33.832 seconds; mean 33.914.
- Comparable mean improvement: approximately 30.5%.
- Earlier exploratory consolidated runs ranged from 23.38 to 26.54 seconds, but
  they are not used for the speedup claim because filesystem and machine state
  were not controlled against a same-session baseline.
- Alternating file-enumeration measurements returned the same 10,005 paths and
  digest while decreasing from 4.12-5.49 seconds to 1.71 seconds.
- Alternating repository-summary measurements retained the same digest while
  decreasing from 5.76-6.24 seconds to 4.62-4.78 seconds.
- Nested-project exclusion retained the same digest while decreasing from
  1.11-2.07 seconds to 0.14-0.21 seconds in a focused repeated-operation test.
- Optimized cProfile function time: 65.87 seconds versus 88.89 seconds.
- `latest.ass` size: 30,783,110 bytes.
- Loading and checksum-validating the snapshot took 1.43-1.48 seconds and
  reached 157,682,485 bytes peak traced allocation.
- The semantic graph JSON section is approximately 8.91 MB; dependency data is
  approximately 0.38 MB and repository summary data approximately 0.07 MB.
- Immutable semantic structures are appropriate for deterministic snapshots,
  but serialization temporarily duplicates large Python and JSON structures.

## Remaining opportunities

1. Add stable phase timers to the existing metrics/events infrastructure so
   future benchmarks do not require cProfile.
2. Benchmark Java lexer changes independently before modifying the parser.
3. Introduce a run-scoped file inventory only if freshness boundaries are made
   explicit for analyzer, summary, cache, and snapshot consumers.
4. Investigate streaming/checksummed snapshot serialization while preserving
   the existing format and exact canonical output.
5. Add process peak-RSS and snapshot-section sizes to benchmark history.
6. Track median, spread, commit, Python version, OS, and cold/warm filesystem
   state for Maven, JUnit, Spring Framework, Gradle, Elasticsearch, Quarkus,
   Micronaut, and OpenRewrite.
7. Evaluate bounded module-level parallelism only with deterministic output,
   memory ceilings, and isolated-failure tests.
8. Apply token-budgeted repository-summary selection when its owning roadmap PR
   introduces that shared capability; the current deterministic prompt is
   approximately 44,140 estimated tokens.

## Determinism validation

Repeated runs produced identical values:

- Project order SHA-256:
  `b8b7fa40d5ac6dadf466083572ebb56b747725d9d903baec84008249fe2289f3`
- Workspace SHA-256:
  `3317bdbcbcd18522e3428894be6aed5db5463553bfd7c47005385af009d66d21`
- Repository summary SHA-256:
  `570046baae4eb03868b0cb1300fe08ce54b0a1a4b5507d4dec762dd57be687ae`
- Semantic graph SHA-256:
  `940e5cee7f604866805d5132a05650e61a153ecd7ff1920e2db184847382f3a3`
- Dependencies SHA-256:
  `440b48e63034101dda2d19e7eb0b18e94024c0c7cea4857de3ca23278eccfb68`
- Module hierarchy SHA-256:
  `cec330c2effd7a847cea5c8f11e4d38d307a7454417a14cc43af17c755d062f7`
- Repository prompt SHA-256:
  `500488dcc3e1d5bdb154f30b7701be6e37e5fad4e44ac7ac3512d62f708abf6d`
- Structured explanation context SHA-256:
  `1aa306a036233a6426cded7cb1c63d491d38d2d3617743f65c116910f7c39c94`

Project order, dependency ordering, module hierarchy, repository summary, graph,
and source-free repository explanation context therefore remained stable.

## Validation results

- Focused workspace, matching, dependency, and repository tests: 87 passed in
  0.87 seconds.
- Complete final suite: 3,493 passed, 1 skipped in 10.41 seconds.
- Final Maven runs: 92 projects, 92 succeeded, zero failures, exit code zero,
  in 33.996 and 33.832 seconds.

One earlier direct full-suite attempt was terminated by the command harness
before completion and produced no valid test result. The complete suite result
above is from the subsequent captured run against the final code state.

## Files modified by this performance review

- `moughorai/workspace/files.py`
- `moughorai/workspace/discovery.py`
- `moughorai/repository_summary/service.py`
- `tests/test_pr123_project_scoped_java_identity.py`
- `docs/ATLAS_PERFORMANCE_ENGINEERING_REVIEW.md`

Other modified documentation, workspace validation, and tests already present
in the working tree belong to the preceding Maven hardening review. The
untracked `benchmarks/Maven/` directory was not modified. No commit or push was
performed.
