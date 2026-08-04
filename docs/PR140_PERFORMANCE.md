# PR140 Performance

## Status

The controlled PR140 component measurement and official repository regression
benchmarks are complete. Final compile, diff, and clean-replay validation are tracked
separately in `PR140_VERIFICATION.md`.

## Measurement boundary

PR140 is request-local. It loads an existing verified snapshot, builds the shared
canonical resolver index, associates bounded Git paths, invokes compatible PR136 and
PR137 services, validates exact projection, and renders a response. It does not run
workspace analysis, publish a snapshot, invoke a provider, or persist review state.

The CLI's opt-in M2 profile records these PR140 phases where exercised:

- `change_review.git_diff`;
- `change_review.resolver_index`;
- `change_review.path_association`;
- compatible nested PR136/PR137 phases;
- `change_review.materialize`;
- `change_review.render`.

Measurement sidecars are operational artifacts on stderr/disk and do not enter the
semantic response or snapshot. The command's default sidecar is
`.atlas/measurements/latest-change-review.json`.

## Configured work bounds

These are implementation limits, not measured results:

| Work | Default | Maximum |
| --- | ---: | ---: |
| Changed files retained | 256 | 1,000 |
| Subjects retained per file | 32 | 128 |
| Subjects retained globally | 64 | 128 |
| Impact traversal depth | 4 | 64 |
| Impact findings | 100 | 1,000 |
| Architecture subjects | 8 | 32 |
| Architecture advice globally | 8 | 100 |

The global subject selection uses deterministic round-robin allocation. The global
architecture-advice bound is shared across every evaluated subject. Omitted counts
are serialized explicitly.

## Controlled response-growth results

The controlled run used one immutable fixture snapshot and semantically equivalent
sorted/reversed Git inputs with 0, 1, 25, and 250 changed files. Architecture was
disabled so the response-growth cohort isolated resolver association, feature
evidence, projection validation, and serialization. Fixture construction was
outside the measured interval.

Each cohort recorded cold request latency, repeated median and p95 latency, peak
Python allocation, peak process working set, canonical response bytes, retained
subjects, and feature evidence records.

| Files | Cold | Repeated median | Repeated p95 | Python peak | Peak working set | Response bytes | Subjects | Evidence records |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 3.0638 ms | 2.8994 ms | 2.9485 ms | 74,973 B | 57,507,840 B | 2,962 B | 0 | 0 |
| 1 | 6.7082 ms | 6.5162 ms | 6.5778 ms | 126,450 B | 57,470,976 B | 7,119 B | 1 | 3 |
| 25 | 89.4111 ms | 89.8427 ms | 90.6954 ms | 713,420 B | 58,744,832 B | 105,116 B | 25 | 75 |
| 250 | 794.1669 ms | 792.5643 ms | 801.0610 ms | 6,995,880 B | 70,340,608 B | 892,897 B | 128 | 628 |

Python peaks came from a separate tracemalloc cohort. All repeated and reordered
outputs were byte-identical within every file-count cohort.

## Snapshot compatibility measurement

PR140 has no snapshot producer. The controlled check verified this mechanically:

1. serialized the same snapshot before and after repeated reviews;
2. compared bytes, snapshot ID, semantic-context keys, and checksum;
3. confirmed that no `change_review` semantic-context key was published;
4. repeated the review with reordered equivalent input.

| Observation | Result |
| --- | --- |
| Snapshot bytes before | 1,018 B |
| Snapshot bytes after | 1,018 B |
| Byte growth | 0 B (0%) |
| Byte-content equality | Exact |
| Checksum equality | Exact |
| Snapshot ID equality | Exact |
| Semantic-context change | None; no `change_review` key |

No literal checksum is reported because that value was not retained by the
controlled summary. Equality is reported without inventing an unavailable hash.

## PR139 baseline comparison

The exact pre-PR140 baseline is PR139 commit
`2e8e27097dbcb43625639ea4234172409a8ed36c`. PR139 has no feature-identical
provider-free Git change-review request, so latency must be reported as an absolute
PR140 observation rather than a speedup or regression. The meaningful compatibility
comparison is unchanged snapshot bytes, public API, legacy `atlas ai review`, and
PR139 Ask/Chat behavior.

| Compatibility observation | Result |
| --- | --- |
| Frozen public API fixture | 8 passed in 0.33s |
| Historical compatibility matrix, including legacy AI and PR139 | 586 passed in 17.85s |

## Official repository regression observations

PR140 does not alter normal analysis semantics, but the official repositories remain
regression targets. The following values are from the executed final-candidate runs.

| Repository | Pinned revision | Project result | Analysis time | Determinism evidence |
| --- | --- | ---: | ---: | --- |
| Apache Maven | `3e01a12e9eacd2b336f4db786d54e35647ce268c` | 92/92 in both executions | Timed repeat: 30.419s | Portable, report, risk, graph, and project-order hashes exact across both |
| Quarkus | `bbc0853aef94c567bac2cc4a98d51c90fb423648` | 1442/1442 in both executions | 405.544s; 404.313s | Same five hashes exact across both |
| Spring Framework | `eceebb3077dda9e1b19d73c0398ef022cd91f99c` | 29/29 in both executions | 102.889s; 116.817s | Same five hashes exact across both |
| Elasticsearch | `273e03a8a7149170fac16761af3fbf522b52f9fe` | 545/545 in both executions | 834.242s; 818.025s | Same five hashes exact across both |
| IntelliJ Community | `6affce35cb2aad82747b36e886836c44e0188e46` | 119 discovered, 118 succeeded; only `idea` failed in both | 409.470s; 409.365s | Exact stdout and stderr; no `latest.ass` in either run |

Both Elasticsearch stderr streams contain the upstream diagnostic
`tdvt_run.py:150: SyntaxWarning: invalid escape sequence '\.'`. All 545 projects
succeeded and the five requested deterministic hashes remained exact.

IntelliJ reproduces the accepted module-identity limitation. The sole failure is
`DuplicateTypeError` for `com.intellij.testFramework.TestDataFile` in project
`idea`. Atlas correctly publishes no `latest.ass` for the unsuccessful workspace;
the two runs have exact stdout and stderr.

## Interpretation and limitations

- Resolver-index reconstruction may dominate small snapshot-only requests; it is a
  shared-platform cost and does not justify a PR140-specific cache without an
  isolated measurement and a second real consumer requirement.
- Response and evidence size grow with retained files and subjects. Hard bounds and
  omitted counts make that growth explicit.
- Git collection materializes the external diff before PR140 response bounds apply.
  This is not represented as a streaming implementation.
- Process working set includes interpreter, imports, snapshot loading, graph
  restoration, and operating-system cache effects.
- Provider latency is absent because PR140 invokes no provider.
- Repository benchmark timings are observations under their documented environment,
  not causal optimization claims.
