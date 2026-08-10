# Captured Source V1

Status: Benchmark Source Capture Foundation
Scope: exact caller-supplied bytes and narrow association metadata

## Capability

`CapturedSourceV1` is the immutable boundary between external byte acquisition
and future parsers. It retains the exact caller-supplied built-in `bytes`, and
derives SHA-256, capture identity, and byte length from that payload. It may
verify an expected digest before parser handoff.

The model does not acquire, decode, normalize, interpret, or persist payloads.
Empty payloads and arbitrary binary payloads are valid.

## Identity

Capture identity is exactly:

```text
capture:sha256:<sha256-of-exact-payload-bytes>
```

Only payload bytes participate in identity. Source association and media type
do not. URLs, filenames, retrieval timestamps, display names, HTTP headers, and
acquisition mechanisms are not represented.

An optional expected SHA-256 is a construction-time integrity check. It must be
64 lowercase hexadecimal characters. It is neither retained nor serialized.

## Byte ownership

The capture retains the caller's exact built-in `bytes` directly. It does not
decode, normalize, base64-encode, copy into a storage reference, or write the
payload. Bytes subclasses, mutable byte arrays, and memory views are rejected.

The payload remains resident for the capture's lifetime. Persistence and
large-object storage require a separately approved design.

## Association metadata

`source_identifier` is optional caller-declared metadata using:

```text
source:<lowercase-slug>
```

It may route a future source-specific parser, but it is not proof of provenance,
authority, or acquisition method.

`media_type` is an optional bare `type/subtype` value. ASCII case is normalized
to lowercase. Parameters, whitespace, missing components, invalid Unicode,
charset parsing, content sniffing, and MIME registry behavior are unsupported.

## Canonical metadata

Canonical metadata contains exactly:

- `capture_id`;
- `sha256`;
- `byte_length`;
- `source_identifier`;
- `media_type`.

Optional metadata is explicit `null`; the payload is never embedded. Existing
Benchmark canonical JSON rules provide UTF-8, normalized Unicode scalar strings,
sorted keys, compact separators, and byte-identical equivalent metadata.

## Capture and field evidence

Capture establishes which exact bytes Atlas received. `FieldEvidenceV1`
establishes how a source-specific parser derived a benchmark field from those
bytes. They remain separate:

```text
CapturedSourceV1
  -> future source-specific parser
  -> FieldEvidenceV1
  -> FireStrikeSubmissionV1
```

The PR146 fixture parser continues to accept payload bytes and an expected
digest. PR147 does not retrofit it to depend on `CapturedSourceV1`.

## Explicit exclusions

V1 provides no networking, filesystem acquisition, source/parser registry,
HWBOT/3DMark/Elmor parser, URL/timestamp metadata, persistence, database, blob
store, cache, plugin framework, evidence graph, score calculation, simulation,
hardware normalization, reconciliation, CLI, public API, or UI.
