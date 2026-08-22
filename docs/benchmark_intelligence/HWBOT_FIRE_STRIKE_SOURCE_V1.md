# HWBOT Fire Strike Source V1

Status: first production source-specific Benchmark Intelligence parser
Scope: offline HWBOT Fire Strike Standard HTML interpretation only

## Capability

`parse_hwbot_fire_strike_submission` consumes one `CapturedSourceV1` and
returns the existing `FireStrikeSubmissionV1`. It interprets a narrow,
server-rendered HWBOT submission structure without acquiring or persisting the
source.

The capture must declare exactly:

```text
source_identifier = source:hwbot
media_type = text/html
```

The parser rejects missing or different metadata before decoding. Payload bytes
are decoded as strict UTF-8 and are never normalized or rewritten.

## Supported benchmark representation

V1 requires exactly one `submission-score-wrapper` and benchmark/user anchors
inside its visible user structure. The decisive benchmark discriminator is the
anchor path:

```text
/benchmarks/3dmark_-_fire_strike
```

Absolute and relative anchor references are interpreted only for their path.
The visible label corroborates the path. Case and whitespace may vary, the
`3DMark` prefix and `Standard` suffix are optional, and a hyphen or colon after
`3DMark` is cosmetic. A label identifying another benchmark or variant is a
conflict.

Fire Strike Extreme, Ultra, Fire Strike (GPU), Custom, Stress Test, unknown
variants, and conflicting benchmark paths are rejected. They are never mapped
to Fire Strike Standard.

## Native submission identifier

The parser recovers the source-native identifier from a submission self-link
inside a `wr-ranking-grid` row. A matching row must contain:

- the same user path shown in the submission score wrapper;
- a Standard Fire Strike submission self-link;
- a link score matching an authoritative overall-score observation.

The identifier is the final path component. It must be positive ASCII decimal
text without leading zeros. Repeated references to one identifier collapse;
missing, malformed, or multiple distinct matching identifiers fail.

The user value is used only for deterministic self-link matching. PR148 does
not add a submitter field or make an ownership assertion.

## Overall score evidence

Authoritative overall observations follow the direct structural path
`submission-score-wrapper` → `div.score-wrapper` → `div.value` →
`span.score-item`. Hidden elements and score-like descendants in suggestions,
rankings, comments, or unrelated nested content are ignored.

Duplicate HTML attribute names are rejected case-insensitively before any
structural interpretation. Attribute order can therefore never select between
ambiguous `id`, `class`, or `href` evidence.

Accepted values are non-negative base-ten decimals, either ungrouped or using
three-digit comma groups. Zero is observed zero. Binary floating point,
exponents, signs, malformed grouping, and embedded unit text are rejected.
Existing Benchmark Intelligence decimal normalization removes grouping,
redundant fractional zeros, and negative-zero ambiguity.

The base locator is:

```text
//*[@id='submission-score-wrapper']//span[@class='score-item']
```

Repeated observations normalizing to one value collapse to one observed field.
Distinct normalized values produce `FieldState.CONFLICTING`, with one observed
alternative per distinct value. Alternatives use deterministic one-based
occurrence suffixes and retain the exact capture SHA-256.

## Missing component scores

The supported HWBOT representation does not directly expose Graphics, Physics,
or Combined scores. Each is therefore `FieldState.MISSING`, never zero or an
inferred value. Its evidence uses the source scope locator:

```text
//*[@id='submission-score-wrapper']
```

Every observed, conflicting, and missing field retains `source:hwbot`, the
recovered native identifier, the exact capture SHA-256, and unit `marks`.

## Source authority

PR148 treats HWBOT as authoritative only for its native submission identifier,
presented benchmark path/category, and displayed overall score. It does not
assert UL validity, formula correctness, component scores, ownership, hardware
telemetry, runtime clocks, historical eligibility, or external verification
contents.

## Fixture provenance

`tests/fixtures/benchmark_intelligence/hwbot_fire_strike_submission_v1.html` is
Atlas-authored synthetic material. Its structure is informed by inspection of
public HWBOT server-rendered pages; its user, identifier, and score are
illustrative. It copies no page, script, image, comment, advertisement,
tracking asset, cookie, credential, or real submission record.

Historical extractor spreadsheets informed variant/path regression choices
only. They are derived research material, are not committed, are not parsed by
production code, and are not field-evidence provenance.

## Boundaries and exclusions

The parser uses only the Python standard library and Benchmark Intelligence
models established by PR146 and PR147. It performs no HTTP, URL opening,
filesystem acquisition, browser automation, authentication, persistence, or
content sniffing.

V1 adds no generic parser/DOM framework, registry, plugin, spreadsheet
ingestion, hardware model, submitter/date/ranking/points model, verification
model, 3DMark parser, formula, simulation, normalization, reconciliation, CLI,
public API, or UI.
