# M1 Platform Stabilization Report

> **Historical M1 record.** This report describes the provisional commit-scoped
> evidence available before canonical M1.1 capture. Its `STABILIZATION REQUIRED`
> recommendation is superseded by `M1_1_VALIDATION_REPORT.md`, which records the
> accepted Maven and Quarkus baselines and the current `READY FOR PR135` decision.

Date: 2026-08-01  
Roadmap baseline: PR134, commit `b788efea901dffc980ab0bfa9d5afe1e57512a1a`  
Validated M1 implementation: `7d26b83943db808e7283712f3f3f3d6950f7ed58`

## Executive summary

M1 materially strengthens Atlas without implementing PR135 or changing the roadmap.
The milestone adds a strict repository-neutral benchmark manifest and runner,
versioned compatibility fixtures, deterministic regression policies, CI guidance,
and narrowly justified persistence/API hardening.

The internal code baseline is healthy: the complete test suite, compile check, three
fresh Maven analyses, and three Quarkus snapshot replays completed. Deterministic
semantic/report/explain/order gates remained stable.

The release recommendation is **STABILIZATION REQUIRED**. The available Maven and
Quarkus corpora are downloaded source archives without Git metadata, so their records
are correctly provisional and cannot become long-term golden baselines. Quarkus was
replayed rather than freshly analyzed, and its historical success count is not linked
to an eligible fresh manifest. Atlas also needs an explicit version/tag decision;
M1 does not guess a successor to package version `2.0.0`.

## Improvements delivered

### Benchmark and performance foundation

- Added one strict schema-v1 manifest record per JSON file.
- Added generic `analyze`, `replay`, and `compare` commands with no repository-specific
  discovery behavior.
- Recorded repository/Atlas provenance, environment, measurement scope, samples,
  counts, snapshot size, and separately defined correctness hashes.
- Required explicit commit pinning, clean/unchanged Git trees, controlled checkout
  identity, at least three samples, and verified success evidence for baseline
  eligibility.
- Separated fresh-analysis evidence from declared or linked replay evidence.
- Made ineligible records incomparable and correctness regressions non-zero at the
  CLI boundary.
- Added advisory, reproducible performance thresholds and atomic no-overwrite output.
- Streamed raw file and canonical JSON hashing to avoid an unnecessary second large
  in-memory byte copy.

### Snapshot and API hardening

- Revalidated the complete nested snapshot immediately before persistence.
- Rejected invalid schema/identity metadata and non-standard JSON constants at the
  durable store boundary while preserving adversarial in-memory compatibility tests.
- Made immutable historical archive publication atomic across independent store
  instances; same-second captures are preserved under deterministic ID suffixes.
- Added an exact LF-enforced schema-v1 ASS golden with fixed raw, semantic, and
  provider-free explain hashes.
- Added an independent public API v1 constructor-signature fixture and made removed
  runtime exports reportable rather than raising `KeyError`.

### Documentation

- Added benchmark, snapshot, performance, CI, determinism, and technical-debt
  strategies under `docs/stability/`.
- Documented the current repository-intelligence ownership chain and the
  canonical-versus-specialized graph boundary.
- Marked stale architecture/review inputs historical and reconciled the ADR index
  with files that actually exist.
- Updated the README test total and benchmark entry points.

## Validation results

### Automated tests and compilation

| Validation | Actual result |
|---|---|
| Focused regression selection after the first full-suite findings | `45 passed in 0.62s` |
| First complete suite | `3679 passed, 2 failed, 1 skipped in 15.69s` |
| First-suite finding | finite-JSON enforcement was too early and broke two intentional malformed in-memory snapshot tests |
| Complete post-fix suite | `3681 passed, 1 skipped in 15.32s` |
| `python -B -m compileall -q benchmarks moughorai` | exit `0`, no diagnostics |
| `git diff --check` before the implementation commit | exit `0` |

The skipped test remains explicitly reported; M1 does not describe it as passed.

### Apache Maven fresh analysis

Manifest: `benchmarks/results/m1-apache-maven.json` (ignored local evidence)

| Field | Result |
|---|---|
| Mode | `fresh-analysis` |
| Repetitions | 3 |
| Projects | 92 |
| Succeeded / failed | 92 / 0 |
| Analysis durations | 24,130 ms; 23,695 ms; 23,709 ms |
| Median | 23,709 ms |
| Snapshot size | 31,153,709 bytes |
| Analysis report SHA-256 | `c4296f8d2e03bae77681d2dc927bc532683d47d0bdcb9b651f70015b0bdb7e18` |
| Analysis/workspace order SHA-256 | `9bd5e6de80addc3983a33e8f284f490b79286631adcfb9c89fb135cb3079a858` |
| Semantic payload SHA-256 | `39012992281c938af8f285c610db5d69796c4330dd879a4a2d0ff6863c65d455` |
| Repository report SHA-256 | `0da6de7d4ce5059f7ea4386e5912b532c64753007072585e467756b01b79524f` |
| Provider-free explain SHA-256 | `93a06637a0822557449a21911e91138acc7b58cef0b1e4bcdb619c769a07c6b4` |
| Final raw snapshot SHA-256 | `505b60170178ee0c1019759f1a87b365f2fc8d4140ee302371575efb84a7bb54` |
| Baseline eligible | no: source archive has no verifiable Git commit |

All deterministic gates matched across the three fresh analyses. Raw ASS hashes were
`2f9c2668f0855eb3b2986d00aa0b1b15cbcaa852f8028b6481e944ab2bdca826`,
`27fa398f6ecaa11d86e2d6a93965d8168968a02115aa4e3b4eae3a139eeab35a`, and
`505b60170178ee0c1019759f1a87b365f2fc8d4140ee302371575efb84a7bb54`;
their expected drift comes from distinct `history_reference` values. Snapshot size
stayed identical.

### Quarkus snapshot replay

Manifest: `benchmarks/results/m1-quarkus-replay.json` (ignored local evidence)

| Field | Result |
|---|---|
| Mode | `snapshot-replay` |
| Repetitions | 3 |
| Projects in snapshot | 1,442 |
| Declared historical success / failure | 1,442 / 0 |
| Replay durations | 11,993 ms; 12,088 ms; 11,967 ms |
| Median | 11,993 ms |
| Snapshot size | 337,186,920 bytes |
| Raw snapshot SHA-256 | `4c3357ed62bdd3d91ed3654a0e6a826a8c34f8dbe29f6879a23ef9514c4a4da1` |
| Workspace order SHA-256 | `d2ed544debf248f36d51ec96a4c72ea7ecf1022c87d697a36697178381176646` |
| Semantic payload SHA-256 | `d298e22b29ea46194d8454d167eaa5f65a0e91fb555349094f4a8834f4a5c235` |
| Repository report SHA-256 | `f9e469d6083da885f698f0fb98f74a4375f83d400891ffbdf16afd1af91b0531` |
| Provider-free explain SHA-256 | `0ee0eb596e1b7bb827d91f7bdae251e8eb3fb2bfc3f1b17000281ba43f868125` |
| Baseline eligible | no: no Git metadata and no linked eligible fresh manifest |

The snapshot, order, semantic payload, report, and explanation were identical on all
three replays. This result does not claim a fresh Quarkus analysis or reproduced
per-project completion evidence.

## Maturity assessment

| Area | Assessment | Evidence / remaining risk |
|---|---|---|
| Platform architecture | strong | PR127-PR134 ownership boundaries remain intact; no second graph, cache, or analysis engine was introduced |
| Determinism | strong within comparable inputs | canonical models, process hash-seed checks, three Maven runs, and three Quarkus replays are stable; raw ASS identity remains capture/path scoped |
| Testing | strong | 3,681 passing tests, one explicit skip, adversarial regression caught and corrected |
| Snapshot compatibility | strong for schema v1 | byte golden, checksum/ID validation, strict durable JSON, concurrent archive preservation; deep nested immutability remains deferred |
| Benchmarking | structurally ready, evidence provisional | runner and schema are strict; external corpora lack pinned Git provenance |
| Performance | early/advisory | repeat samples and thresholds exist, but no eligible history or stable-runner distribution exists yet |
| CI | designed, not provider-installed | stages and exit contracts are provider-neutral; repository has no selected internal CI provider |
| Documentation | materially improved | normative guides are discoverable; historical delivery-patch retention remains unresolved |
| Public API stability | improved, partial | v1 constructor surface is independently anchored; behavioral/enum/payload compatibility is not yet a complete public contract |

## Performance observations

- Maven's three fresh end-to-end samples have a 435 ms range (about 1.8 percent of
  the median), but this single batch is not a performance baseline.
- Quarkus replay has a 121 ms range (about 1.0 percent of the median).
- A focused audit spot measurement on a 6.7 MB snapshot observed about 20 percent
  extra serialization CPU from pre-save revalidation. The correctness protection is
  retained; a fresh large Quarkus save should measure its real impact before a
  release performance claim.
- Snapshot raw hashing now streams in chunks. JSON parsing still necessarily
  materializes the semantic model, so the 337 MB replay remains memory-sensitive.
- No cache, parallelism, telemetry, or repository-specific optimization was added.

## Remaining technical debt and risk

### Critical

None identified.

### High

- Maven and Quarkus benchmark sources need exact verifiable upstream Git commits
  before compact records can be accepted as long-term goldens.
- A fresh pinned Quarkus analysis is still needed to verify analysis success and
  snapshot publication under the M1 persistence boundary.

### Medium

- Choose and tag an explicit Atlas release version; the exact M1 commit currently
  disambiguates the long-lived package version `2.0.0`.
- Raw snapshot and graph identities remain checkout-location sensitive. Do not create
  a portable projection without a versioned compatibility decision.
- `KnowledgeGraph.from_dict()` remains permissive for malformed schema/duplicate
  inputs; normal production serialization is canonical.
- Snapshot nested values remain shallowly mutable in memory. Pre-save validation
  protects durability without breaking the existing mapping API.
- Performance thresholds remain advisory until a stable runner has multiple eligible
  batches.
- Historical verification documents still reference untracked delivery patches and
  need a separately chosen archive policy.

### Low / future

- Confirm a deprecation path before removing the obsolete alternate
  `moughorai/main.py` entry module.
- Confirm ownership before removing the unreferenced Java semantic walker.
- Extend public compatibility fixtures only when real consumers establish additional
  behavioral or serialized contracts.

## Recommended priorities before PR135

1. Obtain clean Maven and Quarkus Git checkouts at explicit upstream commits.
2. Run three fresh single-worker analyses at fixed logical/physical checkout roots
   and promote only baseline-eligible manifests after review.
3. Run a fresh Quarkus analysis to measure large-snapshot save cost and peak memory.
4. Make an explicit package version and release-tag decision for the M1 commit.
5. Select a CI provider only after mapping the provider-neutral stages; do not alter
   Atlas product CI templates as a substitute.

No PR135 functionality should be implemented until items 1-4 are resolved or the
release owner explicitly accepts those risks.

## Suggested future benchmark corpus

- JUnit: mixed Maven/Gradle hierarchy and known 41-project aggregator behavior.
- Gradle: large Gradle-native multi-project discovery and ordering.
- Spring Framework: large Java/Kotlin build and framework-managed evidence.
- Elasticsearch: very large Gradle workspace and memory pressure.
- Quarkus: fresh analysis and large ASS publication, not only replay.
- Micronaut and OpenRewrite: annotation/framework evidence and transformation-heavy
  Java structures.

Adding a repository requires a pinned commit and a concrete coverage purpose. M1
does not add or download new benchmark repositories.

## Files changed

- Benchmark tooling: `benchmarks/README.md`, `benchmarks/repository_benchmark.py`,
  `benchmarks/stability_manifest.py`, `.gitignore`, `.gitattributes`.
- Stability guidance: all seven documents under `docs/stability/`, including this
  final report.
- Architecture/readme: `README.md`, `docs/ARCHITECTURE.md`,
  `docs/architecture/ARCHITECTURAL_DECISIONS.md`,
  `docs/architecture/ARCHITECTURE_OVERVIEW.md`, and
  `docs/architecture/KIRO_ARCHITECTURE_REVIEW.md`.
- Narrow production hardening: `moughorai/__init__.py`,
  `moughorai/public_api/__init__.py`, `moughorai/semantic_snapshot/models.py`, and
  `moughorai/semantic_snapshot/store.py`.
- Regression assets/tests: `tests/fixtures/public_api_v1.json`,
  `tests/fixtures/semantic_snapshot_v1_minimal.ass`,
  `tests/test_m1_platform_stability.py`, `tests/test_pr105_public_api.py`, and
  `tests/test_pr111_semantic_snapshot.py`.

## Recommended commits

- `7d26b83 chore: establish M1 platform stability baseline`
- A documentation-only follow-up recording this final benchmark evidence.

The official roadmap was not modified, and no PR135-or-later functionality was
implemented.
