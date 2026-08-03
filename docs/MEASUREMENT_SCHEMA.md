# Performance Measurement Schema

M2 sidecars use producer `atlas-performance-measurement/1.0` and schema version 1.
They are UTF-8 JSON with sorted keys, finite numbers, and a trailing newline.
The normative JSON Schema is
[`schemas/atlas-performance-measurement-v1.schema.json`](schemas/atlas-performance-measurement-v1.schema.json).

## Top-level fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer compatibility boundary. |
| `producer` | Measurement producer and contract version. |
| `phase_ids` | Stable registered phases plus any valid observed extension phases. |
| `phase_status` | Measured or explicitly unavailable coverage for every phase. Metric-level platform/runtime support remains separate. |
| `samples` | Immutable scope observations in canonical order. |
| `sampling` | Deterministic hash-sampling interval and eligible/sampled scope coverage. |
| `aggregates` | Status-aware deterministic per-phase aggregation with an explicit aggregation contract. |
| `filesystem` | Partial run-local observations grouped by portable consumer ID and observed totals. |

Each sample records its phase and nested scope path, consumer, worker identifier,
thread identifier, success state, and metrics. Metrics always include a unit and one
of these states:

- `measured`: contains a finite numeric `value`;
- `unsupported`: the platform or runtime does not provide the counter;
- `unavailable`: collection was disabled or no observation was recorded.

Unavailable values are never replaced with zero. Aggregates retain measured,
unsupported, and unavailable counts separately. Each aggregate declares one of:

- `sum`: additive work such as processed units or produced objects;
- `sample-sum`: the arithmetic sum of scope samples, which can overlap when scopes
  are nested or concurrent and is therefore not an exclusive pipeline duration;
- `distribution`: a gauge, ratio, boundary sample, peak, retained count, or unknown
  extension metric. Its `total` is always `null`; minimum, maximum, and average remain
  available when measured.

Current metric units are nanoseconds, bytes, count, and percent. Filesystem counters
observe explicit directory enumeration, metadata lookup, path normalization, content
read, hashing, descriptor-parse, and language-parse boundaries. `bytes_read` uses an
already-known byte length or a physical file size observed after a successful read.
Text producers deliberately avoid an extra metadata probe and record the read with
unknown size; a failed or deliberately omitted lookup increments
`content_read_bytes_unavailable` instead of fabricating zero bytes.

The filesystem object always declares `coverage.status: partial` with reason
`explicit-instrumentation-boundaries`. Its `totals` are totals of recorded ledger
events, not exhaustive operating-system I/O counters. If filesystem collection is
disabled, coverage is `unavailable/collection-disabled`, so zero counters cannot be
misread as observed zero activity. Run-local one-way resource keys publish only
aggregate unique/repeated reads and generic consumer-pair overlaps; neither paths nor
resource digests enter the sidecar. Identity is a normalized absolute-path digest
that exists only in memory for the run; path aliases and symlinks are not claimed to
be the same physical resource. Metadata lookups introduced solely to obtain physical
byte counts are separated as `measurement_metadata_lookups`.

`content_resources` reports its own exact observed coverage. The default
`resource_tracking_limit` is 100,000 identities. `resource_limit_reached`,
`untracked_reads`, `tracking_status`, and `tracking_reason` make truncation or a
caller without a resource identity explicit. Observed plus untracked reads must equal
the content-read total; consumer repeat and overlap counters are cross-validated.

Sampling never extrapolates aggregates. `sampling.eligible_scopes` and
`sampling.sampled_scopes` state exact coverage; selection hashes only the stable scope,
consumer, and caller-provided key, never nondeterministic worker assignment. Sampling
keys are not retained.

## Privacy and identity

The schema contains no source text, file path, workspace name, semantic symbol,
prompt, snapshot identity, or user identity. Sampling keys may influence deterministic
selection but are never retained. Measurement artifacts are operational evidence and
must never participate in semantic hashes or snapshot identity.

Sorted serialization provides a stable machine-readable shape. Timing, memory,
thread IDs, and sample availability are environment-dependent facts, so complete
sidecar bytes are not a deterministic semantic output.

JSON Schema validates the portable wire shape. `MeasurementReport.from_dict()` also
enforces canonical derived arrays, exact counter totals, status/reason consistency,
and exact round-trip serialization; schema validation alone does not establish those
cross-field invariants.

Run provenance and deterministic semantic-output hashes belong to the existing
benchmark manifest. A raw M2 sidecar is not independently comparable unless retained
with that manifest or equivalent source-free run metadata.
