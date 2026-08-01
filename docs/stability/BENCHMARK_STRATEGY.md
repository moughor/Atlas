# Atlas M1 Benchmark Strategy

> M1.1 note: `M1_1_CANONICAL_BASELINE.md` is normative for new schema-2
> repository baselines, portable hashes, pinned definitions, and clean-state
> captures. This document retains the schema-1 M1 contract for backward
> compatibility and historical interpretation.

## Status and scope

This document defines the benchmark discipline for the M1 platform-stabilization
baseline. It does not add a roadmap feature, change Atlas analysis semantics, or
authorize repository-specific behavior. Benchmark tooling must exercise existing
production paths and keep repository identity, measurement, and deterministic
output validation separate.

The current benchmark programs remain useful for their original scopes:

- `benchmark_semantic_tables.py` compares the PR101 bulk-builder path with the
  compatibility update path.
- `benchmark_large_workspace.py` measures deterministic synthetic indexing and
  workspace fingerprinting. It is not a full `atlas analyze` benchmark.
- `benchmark_pr132_risk_hotspots.py` measures synthetic PR132 graph shapes.
- `benchmark_pr132_snapshot_replay.py` replays risk analysis from an ASS artifact.
- `benchmark_pr133_repository_report.py` measures deterministic repository-report
  construction and bounded context selection.
- `benchmark_pr134_explain_anything.py` measures indexed subject resolution and
  bounded structured-explanation selection.

These feature benchmarks do not replace a common real-repository benchmark. M1
requires a repository-neutral runner that records one strict, versioned manifest
record for Apache Maven, Quarkus, and future pinned repositories.

## Benchmark classes

Atlas uses three benchmark classes with different acceptance semantics.

1. **Synthetic microbenchmarks** isolate a bounded algorithm or data structure.
   They validate workload completeness and deterministic result hashes. Timing is
   useful for diagnosis but is not portable between hosts.
2. **Snapshot replays** consume a checksum-verified ASS artifact and exclude fresh
   repository discovery and analysis. They validate serialization, deterministic
   derived analyses, and interactive query performance.
3. **Fresh repository analyses** run `atlas analyze ROOT --force --no-recover
   --format json` against a clean checkout at an exact repository commit. They
   validate discovery, analysis, snapshot publication, repository reports, and
   deterministic default explanations through normal production paths.

Every result must state its class and measurement scope. A replay must never be
reported as a fresh analysis.

## Required identity and execution data

Every real-repository record contains:

- benchmark identifier and mode;
- repository name, Git commit when available, and explicit revision-verification
  state;
- Atlas exact Git commit and Atlas package version;
- Python version and implementation;
- operating system, release, and architecture;
- UTC observation timestamp;
- worker count, cache mode, repeat count, and measured durations;
- a non-sensitive logical checkout identity for path-scoped comparisons;
- project, success, and failure counts;
- the source and verification state of project-result counts;
- snapshot size and hashes defined below;
- canonical repository-report hash;
- provider-free default-explanation hash;
- canonical analysis-report and project-order hashes for fresh analysis.

Absolute checkout paths, hostnames, usernames, credentials, and raw provider output
must not be persisted in tracked manifests.

## Canonical manifest

The tracked format is one canonical JSON record per file. A file is named for its
benchmark identifier and mode; Git history provides baseline history without a
mutable multi-record database. Its top-level form is:

```json
{
  "atlas": {
    "commit": "<exact Git object id>",
    "version": "2.0.0"
  },
  "artifacts": {
    "analysis_report_sha256": "<sha256>",
    "analysis_order_sha256": "<sha256>",
    "explain_sha256": "<sha256>",
    "workspace_project_order_sha256": "<sha256>",
    "repository_report_sha256": "<sha256>",
    "semantic_payload_sha256": "<sha256>",
    "snapshot_id": "<ASS snapshot id>",
    "snapshot_sha256": "<sha256 of latest.ass bytes>",
    "snapshot_size_bytes": 0
  },
  "baseline_eligible": true,
  "benchmark_id": "apache-maven",
  "environment": {
    "architecture": "AMD64",
    "os": "Windows",
    "os_release": "<release>",
    "python_implementation": "CPython",
    "python_version": "3.12.10"
  },
  "execution": {
    "analysis_duration_ms": [1000, 1010, 990],
    "cache_mode": "force-no-recover",
    "measurement_scope": "atlas-analyze-subprocess",
    "median_duration_ms": 1000,
    "observed_at_utc": "2026-08-01T00:00:00Z",
    "repeat_count": 3,
    "replay_duration_ms": [],
    "workers": 1
  },
  "format": "atlas-benchmark-manifest",
  "limitations": [],
  "mode": "fresh-analysis",
  "repository": {
    "checkout_identity": "maven-windows-stable-v1",
    "commit": "<exact Git object id>",
    "name": "Apache Maven",
    "revision_verified": true
  },
  "results": {
    "analysis_success_verified": true,
    "failure_count": 0,
    "project_count": 92,
    "source": "analysis-report",
    "source_manifest_sha256": null,
    "success_count": 92
  },
  "schema_version": 1
}
```

Manifest JSON is UTF-8, uses LF line endings, sorted object keys, two-space
indentation, and exactly one final newline. Counts and byte sizes are non-negative
integers; recorded durations are positive integers. Median values use deterministic
half-up rounding. A loader
rejects unsupported schemas and malformed required fields rather than coercing
them. Unknown future fields require a schema decision before they become normative.

Timestamp and duration are observations. They are not part of deterministic result
identity. Equivalent manifest objects serialize byte-for-byte identically; separate
runs are not expected to produce identical manifest bytes because their timestamp
and timing samples intentionally differ.

## Hash semantics

Hash names have one meaning only:

- `snapshot_sha256` is SHA-256 over the exact bytes of the selected ASS artifact.
  Fresh analysis selects `latest.ass`; replay uses its explicit path. The hash proves
  artifact integrity.
- `snapshot_id` is the identifier already verified by
  `AtlasSemanticSnapshot.from_dict()`.
- `repository_report_sha256` is SHA-256 over the compact canonical JSON encoding of
  the persisted `semantic_context.repository_report` object.
- `semantic_payload_sha256` covers schema version, workspace fingerprint, analyzer
  version, and the complete semantic context, but deliberately excludes run-specific
  `snapshot_id` and `history_reference`. It remains checkout-location scoped because
  the semantic context contains the absolute workspace root.
- `explain_sha256` is SHA-256 over the provider-free default repository explanation
  encoded as UTF-8 after normalizing line endings to LF and retaining exactly one
  final newline.
- `analysis_report_sha256` is SHA-256 over the compact canonical JSON projection
  emitted by `atlas analyze --format json`, after repository-root normalization and
  removal of per-project `duration_ms` observations. Durations remain manifest
  measurements, not correctness evidence. The hash is unavailable for replay.
- `workspace_project_order_sha256` hashes the ordered project inventory stored in
  the snapshot.
- `analysis_order_sha256` hashes the CLI execution/report order and exists only for
  fresh analysis. These two order concepts are never conflated.
- `source_manifest_sha256` hashes the normalized canonical manifest object linked by
  a replay. It identifies the exact provenance record, not the pretty-printed file
  bytes.

Canonical JSON uses sorted keys, compact separators, UTF-8, and no ASCII escaping.
The runner validates analysis success from the JSON payload; process exit code alone
is not sufficient because `atlas analyze` can report failed projects without acting
as a quality gate.

### Snapshot portability limitation

An exact ASS hash is not presently a portable cross-machine golden hash. Snapshot
identity includes `history_reference`, and semantic context contains the absolute
workspace root. Consequently:

- exact snapshot hashes are correctness gates only when repository commit, Atlas
  commit, checkout root, and initial Atlas state are controlled;
- raw snapshot hashes remain valid integrity records in every environment;
- report, explanation, analysis-report, graph, and other defined section hashes are
  preferred for cross-host comparisons;
- no benchmark may silently remove arbitrary fields to make a hash stable.

Any future normalized snapshot-regression projection requires an explicit,
documented compatibility contract. It must not replace the raw artifact hash.

## Repeatable repository protocol

For a fresh repository benchmark:

1. Resolve and verify the exact Atlas and repository commits.
2. Reject dirty Atlas and target-repository checkouts. Unpinned mode relaxes revision
   provenance only; it never permits worktree modifications.
3. Use a documented worker count and `--force --no-recover` cache mode.
4. Control the checkout root and initial `.atlas` state when exact snapshot equality
   is required.
5. Capture the deterministic JSON analysis report and require every discovered
   project to succeed.
6. Load the published ASS through checksum and snapshot-ID verification.
7. Hash the snapshot, persisted repository report, and provider-free explanation
   using the definitions above.
8. Repeat the configured workload and fail immediately if deterministic counts or
   comparable hashes differ.
9. Write the result atomically and compare it with a baseline only when workload and
   environment identities, repeat count, measurement scope, and logical checkout
   identity are compatible.

Repository locations are command-line inputs. The runner must not contain Maven,
Quarkus, JUnit, or other repository-specific discovery logic.

## Storage and provenance

Compact accepted baselines belong as individual files under
`benchmarks/baselines/`. Raw logs, snapshots, checkout copies, provider responses,
and per-run diagnostics remain outside version control or in CI artifacts. Git
history is the audit history for accepted baseline changes; no benchmark database is
required. The runner refuses to replace an existing output unless `--force-output`
is supplied explicitly.

A record is baseline-eligible only when the repository commit was supplied and
verified, the checkout identity is declared, at least three samples exist, every
project succeeded, and project-success evidence is verified. Replay counts are
declared historical unless the replay links an eligible fresh-analysis manifest
with the same repository identity, project counts, and raw snapshot hash.
The comparator treats either ineligible side as `incomparable`; provisional evidence
cannot produce a CI-successful baseline comparison.

The ignored local `benchmarks/Maven/` archive is not baseline evidence. The current
archive contains an unresolved repository-path run, runs with blank repository
commit fields, and a partial 73-project failed analysis. It predates the accepted
92-project Maven validation and lacks sufficient provenance. It may be retained for
local debugging, but must not be imported into the canonical manifest.

## Baseline updates and drift

With identical comparable inputs, project/success-count or deterministic-hash drift
is a failure. When Atlas intentionally changes deterministic output, the baseline is
updated only after:

- the changed section is identified;
- compatibility impact is reviewed;
- the new output is reproduced;
- the reason is recorded in the same commit as the baseline update.

Timing drift follows the separate performance policy. It must never be hidden by
updating correctness hashes automatically.
