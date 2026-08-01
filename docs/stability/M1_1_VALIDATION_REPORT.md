# M1.1 Canonical Baseline Validation Report

Date: 2026-08-01
Platform: Windows 11, AMD64, CPython 3.12.13
Atlas version: 2.0.0
Validated Atlas commit: `7565042439ef3f3607c7ba4849d445f79e9ef550`

## Executive decision

**Recommendation: READY FOR PR135.**

**Engineering designation: Atlas M1 Stable baseline.** Do not designate this work
`Atlas v1.0.0-alpha1`: the validated package already reports version 2.0.0, M1.1 does
not change product versioning, and no release tag is created by this validation.
“M1 Stable” describes the engineering baseline, not a published stable release.

Both required repositories were captured from clean, complete, detached Git
checkouts at the pinned commits. Every discovered project succeeded. Three fresh
analyses per repository reproduced exact deterministic output, both source-free
golden bundles passed independent verification against their raw ASS files, and
three linked replays per repository reproduced the persisted semantic gates.

This is an initial performance cohort, not evidence of improvement or regression
against the legacy archive runs. The tracked manifests are suitable correctness
baselines. Raw snapshots, golden bundles, checkouts, and replay manifests remain
ignored operational evidence.

## Validated inputs

| Input | Immutable revision | Operational root | Provenance |
|---|---|---|---|
| Atlas | `7565042439ef3f3607c7ba4849d445f79e9ef550` | `C:\MoughorAI\Atlas_PR4_Source` | clean Git worktree during capture |
| Apache Maven | `3e01a12e9eacd2b336f4db786d54e35647ce268c` | `C:\AITest\atlas-m1.1\maven-source` | detached `master`; complete history; 10,122 blobs; 28,136,721 bytes |
| Quarkus | `bbc0853aef94c567bac2cc4a98d51c90fb423648` | `C:\AITest\q` | detached `main`; complete history; 31,433 blobs; 128,026,844 bytes |

Neither pinned tree declares submodules or Git LFS content. The Maven and Quarkus
logical checkout identities are `apache-maven-m1-1` and `quarkus-m1-1`. Physical
paths are operational details and are absent from tracked manifests.

The later documentation/baseline commit does not alter the validated analyzer or
benchmark code. All captures intentionally retain the exact code commit above.

## Atlas validation

The following commands were actually executed on the validated implementation:

| Command | Exact result |
|---|---|
| `python -m pytest -q -p no:cacheprovider --basetemp .pytest_m11_targeted_final tests\test_m1_platform_stability.py tests\test_m1_1_checkout_provenance.py` | `58 passed in 6.55s` |
| `python -m pytest -q -p no:cacheprovider --basetemp .pytest_m11_full_after_quarkus_fix` | `3717 passed, 1 skipped in 21.17s` |
| `python -m pytest -q -rs ...::test_project_indexer_does_not_follow_file_symlinks` | `1 skipped in 0.15s` |
| `python -m compileall -q moughorai benchmarks tests` | exit code 0 |

The exact full-suite skip was:

```text
tests\test_production_review_remediations.py:107:
file symlinks are unavailable on this platform
```

No passing claim is made for an unexecuted test. One early targeted invocation
reported `10 passed` and two setup errors because the default pytest temporary
directory and cache were inaccessible (`WinError 5`). The controlled-basetemp rerun
then exposed one incorrect diagnostic-location expectation (`11 passed, 1 failed`);
the test expectation was corrected to include the `semantic_context` root. The final
targeted and complete results above are the accepted evidence.

## Apache Maven result

The canonical verifier confirmed the exact commit, URL, detached HEAD, clean tree,
complete history, tracked inventory, and absent initial `.atlas` state. The final
fresh command used three repetitions and exited 0 after 170.9 seconds of total
orchestration time.

| Measure | Result |
|---|---|
| Projects | 92 |
| Succeeded / failed | 92 / 0 |
| Timed fresh analyses | 23,922 ms; 23,615 ms; 23,662 ms |
| Fresh median | 23,662 ms |
| Raw ASS | 31,168,556 bytes |
| Snapshot ID | `75cc7e122ad2103befe956b0531b1053016119aa21b1faf000d00b5009328852` |
| Raw snapshot SHA-256 | `511c5330ae607150d7d5b28510c24f5741ff81d9ee7eb0d3defa31adda08426a` |
| Portable semantic SHA-256 | `d49835d18719a02f17e2118dcf244d96acac4bbf9d365e3c589fb987df28b66b` |
| Repository report SHA-256 | `3cb03db433dede8dbf4941c030c7375f1920ed5caac15a47d0d7dd7262ee7361` |
| Explain SHA-256 | `c7e332fca0ad55196378e6a9bfeb1b9e687cf8aaf5011ee566d207a05fea8933` |
| Risk SHA-256 | `9ffc5810cedf67c5babbb9cea377e8529a336917a149135735c5e85968261b89` |
| KnowledgeGraph SHA-256 | `37743e2e5ba29ab0da8164065109aea4f73e0d927b0e02a687232e67b0129669` |
| Workspace order and analysis order SHA-256 (both) | `3d747b9bfe7ac27ce8f367ad9287fb43ab1704e2ecfb2a23a8d0fae4230561e6` |
| Fresh deterministic-order SHA-256 | `903928f5fc4a6a74b4f9b05a4d7a770d23cb2dba2f611aed0ef066b0b7f59d2b` |

The eight-file golden bundle is 29,851,709 bytes, including a 29,651,431-byte
portable semantic snapshot. Independent `verify-golden` execution exited 0 with
`external_snapshot_verified: true`.

The linked replay exited 0 after 59.2 seconds. Its measured repetitions were
16,937 ms, 16,926 ms, and 16,967 ms (median 16,937 ms). Its canonical fresh-manifest
lineage is `0ff83419d4497f70757ff9df3c3b9784f7134a52253209090c80c346e2e9c16a`.

## Quarkus result

The canonical verifier confirmed the exact commit, URL, detached HEAD, clean tree,
complete history, tracked inventory, and absent initial `.atlas` state. The final
fresh command used three repetitions and exited 0 after 1,598.9 seconds of total
orchestration time.

| Measure | Result |
|---|---|
| Projects | 1,442 |
| Succeeded / failed | 1,442 / 0 |
| Timed fresh analyses | 347,620 ms; 346,927 ms; 348,588 ms |
| Fresh median | 347,620 ms |
| Raw ASS | 337,100,718 bytes |
| Snapshot ID | `c0a869b9a27778095ea009f399786fe34edaa17aaa082428bd7c9b0871e5f2e2` |
| Raw snapshot SHA-256 | `d463551cb42fdebce96323fee6f1adbf147e05f377c4fc0f811b74c2b338a694` |
| Portable semantic SHA-256 | `8c867e8c31fb4203ce7bfb955907dd68c852ec3f1c4dcf9a5f70a1b10372e9b4` |
| Repository report SHA-256 | `b4a905c2c602e3a9e4912de7757b8f0ecce0103c8b80bf7c7d3cce423921e1bc` |
| Explain SHA-256 | `72d58b096ebb854467eaab182c98c5abb47fcd0b60e6f13d19b4847a102d0547` |
| Risk SHA-256 | `97c1e765bf5ff234a04039a8cd03ee61ce269ca9e1e39e9b6a52c805262107db` |
| KnowledgeGraph SHA-256 | `21c47c475718ccd02128c95e2cf64a5ec461c4dbddc2612b4dee381a42b9a122` |
| Workspace order and analysis order SHA-256 (both) | `da5919e2741e32d054d3d673c071d71ea9b3370ddf6789aea08d3cb09c339f6f` |
| Fresh deterministic-order SHA-256 | `c1d6476bbf0647e1adf2c0b3d64675980800e686c4b3fcbe12437bbe489a0736` |

The eight-file golden bundle is 324,079,727 bytes, including a 323,615,601-byte
portable semantic snapshot. Independent `verify-golden` execution exited 0 with
`external_snapshot_verified: true`.

The linked replay exited 0 after 302.9 seconds. Its measured repetitions were
99,560 ms, 100,791 ms, and 100,700 ms (median 100,700 ms). Its canonical
fresh-manifest lineage is
`a57b592a14c746d1f35aea5c032d3764febbf0b404bc6d52b07bc7045f6f351a`.

## Determinism assessment

The fresh runner required exact repeated ASS identity, project inventory, analysis
report, semantic projection, report, explanation, risk, graph, workspace order, and
analysis order. The replay runner reloaded each accepted snapshot three times.
Independent post-run validation loaded all four manifests canonically and confirmed
that ten replay gates plus the project counts and zero-failure results matched their
fresh source.

Fresh and replay `deterministic_ordering_sha256` values intentionally differ: a
fresh record hashes its observed analysis order, while replay records an explicit
analysis-order-unavailable state. This is mode semantics, not nondeterminism.

Fresh timing spread was 307 ms (1.30% of the median) for Maven and 1,661 ms (0.48%)
for Quarkus. Replay spread was 41 ms (0.24%) for Maven and 1,231 ms (1.22%) for
Quarkus. These values establish the first comparable cohort. They are advisory until
a later run uses the same repository revisions, Atlas measurement scope, Python
inventory, OS, architecture, worker count, cache mode, and repeat count.

## Issues found and resolved

1. A Maven checkout physically named `apache-maven` collided with the repository's
   discovered `apache-maven` project. Capture stopped with
   `duplicate project name 'apache-maven'`. The checkout was moved to
   `maven-source`; no production discovery rule was weakened.
2. Quarkus initially failed to open a 263-character nested Java path. The verified
   checkout was moved to `C:\AITest\q`, reducing that path to 239 characters. The
   source tree and pinned commit were unchanged.
3. The first short-root Quarkus capture reached snapshot projection but stopped with
   `portable semantic snapshot still contains an absolute machine path`. Diagnosis
   found nine false positives: Maven `${project.version}` coordinates were mistaken
   for drive paths and an escaped Java delimiter string for UNC syntax. Commit
   `7565042` tightened only the benchmark validator's lexical boundaries, added a
   bounded JSON-location diagnostic, and added positive and negative regressions.
   The actual 337,100,718-byte snapshot then projected successfully before the final
   clean capture.

Every failed capture stopped before publishing a candidate manifest or golden
bundle. Generated `.atlas` state was removed only after verifying the exact target
under the controlled benchmark root.

## Tracked and retained evidence

Tracked compact manifests:

- `benchmarks/baselines/apache-maven-fresh.json`
- `benchmarks/baselines/quarkus-fresh.json`

Each tracked file is byte-identical to its accepted candidate and passes the strict
canonical manifest loader. Complete project and analysis-order preimages are retained
in these records.

Ignored local evidence includes the two raw ASS files, fresh/replay candidate
manifests, and eight-file golden directories under `benchmarks/results/m1.1/`.
Release CI should retain equivalent artifacts in access-controlled storage together
with their checksums.

## Files added or modified

- `.gitattributes`
- `.gitignore`
- `README.md`
- `benchmarks/README.md`
- `benchmarks/canonical_baseline.py`
- `benchmarks/repositories.json`
- `benchmarks/repository_benchmark.py`
- `benchmarks/stability_manifest.py`
- `benchmarks/baselines/apache-maven-fresh.json`
- `benchmarks/baselines/quarkus-fresh.json`
- `docs/stability/BENCHMARK_STRATEGY.md`
- `docs/stability/M1_1_CANONICAL_BASELINE.md`
- `docs/stability/M1_1_REPLAY_AND_CI.md`
- `docs/stability/M1_1_REPOSITORY_AUDIT.md`
- `docs/stability/M1_1_VALIDATION_REPORT.md`
- `docs/stability/M1_PLATFORM_STABILIZATION.md`
- `docs/stability/SNAPSHOT_REGRESSION_STRATEGY.md`
- `tests/fixtures/benchmark_manifest_v1_fresh.json`
- `tests/test_m1_1_checkout_provenance.py`
- `tests/test_m1_platform_stability.py`

## Remaining risks and technical debt

- **Upstream retention:** GitHub availability is not a two-year retention guarantee.
  Store reviewed Git bundles or an access-controlled mirror of both pinned commits.
- **Quarkus memory and I/O:** golden creation materializes large semantic payloads;
  peak memory is not yet measured and the portable snapshot is 323.6 MB. Add process
  memory telemetry before treating this workflow as a routine per-commit CI stage.
- **Crash recovery:** an abrupt process termination can leave an orphan manifest or
  staging directory between the paired publications. The final golden directory is
  staged and verified before publication, but an operator must quarantine or remove
  owned orphan output before rerun.
- **Windows placement:** checkout basenames can affect project identity, and deeply
  nested corpora can exceed filesystem path limits. Canonical runners need documented,
  stable, short physical roots even though those paths are not semantic identity.
  Exact reproduction of the accepted project inventories currently requires root
  basenames `maven-source` and `q`; `repositories.json` does not enforce them.
- **Path classification:** the final source-free guard is a conservative lexical
  classifier. The Quarkus false positives are covered, but URLs, regex syntax,
  punctuation-adjacent paths, and other ambiguous text can still produce false
  positives or negatives. Root projection remains restricted to verified aliases;
  future refinement must add real-corpus regressions rather than silently stripping
  unknown values.
- **External artifact service:** the procedure is provider-neutral; automated
  retention, promotion approval, and scheduled replay remain operational work.
- **JUnit:** the historical 41-project result was not promoted because its previously
  used local corpus was unavailable for immutable provenance capture.

Correctness risk after this validation is low for the two pinned corpora. Operational
risk remains medium because of Quarkus resource use and external artifact retention.
No production analyzer behavior, roadmap item, or PR135 functionality was added by
M1.1.

## Recommendation

**READY FOR PR135.** Use the two tracked fresh manifests as the canonical pre-PR135
correctness baseline. Proceed only from a clean descendant of the validated commits.
Before a published stable release, rerun both pinned fresh analyses and linked
replays on the release candidate, retain the raw/golden evidence, and disposition
any deterministic or performance comparison result under `M1_1_REPLAY_AND_CI.md`.
