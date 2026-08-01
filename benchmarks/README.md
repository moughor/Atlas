# Atlas benchmark tooling

Atlas keeps algorithm-specific microbenchmarks in this directory and uses
`repository_benchmark` for comparable real-repository evidence. The runner is
repository-neutral: repository identity, expected counts, paths, and execution
parameters are inputs, never production discovery rules.

## Fresh analysis

Use a clean, pinned checkout and an explicit logical checkout identity:

```text
python -m benchmarks.repository_benchmark analyze C:\benchmarks\maven --repository-name "Apache Maven" --repository-commit <full-git-object-id> --checkout-identity maven-windows-stable-v1 --workers 1 --repeats 3 --output benchmarks/results/apache-maven.json
```

The timed scope is the `atlas analyze --force --no-recover --format json`
subprocess. Snapshot loading and hash collection occur after that timer. The runner
requires all projects to succeed and repeats the full analysis. It rejects semantic,
report, explanation, workspace-order, analysis-order, or analysis-report drift.

Both Atlas and the target repository must stay clean and at the same commits for the
whole capture. An expected repository commit is required for baseline eligibility.
If an extracted source archive has no Git metadata, `--allow-unpinned` permits a
clearly provisional record; it cannot become a golden baseline.

## Snapshot replay

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
