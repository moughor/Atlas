# Benchmark Lab HWBOT Workspace V1

## Status

PR152 defines the first HWBOT-first Atlas AI OC Benchmark Lab workspace.

It is a local companion application. It is not an embedded copy of HWBOT and it
does not acquire benchmark sources from the network.

## Product contract

The primary workflow is:

```text
external HWBOT browsing
  + explicit HWBOT reference URL
  + user-selected saved source HTML
  -> Atlas source-specific parser
  -> deterministic evidence and comparison
  -> exact Fire Strike calculation and sensitivity
```

The large left workspace is organized around HWBOT navigation and local HWBOT
evidence. Atlas Intelligence is the sidecar. The calculator remains visible
below both surfaces.

## Embedding boundary

Representative HWBOT pages prevent framing by a localhost application. V1 does
not bypass those browser protections.

The central source panel is labeled:

`ATLAS SOURCE VIEW — NOT LIVE HWBOT`

HWBOT browsing, search, and fixed quick actions open as top-level external
navigation with `noopener,noreferrer`. There is no iframe, reverse proxy,
security-header stripping, cookie forwarding, credential forwarding, or DOM
injection.

## HWBOT Search

HWBOT Search creates only:

```text
https://hwbot.org/search?query=<percent-encoded-query>
```

The origin and path are fixed. Browser URL encoding supplies the query. Atlas
does not fetch or present the returned results as Atlas data.

Fixed HWBOT quick actions cover Home, Fire Strike, Fire Strike Rankings,
Submissions, and Members. Each destination uses a fixed HTTPS HWBOT URL.

## HWBOT reference URL

The input is explicitly named `HWBOT reference URL`. Atlas cannot observe the
active external browser tab.

The detector accepts only HTTPS URLs on `hwbot.org` or the narrowly normalized
`www.hwbot.org` host. It rejects credentials, nonstandard ports, controls,
backslashes, encoded paths, and malformed known Fire Strike submission routes.

A detected Fire Strike submission path produces navigation context such as:

```json
{
  "authority": "navigation_only",
  "status": "url_detected_unparsed",
  "source_identifier": "source:hwbot",
  "route_family": "fire_strike_submission",
  "path_submission_segment": "6026699",
  "semantic_evidence": false
}
```

The query and fragment never provide a path identity. The path segment remains
unverified and never becomes `CapturedSourceV1`, `SubmissionIdentityV1`, or
field evidence.

When a path segment differs from a parser-authoritative HWBOT native submission
identifier, V1 shows both values and a warning. It does not repair or alter the
parser result.

## Capture state

The user-facing state machine is:

```text
NO SOURCE CAPTURE
URL DETECTED — NOT EVIDENCE
CAPTURE UPLOADED — PARSING
CAPTURED AND PARSED
PARSE FAILED
```

Only exact user-selected HTML bytes feed `CapturedSourceV1`. PR148 remains the
sole HWBOT Fire Strike evidence parser and PR149 remains the sole UL / 3DMark
Fire Strike evidence parser. Raw captures are not persisted or returned to the
browser.

## Atlas Search — Current session

V1 searches at most the two currently parsed projections in deterministic
HWBOT-then-UL order. Results are capped at two.

Searchable values are:

- benchmark identity;
- source label and source identifier;
- native source identity;
- deterministic submission identity;
- uniquely observed normalized score values.

Queries are NFC-normalized, case-insensitive, nonempty, and limited to 128
Unicode characters. Raw HTML, the filesystem, historical workbooks, missing
fields, and conflict alternatives are not indexed. There is no database or
persistent search index.

The empty state explicitly says that historical Benchmark Intelligence is not
indexed yet.

## Atlas Intelligence sidecar

The sidecar has four views.

### Atlas

Shows URL detection separately from capture state, then parsed benchmark,
native identity, overall score, and capture hash. Analyze is enabled only after
parse and means deterministic evidence inspection, not an AI recommendation.

### 3DMark

Accepts saved UL result HTML, shows PR149 evidence, opens the parser-derived
canonical external result, and can load uniquely observed component scores into
CURRENT and WHAT IF.

### Compare

Reuses the PR151 deterministic source comparison. Score agreement is not run
identity. `run_linkage` remains `unknown`.

### Evidence

Shows field state, raw and normalized values, unit, locator, source identifier,
native identity, capture SHA-256, conflict alternatives, submission identity,
and canonical SHA-256 through the existing bounded projections. It never shows
raw third-party HTML.

## Fire Strike workspace

CURRENT and WHAT IF each contain Graphics, Physics, and Combined component
scores. One atomic server request carries one immutable pair of input snapshots.
PR150 calculates both Overall scores, absolute delta, and percentage delta.

The browser contains no Fire Strike constants or scoring formula. Server-side
`calculate_fire_strike_score` remains the only scoring authority.

Rounded negative percentage zero is presented as `0.00`; scoring semantics are
unchanged.

## Component sensitivity

For every positive integral component score:

```text
increment = ceil(component / 100)
candidate = component + increment
```

The implementation uses equivalent integer arithmetic and delegates the
baseline and each candidate Overall to PR150. It holds the other two components
unchanged.

The UI calls this `+1% sensitivity, rounded up to a whole mark` and labels the
maximum delta as `Largest modeled component-score effect`. Ties retain fixed
Graphics, Physics, Combined order. This is deterministic score sensitivity, not
an overclock recommendation.

For the authorized reference vector:

| Component | Baseline | Candidate | Overall | Delta |
| --- | ---: | ---: | ---: | ---: |
| Graphics | 22447 | 22672 | 20497 | +139 |
| Physics | 56270 | 56833 | 20369 | +11 |
| Combined | 7668 | 7745 | 20412 | +54 |

The PR150 baseline Overall is 20358.

## Asynchronous state

The browser uses per-operation monotonic generations and abort controllers.
State mutation, detection, search, and calculation responses are applied only
when their generation is still current. Score input changes invalidate a
pending calculation. Reset invalidates all outstanding channels.

This prevents an older response from overwriting a newer UI state. The server
continues to apply its existing atomic parse-before-replace behavior.

## Local security

The PR151 security boundary remains unchanged:

- bind only to `127.0.0.1`;
- fixed route allowlist;
- exact Host and Origin checks;
- request token protection;
- singleton security headers;
- bounded bodies and exact content types;
- no CORS;
- restrictive CSP and `X-Frame-Options: DENY`;
- no filesystem fallback;
- no capture persistence;
- no network acquisition;
- no arbitrary redirects.

Untrusted values are rendered with `textContent`. External destinations are
fixed or constrained to a narrow HTTPS host allowlist.

## Explicit exclusions

V1 does not implement target-score solving, live acquisition, HWBOT embedding,
browser extensions, a desktop shell, persistent indexing, historical corpus
search, generic source registries, hardware normalization, result-validity
modeling, cross-source run linkage, formulas in JavaScript, Elmor runtime calls,
recommendations, or Atlas Platform changes.

Elmor remains an external reference link. Atlas is the calculator authority.

## Future work

The next calculator extension may solve required component scores for a target
Overall, but every result must be verified through the exact PR150 scorer. A
later acquisition contract may connect an external browsing companion to saved
captures without weakening the evidence boundary.
