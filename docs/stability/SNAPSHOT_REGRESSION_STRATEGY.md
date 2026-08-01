# Atlas M1 Snapshot Regression Strategy

## Purpose

Snapshot regression testing protects Atlas Semantic Snapshot (ASS) integrity,
serialization, compatibility, and deterministic derived output. It does not treat
run metadata or machine paths as portable repository facts.

## Three regression layers

### 1. Tracked compatibility fixtures

Commit small, source-free `.ass` fixtures representing every supported schema and
producer boundary. Each fixture has fixed bytes, checksum, snapshot ID, semantic
payload hash, and provider-free explanation hash. Tests must:

- load through `SemanticSnapshotStore`;
- verify checksum and content-derived snapshot identity;
- reproduce the exact serialized bytes;
- assert hard-coded regression hashes;
- exercise the compatible default explanation path.

M1 adds `tests/fixtures/semantic_snapshot_v1_minimal.ass` as a minimal schema-v1
compatibility fixture. It is deliberately not a PR133/PR134 capability fixture;
focused model tests cover those current producers.

### 2. Focused canonical model goldens

Knowledge Graph, repository summary, risk, repository report, subject resolution,
and structured explanation tests compare exact `to_dict()` values and canonical
digests under reordered inputs and fresh processes. These small fixtures localize a
semantic change better than a single large ASS diff.

### 3. External repository manifests

Apache Maven, Quarkus, and future repository snapshots remain external artifacts.
Git tracks compact manifests containing provenance, counts, sizes, and defined
hashes. Large snapshots are retained as bounded CI/release artifacts when storage
permits; they are not committed as source fixtures.

## Hash and ordering contract

- `snapshot_sha256` proves exact artifact integrity.
- `snapshot_id` identifies the exact persisted capture payload.
- `semantic_payload_sha256` excludes only `snapshot_id` and
  `history_reference`; it includes schema, workspace fingerprint, analyzer version,
  and semantic context.
- `repository_report_sha256` hashes the canonical persisted report object.
- `explain_sha256` hashes the provider-free Markdown after LF normalization and one
  final newline.
- workspace project order and fresh-analysis execution order have separate hashes.
- provider-generated narrative is never a golden.

Canonical JSON uses sorted keys, compact separators, and UTF-8. The durable ASS
store and benchmark manifests reject non-finite JSON numbers. In-memory snapshots
may still carry malformed evidence so downstream compatibility paths can degrade
safely, but such a value cannot be published. Stable serialization means identical
validated payloads produce identical bytes; it does not mean separately captured
runs always have the same identity.

## Portability boundary

Raw ASS identity is not relocation invariant:

- `history_reference` changes for successive recorded analyses;
- semantic context stores the absolute workspace root;
- repository and workspace graph identities can incorporate that root;
- optional Git evidence depends on repository HEAD and available history.

Therefore raw hash equality is a correctness gate only when repository and Atlas
commits, logical and physical checkout root, initial Atlas state, Python/OS, worker
count, and cache mode are controlled. The semantic payload hash removes capture
history identity but remains path-scoped. A benchmark manifest records a
non-sensitive logical checkout identity and treats a different identity as
incomparable; it never persists usernames or absolute paths.

Atlas must not delete arbitrary fields merely to make a hash portable. M1.1 adds a
versioned portable projection for external repository baselines. It replaces only
the verified checkout root, its encoded forms, and the path-scoped workspace
fingerprint; the raw artifact hash remains an integrity record. The exact contract
is documented in `M1_1_CANONICAL_BASELINE.md`.

## Backward compatibility

- Loaders reject corrupt checksums, mismatched IDs, unsupported schemas, ambiguous
  numeric schema values, and invalid required metadata.
- Valid schema-v1 artifacts remain supported.
- Pre-save validation rejects shallowly mutated snapshot payloads before any archive
  or `latest.ass` file is published.
- Deep freezing nested context is intentionally deferred to avoid changing the
  established mapping contract without large-snapshot memory evidence.

## Drift policy

Snapshot drift is acceptable only when all of the following hold:

1. a deliberate producer, schema, or semantic contract changed;
2. the exact canonical section diff is reviewed;
3. backward-compatibility impact is tested;
4. the new result is reproduced in a comparable environment;
5. release notes and the baseline change explain the reason.

Ordering changes, hash-seed differences, worker-count races, timestamps, durations,
provider prose, silent checkout relocation, and unexplained field loss are not
acceptable semantic drift. Raw-only drift caused by a new history reference is
reported as an operational warning when all semantic gates match.
