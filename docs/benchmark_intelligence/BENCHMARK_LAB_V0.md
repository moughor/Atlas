# Atlas AI OC Benchmark Lab V0

## Outcome

Benchmark Lab V0 is the first visible local application over Atlas Benchmark
Intelligence. It combines the existing HWBOT and UL Fire Strike parsers, their
field-level evidence, a deterministic source comparison, and the PR150 exact
component-score calculator on one local page.

Launch it from the repository root:

```text
python -m moughorai.benchmark_lab
```

To select another port or avoid opening the browser automatically:

```text
python -m moughorai.benchmark_lab --port 8765 --no-browser
```

The server binds only to `127.0.0.1`. There is no host option and no remote
deployment contract.

## Source workflow

V0 is deliberately offline:

1. Save a supported HWBOT or hydrated English UL result page locally in the
   browser.
2. Select that HTML file in the matching Benchmark Lab source panel.
3. The browser sends the file's exact bytes directly to the loopback server.
4. The server constructs the existing `CapturedSourceV1` and invokes the
   existing PR148 or PR149 source-specific parser unchanged.
5. The page displays only the bounded parsed projection.

The source URL fields are reference-only. Atlas never sends them to the server
and never fetches them. Native identity continues to come from authoritative
source structure; in particular, a `/3dm/<id>` locator never replaces UL's
native `/fs/<id>` identity.

Raw capture bytes are local request data. They are not persisted, rendered,
returned, or retained in `BenchmarkLabState` after parsing. A failed
replacement upload leaves the last successfully parsed immutable submission in
place. Reset or process exit discards the bounded in-memory state.

## Source presentation

V0 does not use third-party iframes.

- HWBOT currently sends frame restrictions that block localhost embedding.
- 3DMark's public result surface can present a WAF challenge, so framing is not
  a dependable contract.
- Elmor's calculator is unversioned and remains independent corroboration.

Benchmark Lab instead shows Atlas Source Panels with native identity, presented
scores, capture SHA-256, provenance, and a fixed `Open authoritative source`
link derived from the parsed native identity. It never proxies, rewrites,
sanitizes, or renders captured third-party HTML and never bypasses browser
security.

## Evidence projection

Each source projection includes:

- benchmark identity;
- source identifier;
- native submission/result identity;
- deterministic submission identity;
- submission canonical SHA-256;
- exact capture SHA-256;
- fixed open-original URL;
- all four `FieldEvidenceV1` projections, including states, values, units,
  locators, and conflict alternatives.

It excludes source bytes, filenames, filesystem paths, entered reference URLs,
cookies, credentials, user accounts, and unrelated source metadata.

Parsing means that the captured source presented those values. It does not
establish validity, eligibility, stability, safe tuning, or ownership.

## Source comparison

`compare_fire_strike_sources` is a narrow comparison of one
`source:hwbot` submission and one `source:ul-3dmark-results` result. It is not a
generic comparison framework.

Each score predicate returns one state:

- `agreement` — both sources have one observed equal normalized value;
- `disagreement` — both sources have one observed distinct normalized value;
- `missing` — at least one source has no value;
- `not_comparable` — conflicting or otherwise non-unique evidence prevents a
  value comparison.

The original evidence states and normalized values remain visible. Missing is
not zero, and conflict alternatives are never flattened.

Run linkage is always:

```text
unknown
```

Equal scores do not prove that HWBOT and UL describe the same physical run.
PR146–PR150 contain no explicit cross-source run-linkage evidence, so V0 never
synthesizes a run identity from scores, URLs, native IDs, or capture hashes.

## Calculator and what-if

Calculator requests contain baseline and candidate Graphics, Physics, and
Combined score strings. The server delegates each set to the PR150
`calculate_fire_strike_score` contract. JavaScript contains no second Fire
Strike formula.

The response displays:

- current calculated overall;
- candidate calculated overall;
- exact integer delta;
- percentage delta rounded to the nearest hundredth using half-up ties.

The UI labels them Atlas calculated/derived values. They are never represented
as observed `FieldEvidenceV1` and do not replace the source-presented overall.
The `Load UL components` action only copies three uniquely observed UL
component values into the inputs.

## Local security boundary

The V0 server:

- binds only to IPv4 loopback `127.0.0.1`;
- exposes a fixed route allowlist and no filesystem handler;
- accepts raw capture bodies up to 32 MiB and JSON up to 64 KiB;
- requires one canonical `Content-Length` and rejects transfer encoding;
- requires exact content types;
- validates the loopback `Host` and same-origin `Origin` when present;
- requires a process-generated page token on every state-changing request;
- emits no CORS permission;
- sends CSP, frame denial, no-sniff, no-referrer, no-store, and opener-isolation
  headers;
- renders parsed values through DOM `textContent`, never `innerHTML`;
- bounds parse errors without returning source text or tracebacks.

External links use HTTPS and open with `noopener noreferrer`.

This is a single-user local prototype, not a production multi-user HTTP
service. It provides no authentication, TLS, remote binding, persistence, job
queue, or concurrent editing model.

## Architecture boundary

The pure score comparison remains in `moughorai.domains.benchmark`. The local
HTTP server and page are top-level adapter modules that import the Benchmark
Intelligence public boundary. Atlas Platform is unchanged.

The repository has no generic local HTTP host. One Benchmark Lab consumer is
not evidence for adding one to Atlas Platform. A shared host may be considered
only if a second implemented domain proves the same lifecycle, routing, body,
and security contract.

## Explicit exclusions

V0 adds no live acquisition, URL import, proxy, persistence, database, source
registry, parser registry, generic web framework, generic comparison engine,
hardware model, validity model, run resolver, cohort analysis, formula for
other variants, Elmor dependency, simulator, recommendation engine, Atlas CLI
command, public API, or remote service.
