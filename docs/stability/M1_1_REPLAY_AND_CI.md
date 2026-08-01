# Atlas M1.1 Replay and CI Policy

## Purpose

This document defines the provider-neutral validation and release-gate procedure for
the M1.1 stable baseline. It operationalizes the existing M1 benchmark, snapshot,
performance, and CI strategies; it does not introduce a roadmap feature, a cloud
service, or a provider-specific workflow.

The reusable implementation remains:

- `benchmarks.canonical_baseline` and `benchmarks/repositories.json` for pinned
  checkout preparation, definition verification, capture orchestration, and golden
  publication;
- `benchmarks.repository_benchmark` for fresh analysis, snapshot replay, and manifest
  comparison;
- `benchmarks.stability_manifest` for strict records, artifact hashes, eligibility,
  and performance classification;
- the compatibility fixtures and focused regression tests described in
  `SNAPSHOT_REGRESSION_STRATEGY.md`;
- the validation stages described in `CI_STRATEGY.md`.

This policy contains no benchmark-result claim. A validation is reported as passed
only after its exact command has completed successfully. An analysis that was not
executed is `not-run`, with its reason recorded.

## Authority and invariants

The following documents remain normative and are applied together:

1. `BENCHMARK_STRATEGY.md` defines manifest provenance and hash semantics.
2. `SNAPSHOT_REGRESSION_STRATEGY.md` defines snapshot compatibility and portability.
3. `PERFORMANCE_REGRESSION_STRATEGY.md` defines comparable timing and default
   thresholds.
4. `CI_STRATEGY.md` defines provider-neutral stages and failure policy.

M1.1 does not weaken these invariants:

- Atlas and benchmark repositories are immutable, clean Git checkouts at explicit
  full object IDs.
- Correctness and deterministic-output drift are evaluated before timing.
- Fresh analysis and snapshot replay are distinct evidence classes.
- Replay does not manufacture analysis-success evidence.
- A large snapshot, raw report, log, or provider conversation is not committed.
- Baselines are never rewritten automatically to make a candidate pass.
- Repository-specific expected counts belong to reviewed benchmark inputs and
  manifests, never Atlas discovery code.

## Required release inputs

Before preparing a release candidate, the release owner records:

- Atlas repository URL and exact candidate commit;
- Atlas package version and intended tag;
- benchmark repository URL, exact commit, and display name;
- a stable logical checkout identity;
- a fixed physical checkout root for path-scoped semantic hashes;
- expected project and success counts for the selected repository revision;
- Python implementation and major/minor version;
- operating system, release, architecture, worker count, and cache mode;
- benchmark mode, repeat count, timeout, and measurement scope;
- the accepted performance-tolerance profile;
- artifact retention location and retention period.

Missing inputs are not inferred from a branch name, archive filename, package name,
or prior conversation. A downloaded branch archive is not a pinned checkout.

## Fresh-clone procedure

Use new, empty directories at the fixed release-runner roots. Do not reuse a developer
worktree for a golden capture. The canonical preparer fetches the complete declared
branch history and checks out the exact commit with a complete working tree; shallow,
sparse, and blob-omitting partial checkouts are not permitted. This is required because
Git-backed risk evidence consumes repository history. The pinned commit must be
reachable from the declared branch, and a declared tag must resolve exactly to that
commit. Network checkout and dependency installation occur before measurement.

```text
git clone <atlas-repository-url> <fixed-atlas-root>
git -C <fixed-atlas-root> checkout --detach <atlas-commit>

python -m benchmarks.canonical_baseline prepare <repository-id> <fixed-benchmark-root>
python -m benchmarks.canonical_baseline verify <repository-id> <fixed-benchmark-root> --require-initial-state
```

If the selected repository uses submodules, initialize them recursively and verify
their recorded commits before capture. The release record states whether submodules
or Git LFS are applicable. Missing submodule content makes the checkout invalid.
The current Maven and Quarkus definitions declare no LFS content. Before admitting a
future LFS-backed corpus, its promotion procedure must additionally verify all LFS
objects and working-tree materialization; the declaration check alone is insufficient.

Create a dedicated Python environment from the selected Atlas commit. Record the
interpreter identity and installed-distribution inventory as restricted build
artifacts. Reuse the same environment for baseline and candidate timing comparison;
changing dependencies creates a new environment cohort.

The benchmark checkout must have no pre-existing `.atlas` state before capture. The
canonical runner removes only the validated benchmark-root `.atlas` directory before
every repetition, so all samples have the same clean initial state. Physical root and
checkout identity must remain the same for every performance-comparable batch; the
portable semantic projection is used for cross-root correctness comparison.
Repositories that track `.atlas`, including an index entry hidden by ignore rules, are
invalid benchmark inputs. A dangling `.atlas` symlink is pre-existing state and is
rejected rather than followed or removed.

## Pinned-checkout verification

Immediately before capture, verify both repositories:

```text
git -C <atlas-root> rev-parse --show-toplevel
git -C <atlas-root> rev-parse --verify HEAD
git -C <atlas-root> status --porcelain=v1 --untracked-files=all

git -C <benchmark-root> rev-parse --show-toplevel
git -C <benchmark-root> rev-parse --verify HEAD
git -C <benchmark-root> status --porcelain=v1 --untracked-files=all
```

The resolved top-level paths and object IDs must exactly match the recorded inputs,
and both status commands must produce no output. Because ordinary Git status omits
ignored build products, the new-clone requirement is part of verification; a clean
status alone is insufficient evidence for a golden capture.

The benchmark runner independently verifies the repository commit, Git top level,
and worktree state and rejects a changed Atlas or target checkout during capture.
Pass the full target commit and checkout identity explicitly:

```text
python -m benchmarks.canonical_baseline capture <repository-id> <benchmark-root> --atlas-commit <atlas-commit> --repeats 3 --output benchmarks/results/<repository>-candidate.json --golden-output benchmarks/results/<repository>-golden
```

The command's manifest must report the chosen Atlas commit, verified target commit,
expected project count, all projects successful, and `baseline_eligible: true`. The
canonical command enforces the expected count from `benchmarks/repositories.json`;
under-discovery cannot be promoted as a first baseline merely because all discovered
projects succeeded.

`--allow-unpinned` is permitted only for investigation. Its output is provisional,
incomparable, and cannot satisfy a release gate or become a golden baseline.

## Fresh-analysis and replay policy

A fresh-analysis record proves that the normal production analysis path ran for the
selected revision. It must contain at least three samples, verified success for every
discovered project, an analysis-report hash, analysis-order hash, semantic hashes,
and the published snapshot identity.

A replay record proves only that one existing ASS artifact can be checksum-validated
and can reproduce its deterministic derived output:

```text
python -m benchmarks.canonical_baseline replay <repository-id> <benchmark-root> <snapshot.ass> --atlas-commit <atlas-commit> --repeats 3 --source-manifest benchmarks/baselines/<repository>-fresh.json --output benchmarks/results/<repository>-replay-candidate.json
```

Replay success and failure counts are verified only when `--source-manifest` names an
eligible fresh-analysis manifest with matching repository name, commit, checkout
identity, project counts, and raw snapshot hash. Without that link, the replay is
reported as `not-run` for analysis-success validation, even if its artifact replay
itself completed. It must not replace a required fresh-analysis release stage.

If a required external checkout or snapshot is unavailable, record:

- status: `not-run`;
- the missing input or failed precondition;
- the exact stage that was skipped;
- whether the release gate is consequently blocked.

Do not convert an unavailable analysis into a pass, a zero-project result, or an
unverified historical success claim.

## Golden artifacts and retention

Only a reviewed, baseline-eligible, compact canonical manifest is committed under
`benchmarks/baselines/`. The tracked filename identifies the repository and evidence
mode; one JSON file contains one schema-versioned record. Git history provides the
approval and change audit.

The following remain restricted CI or release artifacts outside source control:

- raw analysis JSON and diagnostics;
- the checksum-verified ASS artifact;
- provider-free explanation output used by the recorded hash;
- comparison reports and individual timing samples;
- stderr and execution logs;
- detailed interpreter and environment exports beyond the compact interpreter and
  installed-distribution identities embedded in the manifest;
- checkout paths and any artifact containing local workspace paths.

Retain the evidence needed to reproduce and investigate a golden for at least as
long as that golden is accepted. Before expiring a raw artifact, retain its checksum,
manifest lineage, and the documented reason that replay is no longer available.
Artifact storage must be access-controlled and must not retain credentials, provider
prompts, or provider conversations.

Pinned object IDs do not guarantee that an upstream host will still serve the
objects two years later. Long-term corpus retention remains operational technical
debt: release engineering should keep an access-controlled bare mirror or verified
Git bundle for every accepted pin, record its checksum, and periodically test
restoration. Those repository objects remain external artifacts and are never
committed into Atlas itself.

A new golden is promoted only after:

1. checkout and environment preconditions pass;
2. the manifest is baseline-eligible;
3. repository counts match the reviewed revision inputs;
4. deterministic hashes reproduce across the required samples;
5. the candidate is compared with the prior compatible golden when one exists;
6. every semantic or size change is explained and reviewed;
7. the baseline change and release note are committed together.

The initial golden has no prior performance comparison. It establishes provenance
and correctness history but does not by itself establish a performance distribution.

## Regression comparison

Use the existing comparator only for eligible, compatible manifests:

```text
python -m benchmarks.repository_benchmark compare benchmarks/baselines/<repository>.json benchmarks/results/<repository>-candidate.json --output benchmarks/results/<repository>-comparison.json
```

Interpret the result semantically, not only by process exit code:

- `match`: deterministic evidence matches and timing is within tolerance;
- `warning`: correctness matches, but raw-only, size, or advisory timing review is
  required;
- `performance-candidate`: correctness matches, but a second independent batch on
  the same stable runner is mandatory;
- `regression`: deterministic counts or comparable correctness hashes changed;
- `incomparable`: provenance, workload, eligibility, or environment does not match.

The CLI exits `0` for `match`, `warning`, and the first advisory
`performance-candidate`, `1` for `regression`, and `2` for `incomparable`. Release
automation must therefore inspect the comparison status and unresolved warnings; an
exit code of zero alone is not release approval.

Correctness regression blocks immediately. `incomparable` does not become a pass by
waiver or baseline replacement. Raw ASS drift with stable semantic evidence is an
operational warning because capture history participates in ASS identity. Any other
semantic, report, explanation, ordering, count, or unexplained size drift requires
review before a baseline change.

## Configurable performance tolerance

The default `compare_manifests()` tolerance is:

- warning when the candidate is more than 15 percent and at least 500 milliseconds
  slower;
- performance candidate when it is more than 30 percent and at least 1,000
  milliseconds slower.

The comparison API accepts explicit `warning_percent`, `warning_absolute_ms`,
`candidate_percent`, and `candidate_absolute_ms` values. A provider-neutral wrapper
may supply different values only when the benchmark's tracked policy declares them
before candidate results are observed. Candidate thresholds must not be below the
warning thresholds. The comparison report records the samples and observed change;
the release record must additionally identify the tolerance profile used.

Tolerance configuration follows these rules:

- correctness hashes and counts are never tolerance-configurable;
- baseline and candidate use the same threshold profile;
- thresholds are not relaxed after seeing a candidate;
- short microbenchmarks may use a smaller absolute threshold only when justified by
  stable-runner history and documented before use;
- a performance candidate becomes release-blocking only after an independent second
  batch reproduces it on the same stable runner;
- until eligible history demonstrates normal spread, timing remains advisory and is
  not described as a pass/fail performance guarantee.

## Provider-neutral CI stages

### Stage 1: source and package hygiene

Run `git diff --check` and `python -m compileall -q moughorai benchmarks`. Verify
package metadata and version-source consistency. Any failure blocks later stages.

### Stage 2: complete tests

Run `python -m pytest -q` and retain the exact pass, failure, error, and skip counts.
Skipped tests remain skipped; they are never included in a passed count.

### Stage 3: deterministic compatibility

Run the focused canonical serialization, public API, ASS fixture, graph, report,
explanation, and bounded-selection regressions. Unexpected hash, order, round-trip,
or omitted-count drift blocks.

### Stage 4: benchmark smoke

Run bounded synthetic benchmark smoke contracts. Validate their schema and stable
correctness fields. Timing is recorded but not gated in this stage.

### Stage 5: external repository capture

On a stable labeled runner, execute the required pinned fresh analyses and replays.
Keep checkout, installation, and network time outside the declared measurement
scope. A missing repository, snapshot, or runner produces `not-run` with an exact
reason.

### Stage 6: baseline comparison

Compare each eligible candidate with its compatible golden. Correctness regression
or incomparability blocks. Review warnings, and reproduce a performance candidate in
a second independent batch.

### Stage 7: release readiness

Verify that the exact validated Atlas commit, package version, changelog entry, and
intended tag agree. Confirm artifact retention, unresolved warnings, `not-run`
stages, and approved baseline changes. No tag or release recommendation is emitted
automatically by the benchmark runner.

Stages 1 through 4 run for every proposed change. Snapshot-sensitive changes add the
snapshot regression stage. External fresh analysis, replay, comparison, and release
readiness run before a stable release and on relevant semantic or discovery changes.
The procedure is identical whether invoked locally or by a future CI provider.

## Release-gate decision

The release record lists every required stage with exactly one status:

- `passed`;
- `failed`;
- `not-run`;
- `incomparable`;
- `warning`;
- `performance-candidate`.

A stable release requires all correctness stages to be `passed`, every required
external analysis to have eligible evidence, every comparison to be comparable, and
all warnings to have a recorded disposition. A reproduced performance candidate,
deterministic regression, incompatible input, failed project, missing required fresh
analysis, or required `not-run` stage blocks release.

An unreproduced first performance candidate remains advisory but cannot be silently
discarded; its second-batch result and disposition are part of the release record.
Optional exploratory analyses may remain `not-run`, provided they are explicitly
outside the declared release gate. Their absence must not be used to make a positive
claim about unsupported repositories or capabilities.

Baseline promotion, tag creation, and push are separate reviewed actions. Neither
successful replay nor a zero exit code authorizes them by itself.
