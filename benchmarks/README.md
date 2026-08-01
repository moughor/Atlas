# Atlas benchmark tooling

Atlas keeps algorithm-specific microbenchmarks in this directory and uses
`repository_benchmark` for comparable real-repository evidence. The runner is
repository-neutral: repository identity, expected counts, paths, and execution
parameters are inputs, never production discovery rules.

## Canonical M1.1 baseline

Pinned repository definitions live in `repositories.json`. List them, prepare a
new detached checkout, and verify its complete Git-tree provenance with:

```text
python -m benchmarks.canonical_baseline list
python -m benchmarks.canonical_baseline prepare apache-maven C:\benchmarks\apache-maven
python -m benchmarks.canonical_baseline verify apache-maven C:\benchmarks\apache-maven --require-initial-state
```

After the benchmark implementation is committed and Atlas is clean, capture a
schema-2 manifest and source-free golden bundle:

```text
python -m benchmarks.canonical_baseline capture apache-maven C:\benchmarks\apache-maven --atlas-commit <full-atlas-object-id> --repeats 3 --output benchmarks\results\apache-maven-fresh.json --golden-output benchmarks\results\apache-maven-golden
python -m benchmarks.canonical_baseline verify-golden benchmarks\results\apache-maven-golden --snapshot C:\benchmarks\apache-maven\.atlas\ass\latest.ass --require-snapshot
```

Run the same `prepare`, `verify`, `capture`, and `verify-golden` sequence with
repository ID `quarkus`, checkout root `C:\benchmarks\quarkus`, and Quarkus output
names. Both repository definitions are release-baseline inputs; Maven is not a
substitute for the Quarkus run.

The canonical command verifies the expected project count, origin URL, pinned
commit, detached/clean checkout, tracked content size, submodules, LFS declaration,
Atlas commit, and exact repeated output. Each sample starts without `ROOT/.atlas`.
It reuses `repository_benchmark` for analysis; it is not a second benchmark engine.

The complete schema, hash, golden, replay, and promotion contracts are in
`docs/stability/M1_1_CANONICAL_BASELINE.md`.

## Direct or provisional fresh analysis

Use a clean, pinned checkout and an explicit logical checkout identity:

```text
python -m benchmarks.repository_benchmark analyze C:\benchmarks\maven --repository-name "Apache Maven" --repository-commit <full-git-object-id> --checkout-identity maven-windows-stable-v1 --workers 1 --repeats 3 --output benchmarks/results/apache-maven.json
```

The timed scope is the `atlas analyze --force --no-recover --format json`
subprocess. Snapshot loading and hash collection occur after that timer. The runner
requires all projects to succeed and repeats the full analysis. It rejects semantic,
report, explanation, workspace-order, analysis-order, or analysis-report drift.

Both Atlas and the target repository must stay clean and at the same commits for the
whole capture. The direct command remains useful for diagnostics and provisional
runs. Schema-2 eligibility additionally requires the origin/ref, tracked tree,
installed-distribution versions, portable hashes, and complete ordering evidence.
Eligibility is evidence completeness, not proof that the canonical clean-state
wrapper ran; promotion separately requires the `canonical_baseline` preflight and
capture log. If an extracted source archive has no Git metadata,
`--allow-unpinned` permits a clearly provisional record; it cannot become a golden
baseline.

## Direct snapshot replay

Replay verifies persisted snapshot integrity and deterministic derived output. It
does not claim a new analysis:

```text
python -m benchmarks.repository_benchmark replay C:\benchmarks\quarkus\.atlas\ass\latest.ass --repository-root C:\benchmarks\quarkus --repository-name Quarkus --repository-commit <full-git-object-id> --checkout-identity quarkus-windows-stable-v1 --project-count 1442 --success-count 1442 --repeats 3 --source-manifest benchmarks/baselines/quarkus-fresh.json --output benchmarks/results/quarkus-replay.json
```

Project-success counts remain `declared-historical` unless `--source-manifest`
identifies an eligible fresh-analysis record with matching repository identity,
counts, and raw snapshot hash. This prevents replay from manufacturing analysis
success evidence.

## Comparison

```text
python -m benchmarks.repository_benchmark compare benchmarks/baselines/apache-maven.json benchmarks/results/apache-maven.json
```

The command exits `0` for `match`, `warning`, and an advisory
`performance-candidate`; `1` for deterministic correctness regression; and `2` for
incomparable records. It refuses to overwrite an output file unless
`--force-output` is explicit.

## Storage

- `benchmarks/baselines/` is reserved for compact reviewed records from pinned,
  baseline-eligible runs.
- `benchmarks/results/` is ignored local or CI output.
- Raw ASS files, analysis logs, checkout copies, and provider output are not tracked.
- One JSON file contains one schema-versioned manifest record.

Hash definitions, portability limits, performance thresholds, and update policy are
normative in:

- `docs/stability/BENCHMARK_STRATEGY.md`
- `docs/stability/SNAPSHOT_REGRESSION_STRATEGY.md`
- `docs/stability/PERFORMANCE_REGRESSION_STRATEGY.md`
- `docs/stability/CI_STRATEGY.md`
