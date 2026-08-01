# Atlas M1.1 Canonical Benchmark Baseline

## Status

This document defines the canonical, reproducible benchmark contract introduced by
M1.1. It strengthens the M1 benchmark ecosystem without changing the Atlas roadmap,
analysis behavior, or any PR135 capability. Schema-v1 manifests remain readable;
new canonical captures use manifest schema 2 and benchmark version `m1.1`.

The tracked sources of truth are:

- `benchmarks/repositories.json` for immutable repository definitions;
- `benchmarks/canonical_baseline.py` for checkout, verification, capture, replay,
  and golden-bundle orchestration;
- `benchmarks/repository_benchmark.py` for the existing analysis/replay runner;
- `benchmarks/stability_manifest.py` for manifest serialization and comparison;
- compact reviewed JSON records under `benchmarks/baselines/`.

The repository audit is in `M1_1_REPOSITORY_AUDIT.md`. Replay and CI policy is in
`M1_1_REPLAY_AND_CI.md`.

## Canonical repositories

| ID | Upstream | Selection ref | Pinned commit | Expected projects |
|---|---|---|---|---:|
| `apache-maven` | `https://github.com/apache/maven.git` | `master` | `3e01a12e9eacd2b336f4db786d54e35647ce268c` | 92 |
| `quarkus` | `https://github.com/quarkusio/quarkus.git` | `main` | `bbc0853aef94c567bac2cc4a98d51c90fb423648` | 1,442 |

The branch records where the immutable commit was selected. Capture uses detached
HEAD at the commit and never follows the branch. Neither commit has a selected tag.
Unknown tags are represented as JSON `null`, not inferred from version strings.

Repository size means the sum of uncompressed blob sizes in the pinned Git tree.
The file count is the number of tracked blobs. It excludes `.git`, `.atlas`, build
outputs, ignored files, filesystem allocation, and checkout line-ending expansion.
Gitlink entries are recorded separately as submodule path/commit pairs. LFS status
means that the pinned tree declares `filter=lfs`; it is not guessed from filenames.

## Definition format

`benchmarks/repositories.json` is canonical UTF-8 JSON with sorted keys, two-space
indentation, LF endings, and one final newline. Each definition records:

- stable repository ID and display name;
- credential-free HTTPS URL;
- full lowercase Git commit;
- selection branch and optional tag;
- logical checkout identity;
- expected project count, worker count, and timeout;
- tracked blob count and byte size;
- exact submodule pins, LFS requirement, and complete declared-branch history.

The loader rejects unknown fields, duplicate IDs, noncanonical bytes, unsafe paths,
invalid object IDs, and declaration-order drift. Local checkout paths do not belong
in the tracked definition.

## Manifest schema 2

One manifest contains one benchmark observation. It records all M1 fields plus:

- `benchmark_version`;
- repository URL, branch, tag, tracked file count, tracked byte size, submodules,
  LFS requirement, and Git-history completeness;
- the deterministic full installed-distribution inventory;
- portable semantic, risk, canonical KnowledgeGraph, and deterministic-order hashes;
- the ordered workspace-project inventory and fresh-analysis execution order that
  provide auditable preimages for the ordering hashes.

The environment, observation time, and duration samples are metadata. They are not
included in deterministic payload hashes. Unknown values remain `null`; missing
provenance makes a record ineligible rather than being filled heuristically.

A schema-2 record is baseline eligible only when:

1. repository commit and origin are verified in a clean, non-shallow Git checkout;
2. branch or tag provenance and logical checkout identity are recorded;
3. tracked content, submodule, and LFS facts are known;
4. Atlas commit and the installed-distribution inventory are recorded;
5. at least three samples exist;
6. every expected project succeeded through a fresh analysis, or replay success is
   linked to an eligible fresh manifest;
7. repository report, portable semantic, risk, graph, and ordering hashes exist.

`baseline_eligible` means that the manifest contains internally consistent evidence;
it is not, by itself, proof that the canonical wrapper performed its detached-HEAD,
definition, initial-state, and clean-reset preflight. Promotion additionally requires
the recorded `canonical_baseline verify` and `capture` procedure. A direct runner
record is not promoted merely because its evidence fields satisfy eligibility.

Schema-v1 files retain their original exact serialization and eligibility semantics
when loaded. New writes never silently downgrade to schema 1. File consumers require
the exact canonical byte representation; minified JSON, BOM, CRLF, and trailing
whitespace are rejected.

## Deterministic hash contract

All JSON payload hashes use SHA-256 over sorted compact JSON, UTF-8, no ASCII
escaping, and no non-finite numbers. Text uses LF and exactly one final newline.

| Field | Exact payload | Portability |
|---|---|---|
| `snapshot_sha256` | raw verified ASS bytes | integrity only; operational metadata can scope it |
| `semantic_payload_sha256` | original schema, workspace fingerprint, analyzer version, and semantic context | retained M1 path-scoped diagnostic |
| `portable_semantic_sha256` | versioned semantic projection with checkout root and path-scoped workspace fingerprint replaced by stable tokens | cross-root correctness gate |
| `repository_report_sha256` | complete source-free persisted repository report | cross-root gate |
| `explain_sha256` | provider-free default explanation | cross-root gate |
| `risk_sha256` | complete portable `risk_analysis` mapping | cross-root gate |
| `knowledge_graph_sha256` | complete portable canonical `semantic_graph` mapping | cross-root gate |
| `analysis_report_sha256` | portable JSON analysis report excluding per-project `duration_ms` observations | fresh-analysis gate |
| `workspace_project_order_sha256` | ordered project names in the snapshot | ordering gate |
| `analysis_order_sha256` | ordered projects in the CLI result | fresh-analysis ordering gate |
| `deterministic_ordering_sha256` | workspace-order hash plus the recorded fresh analysis order, or explicit replay-unavailable state | combined ordering gate |

The portable projection replaces only the verified repository root, its percent-
encoded forms, and the path-scoped workspace fingerprint. It preserves all semantic
fields and rejects any remaining literal or encoded machine root. It does not remove
source facts merely to obtain a desired hash.

## Fresh checkout and capture

Use an empty target outside the Atlas source tree. `prepare` refuses an existing
target, initializes Git, fetches the complete declared branch history and objects,
checks out the exact commit at detached HEAD, and handles Windows long paths locally
to that checkout. Shallow and partial/promisor clones are rejected. The pinned commit
must be reachable from that branch, and a declared tag must resolve exactly to the
pinned commit.

```text
python -m benchmarks.canonical_baseline prepare apache-maven C:\benchmarks\apache-maven
python -m benchmarks.canonical_baseline verify apache-maven C:\benchmarks\apache-maven --require-initial-state
```

After committing the Atlas benchmark implementation, record the exact clean Atlas
commit and capture three repetitions:

```text
python -m benchmarks.canonical_baseline capture apache-maven C:\benchmarks\apache-maven --atlas-commit <atlas-sha> --repeats 3 --output benchmarks\results\apache-maven-fresh.json --golden-output benchmarks\results\apache-maven-golden
python -m benchmarks.canonical_baseline verify-golden benchmarks\results\apache-maven-golden --snapshot C:\benchmarks\apache-maven\.atlas\ass\latest.ass --require-snapshot
```

Repeat those commands for repository ID `quarkus`, root `C:\benchmarks\quarkus`,
and `quarkus-fresh.json` / `quarkus-golden` outputs. A release baseline requires
independent Maven and Quarkus evidence; one corpus never stands in for the other.

Every repetition removes only the validated `ROOT/.atlas` directory. This makes each
sample a clean-state analysis and requires exact raw ASS reproduction as well as the
portable semantic gates. The runner rejects the wrong project count, commit, origin,
tracked tree, shallow or unreachable history, tracked or pre-existing `.atlas` state,
Atlas commit, dirty worktree, or nondeterministic artifact.

Clone/fetch duration, dependency installation, and golden writing are outside the
timed `atlas analyze` subprocess. Exact Python and dependency versions remain in the
manifest.

## Golden bundle

A generated bundle contains:

- `semantic-snapshot.json`: complete versioned portable semantic projection;
- `repository-report.json`: source-free deterministic repository report;
- `ai-explain.md`: provider-free default explanation;
- `risk-summary.json`: compact status/count/capability projection plus full risk hash;
- `knowledge-graph-summary.json`: node/edge/kind counts plus full graph hash;
- `deterministic-ordering.json`: workspace and analysis project orders plus their
  evidence-bound ordering hashes;
- `benchmark-metadata.json`: manifest plus bundle identity;
- `checksums.json`: exact file hashes for the other bundle members.

The publisher reloads the checksum-verified ASS and checks its raw size, hash,
snapshot ID, portable semantic payload, report, explanation, risk, graph, and
workspace ordering against the manifest before publishing. It stages the complete
directory and refuses to overwrite an existing bundle. `verify-golden` rechecks the
exact file set, canonical bytes, checksums, embedded manifest, semantic linkage, and,
with `--require-snapshot`, the external raw ASS lineage.

Large bundles remain ignored local or access-controlled CI/release artifacts. Git
tracks the small repository definitions and reviewed baseline manifests. Benchmark
repositories, raw ASS files, provider output, and machine paths are never committed.

## Regression comparison

Comparable runs must match repository URL/commit/ref, tracked content, submodules,
LFS requirement, benchmark version, mode, checkout identity, Python minor version,
installed-distribution inventory, OS, architecture, worker count, cache mode, measurement
scope, and sample count. Replay additionally requires the same raw snapshot identity
and linked fresh-manifest lineage.

Project counts or deterministic semantic hash drift is a correctness regression.
Raw-only drift in a fresh analysis is an operational warning when portable semantics
match. Performance uses median samples and configurable percentage plus absolute
thresholds; wall-clock durations are never exact correctness values.

## Promotion policy

Promotion into `benchmarks/baselines/` is manual. The reviewer must verify:

1. fresh checkout and exact provenance;
2. full Atlas tests and compilation;
3. expected all-success project count;
4. three deterministic clean-state captures;
5. source-free golden bundle and matching checksums;
6. independent comparison and review of performance spread;
7. an explanation for every intentional baseline change.

No failure updates a baseline automatically. An unavailable corpus or resource limit
is reported as `not-run` with the exact reason.
