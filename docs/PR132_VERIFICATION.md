# PR132 Verification Report

## Roadmap compliance

PR132 implements Risk and Hotspot Analysis as defined by the authoritative
implementation roadmap. It extends the PR129 canonical `KnowledgeGraph`; it
does not create another repository graph, call graph, evidence model,
confidence model, cache framework, or repository model. PR133 and later work is
not included.

The implementation reuses PR129 graph identities and relationships, PR130
semantic evidence and deterministic confidence calculation, the existing Git
context service, repository inventory, semantic snapshots, and the source-free
AI explanation projection.

## Capability status

| Capability | Status | Production evidence |
| --- | --- | --- |
| Canonical fan-in and fan-out | Partial | Traceable PR129 relationships whose producers are present in the snapshot |
| Project dependency degree | Available when populated | Canonical project `depends_on` relationships |
| Project size | Available when complete | Inventory bytes with zero recorded file-stat failures |
| Change frequency | Available when Git is available | Exact commits touching a project in the bounded Git window |
| Change-author concentration | Available when Git is available | Largest pseudonymous author share of project-touching commits in the same window |
| Complexity | Unavailable | No structured production complexity producer is connected |
| Resolved low-test density | Unavailable | No structured test-to-production mapping or coverage producer is connected |
| Call-specific degrees | Partial or unavailable | Only populated canonical call edges or an authoritative specialized producer may establish them |
| Historical trend | Unavailable unless compatible history exists | Compatible prior PR132 reports only |

Missing evidence remains unavailable and does not become a zero-risk value.
Public APIs, names, package names, LLM output, and absent call edges do not
establish risk. Structural PR129 ownership is not interpreted as human
ownership.

## Determinism and compatibility

- Risk reports, evidence, heatmaps, and ties have deterministic ordering.
- `RiskAnalysisReport.from_dict(report.to_dict()).to_dict()` is exact.
- Canonical evidence IDs are verified at the producer boundary.
- The cache key includes graph, input, producer, configuration, lineage, Git,
  scope, failure, and compatible-history identities.
- Snapshots predating PR132 remain readable and expose the feature as
  unavailable.
- Snapshot publication and AI projection remain source-free and bounded.
- The direct risk-service API can disclose explicitly supplied failed projects
  while processing other evidence. The normal semantic snapshot collector keeps
  its existing invariant and publishes only after a fully successful workspace
  analysis.

## Tests executed

Focused PR132 tests after the final implementation changes:

```text
python -m pytest -q -p no:cacheprovider tests/test_pr132_risk_hotspots.py
37 passed in 2.16s
```

Related regression tests covering repository summary, AI context/explanation,
PR114, PR118, PR127, PR129, PR130, and PR131 were executed after the final
hardening changes:

```text
119 passed in 4.09s
```

The complete Atlas suite was executed exactly once after the final production
changes:

```text
python -m pytest -q -p no:cacheprovider --basetemp=<writable-test-directory>
3550 passed, 1 skipped in 14.76s
```

`compileall` completed successfully. `git diff --check` reported no whitespace
errors; Git emitted only existing LF-to-CRLF conversion notices.

## Scale measurements

The synthetic benchmark was executed with deterministic inputs. Each measured
analysis uses a graph whose digest has not been computed; graph and symbol
construction remain outside the timer. Peak memory in this table is incremental
Python allocation memory measured by `tracemalloc` during risk analysis, not
total feature memory or process RSS.

| Graph | Edges | Repeats | Cold median | Cold p95 | Peak traced memory | Warm median | Warm p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 sparse nodes | 1,000 | 5 | 0.309882 s | 0.316432 s | 3.14 MiB | 0.003293 s | 0.003347 s |
| 10,000-node chain | 9,999 | 5 | 1.489622 s | 1.542273 s | 23.95 MiB | 0.011636 s | 0.019424 s |
| 10,000 high-degree nodes | 9,999 | 5 | 1.153340 s | 1.165878 s | 14.19 MiB | 0.011601 s | 0.017508 s |
| 100,000 sparse nodes | 10,000 | 5 | 3.413379 s | 3.553966 s | 29.03 MiB | 0.042045 s | 0.065591 s |

Warm runs preserved cache identity. A one-million-node run and peak-RSS
measurement were not executed and are not claimed.

## Apache Maven validation

The normal Atlas pipeline was executed twice against the Apache Maven
workspace:

```text
atlas analyze C:\AITest\maven-master\maven-master --force --no-recover
projects: 92
succeeded: yes
```

Both executions completed with 92 successful projects and zero failed
projects in 25.1 and 24.2 seconds. Their regenerated PR132 result hash was
identical:

```text
4b4f3ed78934fe35c5c3f11d8e231dc9b274dceee3b94eb7be2f2e7e5e39a441
```

The resulting canonical graph contained 22,427 nodes and 25,254 edges. Validated
snapshot replay removed the existing `risk_analysis` field from the current
snapshot to form its comparison baseline, then added the freshly generated
field. The exact feature delta was 155,896 bytes, from 30,820,348 to 30,976,244
bytes (0.505822%). This is a same-snapshot feature delta, not a historical
pre-PR132 artifact comparison. Three replay runs produced the same result hash:

```text
4b4f3ed78934fe35c5c3f11d8e231dc9b274dceee3b94eb7be2f2e7e5e39a441
```

Two repository-level `atlas ai explain` executions were byte-identical, exited
successfully, included a compact risk/hotspot section, and did not expose the
raw-source marker checked by the validation. Their UTF-8 output SHA-256 was
`3903ea6493838dd17ada3931767537c4b52d6a564e0278612f0728791347dcf1`.

## Quarkus validation

The normal Atlas pipeline was executed against the Quarkus workspace:

```text
atlas analyze C:\AITest\quarkus-main\quarkus-main --force --no-recover
projects: 1442
succeeded: yes
```

All 1,442 projects succeeded with zero failed projects in 375.9 seconds. The
persisted graph contained 149,048 nodes and 167,850 edges. The same-snapshot
feature-delta replay removed and regenerated `risk_analysis`, adding 162,850
bytes from 336,837,908 to 337,000,758 bytes (0.048347%). It is not a historical
pre-PR132 artifact comparison. Three replay runs produced the same result hash:

```text
12364c7b64321ead025e342d134098009cbf904727eee484359bf024a938e6b7
```

Two repository-level `atlas ai explain` executions were byte-identical, exited
successfully, included a compact risk/hotspot section, and did not expose the
raw-source marker checked by the validation. Their UTF-8 output SHA-256 was
`93b12b6f79591164910a6131e8dbdfaf0b4cedc6ce4966ec58b948060e909726`.

Git-backed metrics were unavailable in both extracted benchmark workspaces and
were correctly reported unavailable. Fan-in and fan-out were partial; complete
inventory size was available. No missing metric was fabricated.

## Deliberate limitations and deferred work

- No complexity value is inferred from graph degree, names, runtime, or LLM
  output.
- Test-file counts are not represented as test coverage or resolved test
  density.
- Change frequency uses exact project-touching commits; line churn remains
  evidence detail rather than an undocumented second score.
- Change-author concentration is a bounded history proxy, not ownership, bus
  factor, CODEOWNERS coverage, or developer performance.
- Rename-aware long-range Git history, symbol spans/LOC, production complexity
  producers, resolved coverage, predictive models, and developer scoring remain
  deferred.
- The historical JUnit benchmark workspace was not present at the configured
  local paths during this validation, so no new PR132 JUnit result is claimed.

The next roadmap item is PR133, AI Repository Report. It should consume PR132's
bounded structured findings when available and explicitly report missing
analyses as unavailable; it must not fabricate absent report sections.
