# M1.1 Repository Provenance Audit

Date: 2026-08-01
Scope: benchmark-corpus provenance only

## Purpose

This audit records the immutable identities available for the Apache Maven and
Quarkus benchmark corpora. It distinguishes canonical repository identity from
machine-local checkout placement. It does not report new Atlas test, analysis, or
performance results.

For future reproducible captures, the canonical repository identity is the upstream
Git URL plus the full verified commit. Branch names are useful acquisition context,
but they are mutable and do not replace a commit. Local paths are operational details
and are never canonical repository identities.

## Fresh pinned checkouts

### Apache Maven

| Field | Verified value |
|---|---|
| Upstream URL | `https://github.com/apache/maven.git` |
| Commit | `3e01a12e9eacd2b336f4db786d54e35647ce268c` |
| Source branch | `master` |
| Checkout state | clean, detached HEAD before capture; generated `.atlas` retained afterward |
| Git history | complete, non-shallow/non-partial; 16,236 commits reachable from HEAD |
| Exact tag | none |
| Tracked-blob inventory | 10,122 blobs; 28,136,721 bytes |
| Submodules | none |
| Git LFS content | none |
| Operational checkout | `C:\AITest\atlas-m1.1\maven-source` |

The local checkout path is a controlled operational location, not part of Maven's
canonical identity. The full commit, rather than `master`, must be used for benchmark
provenance and comparison.

### Quarkus

| Field | Verified value |
|---|---|
| Upstream URL | `https://github.com/quarkusio/quarkus.git` |
| Commit | `bbc0853aef94c567bac2cc4a98d51c90fb423648` |
| Source branch | `main` |
| Checkout state | clean, detached HEAD before capture; generated `.atlas` retained afterward |
| Git history | complete, non-shallow/non-partial; 61,098 commits reachable from HEAD |
| Exact tag | none |
| Tracked-blob inventory | 31,433 blobs; 128,026,844 bytes |
| Submodules | none |
| Git LFS content | none |
| Operational checkout | `C:\AITest\q` |

The local checkout path is a controlled operational location, not part of Quarkus's
canonical identity. The full commit, rather than `main`, must be used for benchmark
provenance and comparison.

These checkouts established the pinned inputs used by the accepted M1.1 captures.
The checkout basename `apache-maven` was replaced by `maven-source` because it
collided with a discovered Maven project identity. Quarkus was placed at the short
root `C:\AITest\q` so its deepest tracked Java path remained accessible on Windows.
These operational paths do not retroactively add provenance to earlier archive-based
results.

## Legacy source archives

The previous corpora were downloaded branch archives rather than Git checkouts.
Their current bytes can be identified, but their exact upstream commits cannot be
recovered from the retained local evidence.

### Apache Maven archive

| Field | Observed value |
|---|---|
| Archive | `C:\AITest\maven-master.zip` |
| Extracted root | `C:\AITest\maven-master\maven-master` |
| Archive SHA-256 | `0c2477ff756dc45502de0bbe422c28a56742eb52eb168346d33c88aaee2030b3` |
| Recorded download URL | `https://codeload.github.com/apache/maven/zip/refs/heads/master` |
| Recorded referrer | `https://github.com/apache/maven` |
| Embedded project version | `4.1.0-SNAPSHOT` |
| Embedded SCM URL | `https://gitbox.apache.org/repos/asf/maven.git` |

The extracted root has no `.git` metadata. The `master` URL component and embedded
SCM metadata identify the intended project and mutable branch, but do not prove an
immutable commit, tag, or checkout branch. Git clean/dirty state cannot be determined.
No `.gitmodules`, `.lfsconfig`, LFS attributes, or LFS pointer signatures were
observed, but operational submodule and LFS checkout state cannot be reconstructed
without Git metadata. Generated `.atlas` data is present and was not in the archive,
so the extracted directory is not byte-identical to the downloaded archive.

### Quarkus archive

| Field | Observed value |
|---|---|
| Archive | `C:\AITest\quarkus-main.zip` |
| Extracted root | `C:\AITest\quarkus-main\quarkus-main` |
| Archive SHA-256 | `a5213981db5007a42eae9ab5b3c3a8f7e953fbccd15841ad3b915e024d5b10cc` |
| Recorded download URL | `https://codeload.github.com/quarkusio/quarkus/zip/refs/heads/main` |
| Recorded referrer | `https://github.com/quarkusio/quarkus?utm_source=chatgpt.com` |
| Embedded project version | `999-SNAPSHOT` |
| Embedded SCM URL | `git@github.com:quarkusio/quarkus.git` |

The extracted root has no `.git` metadata. The `main` URL component and embedded SCM
metadata identify the intended project and mutable branch, but do not prove an
immutable commit, tag, or checkout branch. Git clean/dirty state cannot be determined.
No `.gitmodules`, `.lfsconfig`, LFS attributes, or LFS pointer signatures were
observed, but operational submodule and LFS checkout state cannot be reconstructed
without Git metadata. Generated `.atlas` data is present and was not in the archive,
so the extracted directory is not byte-identical to the downloaded archive.

## Legacy local benchmark evidence

The following repository-local paths are ignored operational evidence and are not
canonical baselines:

- `benchmarks/results/m1-apache-maven.json`
- `benchmarks/results/m1-quarkus-replay.json`
- `benchmarks/Maven/`

The two M1 manifests correctly retain `repository.commit` as `null` and
`repository.revision_verified` as `false`; the archive URLs and checksums cannot be
substituted for a Git commit. The Quarkus replay has no linked eligible fresh-analysis
manifest, so its source-manifest hash remains `null`. They remain distinct from the
accepted schema-2 records now tracked in `benchmarks/baselines/`; the accepted run
evidence is recorded in `M1_1_VALIDATION_REPORT.md`.

The older Maven archive under `benchmarks/Maven/` contains an unresolved-path run,
two records with blank Git commit and branch fields, and a failed partial 73-project
run. It is useful only for historical debugging and must not be promoted into a
canonical baseline.

## JUnit status

The previously used local path
`C:\Users\MoughorOC\Documents\AITest\JUnit\junit-team` is unavailable. The
documented 41-project JUnit validation is historical evidence only; no current local
JUnit corpus, Git identity, or benchmark manifest was available for this audit.
JUnit repository provenance fields must remain unset until a clean checkout is
acquired and pinned to a full verified commit.

## Required provenance treatment

- Use the fresh Git URL and full commit pairs above for new Maven and Quarkus
  benchmark records.
- Keep machine-local paths operational and noncanonical. A logical checkout identity
  may describe a controlled placement without persisting the physical path.
- Record `master` and `main` only as acquisition context; never use them as stable
  revision identities.
- Do not infer a release tag from project versions, branch archives, or `git describe`.
- Do not attach the fresh checkout identities to legacy snapshots or manifests unless
  the artifacts are reproduced from those exact checkouts.
- Keep commit, revision verification, tag, branch state, and Git dirty state unknown
  for the legacy archives.
- Preserve the legacy evidence as provisional history; establish new baselines only
  from verified captures against the fresh pinned checkouts.
