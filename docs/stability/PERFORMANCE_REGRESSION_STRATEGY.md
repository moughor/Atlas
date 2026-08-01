# Atlas M1 Performance Regression Strategy

## Purpose

Performance validation detects material regressions without turning machine noise
into flaky correctness failures. It does not add telemetry, caches, or production
instrumentation. Existing deterministic outputs remain the primary acceptance gate;
performance results are compared only when their workloads and environments are
compatible.

## Comparable measurements

Two measurements are comparable only when all of the following match:

- benchmark identifier and benchmark mode;
- exact repository commit;
- workload parameters and measurement scope;
- Python major/minor version and implementation;
- operating system, OS release, and architecture;
- worker count and cache mode;
- sample count and logical checkout identity;
- cold, warm, replay, or fresh-analysis measurement scope.

The Atlas commit is intentionally different when evaluating a proposed change. Atlas
package-version changes are recorded and reviewed. If any other identity differs,
the comparator returns `incomparable` rather than a pass or failure.

## Sampling

- Use one unrecorded warm-up before component microbenchmarks.
- Record five samples for bounded component benchmarks.
- Three samples are acceptable for expensive fresh Maven or Quarkus analyses.
- Use the median as the regression metric.
- Record individual samples so reviewers can see spread and outliers.
- Treat current five-sample nearest-rank p95 values as the slowest observation and
  diagnostic information only. They are not a CI gate.

Setup, repository checkout, snapshot loading, graph construction, analysis, replay,
serialization, and selection timings must not be combined unless the benchmark
explicitly declares an end-to-end scope. Every result names excluded work.

## Baseline and comparison

The accepted baseline is a compact canonical JSON record in Git. A comparison
reports:

- baseline and candidate medians;
- absolute delta in milliseconds;
- ratio and percentage delta;
- individual samples;
- environment and workload comparability;
- deterministic count/hash status;
- final status: `match`, `warning`, `performance-candidate`, `regression`, or
  `incomparable`.

Correctness drift is evaluated before timing. A project-count, success-count, or
comparable deterministic-hash mismatch is a correctness failure, not a performance
regression.

## Thresholds

For analysis-duration medians:

- `match`: the candidate does not exceed both warning limits;
- `warning`: the candidate is more than 15 percent slower **and** at least 500 ms
  slower;
- `performance-candidate`: the candidate is more than 30 percent slower **and** at
  least 1,000 ms slower;
- `regression`: deterministic correctness evidence differs, independently of timing.

A single `performance-candidate` is not sufficient to block a change. Reproduce it in a
second independent batch on the same stable runner before treating it as a
performance failure. During the first M1 baseline-collection period, timing gates
remain advisory until the runner has enough history to demonstrate normal spread.

Microbenchmarks whose expected duration is below the absolute noise floor may define
a smaller benchmark-specific absolute threshold, but it must be documented in the
tracked baseline before use. Thresholds must not be adjusted after observing a
candidate merely to make it pass.

## Size and memory observations

Snapshot and derived-payload byte sizes are deterministic for a comparable artifact
and should be reported exactly. Unexpected size drift is reviewed as a serialization
or scope change; it is not averaged like timing.

Memory measurements remain diagnostic unless the method is identical:

- `tracemalloc` reports Python allocations, not process RSS;
- process peak RSS is platform-specific and cumulative over process lifetime;
- measurements taken after loading a 300 MB snapshot cannot be compared with isolated
  component allocations.

The measurement method and included lifetime must accompany every memory value. M1
does not introduce a memory failure threshold without stable-runner history.

## History and retention

Git stores accepted compact baselines and explains intentional changes. Raw samples,
logs, snapshots, and comparison reports are retained as ignored local results or CI
artifacts according to the CI retention policy. No external database or complex
telemetry service is required.

An accepted baseline update requires:

1. a successful deterministic comparison;
2. a compatible and pinned environment;
3. reproduced timing samples;
4. review of any size or performance change;
5. a commit message or release note explaining the update.

Performance improvement is recorded when useful, but does not permit deterministic
output drift or weaker validation.
