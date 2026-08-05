# Fire Strike Submission V1

Status: first production Benchmark Intelligence domain slice
Scope: offline Atlas fixture parsing only

## Capability

`FireStrikeSubmissionV1` represents one source-owned standard 3DMark Fire
Strike submission. It records the overall, Graphics, Physics, and Combined
scores with direct field-level provenance. It does not calculate or validate a
score.

The benchmark identity is fixed to:

```text
benchmark:ul:3dmark:fire-strike-standard
```

Extreme, Ultra, Custom, Stress Test, and HWBOT Fire Strike (GPU) are different
identities and are rejected by the V1 fixture parser.

## Identity

The source submission ID is deterministic:

```text
submission:<source-identifier>:<native-submission-identifier>
```

The source identifier uses `source:<slug>`. V1 accepts only portable lowercase
native identifiers. A source URI, retrieval time, local path, score, and capture
digest do not participate in source-submission identity.

## Field evidence

Each score is one immutable `FieldEvidenceV1` carrying:

- state;
- source identifier and source-native submission identifier;
- SHA-256 of the exact supplied fixture bytes;
- JSON Pointer field locator;
- raw lexical and normalized decimal values when observed;
- unit.

Supported states are `observed`, `missing`, `unavailable`, `conflicting`, and
`not_applicable`. A conflicting field retains at least two distinct observed
alternatives. Duplicate normalized alternatives, including lexically different
representations of the same decimal, are rejected. Missing and unavailable
values have no raw or normalized value. The state tag, rather than a null or
numeric sentinel, defines their meaning. Zero is a valid observed decimal value.

## Canonical form

Canonical JSON is UTF-8 with NFC-normalized strings, lexicographically sorted
keys, compact separators, and no binary floating-point, non-finite numbers, or
non-Unicode scalar values. Normalized decimals use base-ten strings without
exponent notation, redundant fractional zeros, or negative zero. Set-like
conflicting alternatives are ordered deterministically.

The fixture parser receives bytes and an expected SHA-256. It verifies the
digest before decoding, rejects duplicate or unknown fields and unsupported
schema versions, and returns the immutable submission model. The parser does
not open files or URLs; the test harness is responsible for supplying bytes.

Reordering JSON changes the capture digest because the evidence bytes changed.
It does not change the benchmark identity, source-submission identity, or
normalized scores.

## Fixture provenance

`tests/fixtures/benchmark_intelligence/fire_strike_submission_v1.json` is an
Atlas-authored synthetic fixture distributed under the repository license. Its
values are illustrative. It contains no copied vendor HTML, screenshot,
external payload, user handle, private data, cookie, credential, or claim about
a real submission.

## Explicit exclusions

V1 does not implement acquisition, HWBOT or UL parsing, score formulas,
simulation, hardware normalization, cross-source linkage, persistence, CLI,
plugins, public API integration, Repository Intelligence models, or a generic
parser/evidence framework.
