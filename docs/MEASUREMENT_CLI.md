# Performance Measurement CLI

Measurement is disabled by default. Normal `atlas analyze` stdout remains unchanged.

Enable phase and filesystem measurement:

```text
atlas analyze . --profile
```

This atomically replaces:

```text
<workspace>/.atlas/measurements/latest.json
```

Choose another sidecar path:

```text
atlas analyze . --profile-output .atlas/measurements/atlas-profile.json
```

`--profile-output` implies `--profile`. A relative explicit path is resolved from the
current working directory. An output inside the analyzed workspace must remain under
`.atlas/measurements`; an output outside the workspace is allowed. Atlas refuses to
replace any existing target, including the default target, unless it is already a
valid M2 sidecar.

Opt in to best-effort current-process memory samples:

```text
atlas analyze . --profile --profile-memory
```

`--profile-memory` also implies `--profile`. The JSON records measured, unavailable,
or unsupported status exactly as returned by the platform probe. It does not estimate
one memory counter from another.

Opt in separately to Python allocation samples:

```text
atlas analyze . --profile-python-memory
```

Atlas starts `tracemalloc` only when it is not already active and stops it after the
last overlapping Atlas profile exits only when Atlas started it. A tracer owned by
the embedding process remains active. This option also implies `--profile`.

Profile deterministic Explain projection and snapshot loading separately:

```text
atlas ai explain . --profile
atlas ai explain . --profile-output .atlas/measurements/atlas-explain-profile.json
atlas search "REST endpoint" . --profile
atlas search "dependency injection" . --profile-output .atlas/measurements/atlas-search-profile.json
atlas impact "com.example.UserService" . --profile
atlas impact "com.example.UserService" . --profile-output .atlas/measurements/atlas-impact-profile.json
```

The default Explain sidecar is
`<workspace>/.atlas/measurements/latest-explain.json`. Provider latency is outside
the `explain.projection` phase: M2.0 measures Atlas context selection and rendering,
not remote or local LLM execution.

The default Semantic Search sidecar is
`<workspace>/.atlas/measurements/latest-search.json`. Search profiling measures
snapshot index construction and deterministic local query phases; no provider is
invoked.

The default Impact Prediction sidecar is
`<workspace>/.atlas/measurements/latest-impact.json`. Impact profiling separates
snapshot loading from deterministic resolver/index construction, bounded graph
traversal, evidence/scoring/serialization, and CLI rendering. It does not run a
provider, semantic search, Git history scan, or repository analysis.

The normal analysis report continues to use stdout. A compact human summary is sent
to stderr and identifies the sidecar kind, sample and phase counts, unavailable and
unsupported phase counts, cumulative sampled phase wall times, maximum sampled RSS,
and sampled Python allocation peak when the corresponding memory modes were requested.
`cumulative_sample_wall_ms` is inclusive sample time, not an exclusive pipeline
duration. The summary reports only `default` or `custom` output kind and does not
expose an absolute sidecar path.

A sidecar publication failure prints:

```text
profile: unavailable (sidecar-publication-failed)
```

It does not turn a successful analysis into a failure and cannot replace an existing
command error. An invalid `.json` suffix or an output inside the workspace but outside
`.atlas/measurements` remains a normal option error.

An analysis that fails after profile configuration still attempts to publish its
partial sidecar. Profiled runs remain available through `atlas history`, but their
instrumented project durations are excluded from later `--adaptive` decisions.

Example compact stderr shape:

```text
profile: samples=42 phases=12 eligible=42 sample_every=1 output=default
profile-coverage: unsupported=0 unavailable=14
profile-phase: workspace.discovery samples=1 cumulative_sample_wall_ms=8.125
```

The PR96 command is unchanged:

```text
atlas profile . --workers 2
```

It continues to emit its original deterministic elapsed-time report on stdout and is
not an alias for the M2 sidecar.
