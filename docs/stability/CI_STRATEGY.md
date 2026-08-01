# Atlas M1 CI Strategy

## Scope

This document defines a provider-neutral validation pipeline for the M1 stable
baseline. It does not install a GitHub Actions, GitLab CI, or Azure Pipelines file.
The repository currently has no checked-in CI workflow, and choosing a hosting
provider is outside M1.

Atlas already provides `CiTemplateService` and `atlas ci` for consumers who want to
run Atlas against their own repositories. Those generated SARIF workflows are a
public product capability; they are not a substitute for Atlas's own build, test,
snapshot, and benchmark validation.

## Principles

- All required validation commands are runnable locally and by any CI provider.
- Deterministic correctness failures block before performance comparison.
- Large external repositories are pinned by commit and never discovered by a
  hardcoded product special case.
- Fresh analysis and snapshot replay are reported separately.
- Provider-generated LLM prose is never a regression artifact.
- Raw benchmark data remains an artifact; only compact reviewed baselines are tracked.
- Expensive or machine-sensitive work runs on an appropriate stable runner rather
  than making ordinary unit-test jobs flaky.

## Recommended stages

### 1. Source and packaging hygiene

Run fast checks that do not require a repository benchmark:

```text
git diff --check
python -m compileall -q moughorai benchmarks
```

Validate package metadata and imports using existing tests. M1 must not invent a
formatting or linting gate because `pyproject.toml` currently declares no formatter
or linter. Such a gate requires a separately reviewed tool and configuration.

### 2. Unit and integration tests

Run the complete supported suite:

```text
python -m pytest -q
```

The job records the exact pass, failure, error, skip, Python, OS, and Atlas commit
values. A skipped test is reported with its reason. No result is described as passed
unless this command actually completes successfully.

### 3. Determinism and compatibility regression

Run focused tests covering:

- canonical JSON and exact serialization round trips;
- KnowledgeGraph ordering and digest stability;
- repository summary and repository report ordering;
- risk-analysis and structured-explanation hashes;
- snapshot checksum, schema, and backward-compatible loading;
- bounded selection and exact omitted counts.

This stage uses small fixtures and belongs on every proposed change. It fails on any
unexpected deterministic drift.

### 4. Benchmark smoke validation

Execute bounded synthetic forms of the tracked benchmark programs. Validate their
schema, workload completeness, result hashes, and deterministic repeated output.
Timing is recorded but not gated in this job.

M1 adds a small direct smoke test that imports and executes the bounded PR134
synthetic benchmark twice. Million-node and large-repository runs remain outside
pytest.

### 5. Snapshot regression

Validate checksum and snapshot-ID round trips against versioned fixtures. Exact raw
snapshot equality is required only under the controlled root and initial-state
conditions documented in `BENCHMARK_STRATEGY.md`. Cross-host jobs compare portable,
defined section hashes and explicitly report raw snapshot equality as incomparable
when those conditions are not met.

### 6. Apache Maven fresh analysis

On a pinned benchmark runner:

1. verify the Maven repository commit;
2. run a clean `--force --no-recover --format json` analysis;
3. require 92 discovered projects, 92 successes, and zero failures for the currently
   accepted repository revision;
4. verify and hash the published snapshot, repository report, and provider-free
   explanation;
5. emit a canonical benchmark record.

Use the provider-neutral command described in `benchmarks/README.md`. A record is
eligible as a baseline only when the expected repository commit and a logical
checkout identity were supplied, at least three samples were captured, and the
repository and Atlas worktrees remained clean and unchanged throughout the run.

The expected count belongs to the pinned baseline record, not production discovery
code. A repository revision change requires an explicit reviewed baseline update.

### 7. Quarkus replay

Replay the checksum-verified snapshot for the pinned Quarkus revision and require the
currently accepted 1,442-project metadata and deterministic report/explanation
hashes. Label this stage `snapshot-replay`; do not claim a fresh Quarkus analysis.
Project-success counts are verified only when the replay links a matching eligible
fresh-analysis manifest; otherwise they remain declared historical observations and
the replay record is not baseline-eligible.

A fresh Quarkus analysis may run as a scheduled or release job when the checkout and
runtime budget are available, but replay remains a separate result.

### 8. Performance comparison

Compare results only with a compatible stable-runner baseline using
`PERFORMANCE_REGRESSION_STRATEGY.md`. Correctness and hash drift block immediately.
Timing warnings are advisory during initial history collection; a blocking
performance regression requires the documented independent reproduction.

### 9. Documentation validation

Check that documented commands, local links, benchmark names, expected counts, and
authoritative test totals agree with current validated records. The M1 baseline
records 3,681 passed and one skipped after the complete post-hardening suite.

Do not add a new documentation checker until a concrete implementation and ownership
are selected. Simple deterministic link and command checks are sufficient for M1.

## Trigger and runner guidance

- Stages 1–4 run for every proposed change.
- Stage 5 runs for changes affecting snapshots, serialization, semantic context, or
  public models, and on release candidates.
- Maven fresh analysis and Quarkus replay run before a stable release and on relevant
  semantic/discovery changes; scheduled runs provide additional confidence.
- Performance comparison runs only on a stable, labeled runner with a compatible
  baseline.

External repository jobs must check out the requested Atlas commit before invoking
the runner. The runner records that exact HEAD and rejects any Atlas change or dirty
state during capture. It also fails fast when the target repository commit, worker
count, or benchmark mode differs from the requested configuration. Network checkout
is separate from measurement and excluded from analysis duration.

## Artifacts and reporting

Each stage publishes its exact command and result. Repository benchmark jobs retain:

- canonical manifest record and comparison result;
- raw analysis JSON;
- verified ASS artifact when storage permits;
- provider-free explanation output;
- stderr and diagnostic logs;
- environment identity.

Artifacts have bounded, access-controlled retention and must not expose credentials
or provider conversations. ASS files, raw reports, and logs may contain workspace
paths and therefore are restricted CI/release artifacts, not source-safe tracked
files. The tracked baseline contains only compact metadata, non-sensitive logical
checkout identity, and hashes; it never contains absolute user paths or source.

## Failure policy

- Compilation, test, checksum, schema, project-success, or deterministic-hash drift
  blocks immediately.
- An unavailable external fixture yields `not-run` with an exact reason, never a
  fabricated pass.
- An environment mismatch yields `incomparable`, never a performance pass.
- A timing warning does not weaken correctness gates.
- Baseline files are never updated automatically in response to a failure.

The manifest comparator exits `1` for deterministic regression and `2` for
incomparable inputs. Timing warnings and a first `performance-candidate` remain
advisory and exit `0`; independent reproduction is required before a performance
block.

Provider-specific CI configuration may be added later only after these commands and
artifact contracts are stable. M1 requires the strategy and reusable tooling, not a
GitHub Actions workflow.
