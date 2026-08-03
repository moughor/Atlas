# PR135 verification

## Baseline and roadmap compliance

PR135 started from clean commit
`c9b6b13cc5cd0520bd9e5576ba374172f21accb6`. At baseline, `HEAD` matched
`origin/main`, and `moughorai` resolved under this checkout. The authoritative
roadmap was not modified.

The implementation is limited to deterministic semantic search. It reuses the
PR129 canonical `KnowledgeGraph`, PR134 `CanonicalSubjectResolver`, PR130 evidence
and confidence contracts, compatible PR128/PR130--PR132 findings, semantic
snapshots, and M2 measurement. It adds no graph, resolver, source parser, LLM,
embedding/vector service, report-text index, global cache, or PR136 impact logic.
The pre-implementation audit is in `docs/PR135_EXISTING_CAPABILITIES.md`.

## Architecture and contracts

The feature-local immutable index is rebuilt from a checksum-verified snapshot.
It indexes canonical identities, bounded normalized tokens, exact kinds and
scopes, allowlisted structured facts, compatible findings, and traceable graph
relationships. Scope constraints are predicates over immutable postings rather
than materialized full-project result sets. The index identity includes snapshot
lineage, the raw PR129 graph digest, producer/schema versions, concept-registry
version, configuration, and supported languages.

`SemanticSearchRequest`, `SemanticSearchResponse`, and `SemanticSearchService`
are additive version-1 exports from `moughorai.public_api`. PR25 construction and
`search()` behavior remain unchanged. DTO restoration rejects malformed arrays,
wrong item types, dangling evidence, and inconsistent component/total scores.

The fixed full-precision relevance weights are:

| Component | Weight |
|---|---:|
| exact canonical identity | 0.35 |
| lexical match | 0.25 |
| intent fit | 0.15 |
| graph proximity | 0.15 |
| evidence quality | 0.10 |

Unavailable components are not negative evidence. Active weights are
deterministically renormalized; lexical-only non-exact scores are scaled by a
fixed factor of 0.39. This preserves their relative ordering while keeping the
maximum below the first evidence-backed confidence tier, and the published score
remains the exact sum of its components.

## Source-free and adversarial verification

Only allowlisted structured symbol fields are consumed. Canonical edge evidence
must match an established PR27/PR129 reference family; accepted values are
published only as fixed graph lineage plus a deterministic SHA-256 reference ID.
Raw edge text, arbitrary project/language metadata, source paths, report prose,
Explain prose, diagnostics, exceptions, host/user strings, and absolute paths are
not retained.

Focused adversarial tests cover lookalike names without semantic evidence,
unknown/custom annotations, absent call evidence, duplicate identities, malformed
DTOs, hostile project/language/edge strings, provider-detail leakage, candidate
and adjacency bounds, exact subtype evidence, ambiguous `used by`, multi-token
unknown subjects, and resolver ambiguity beyond its display bound. Elasticsearch
returning no REST, security, or SQL semantic hits is preserved as an honest
insufficient-evidence outcome; the engine does not manufacture matches from names
or benchmark expectations.

## Test execution

Commands actually executed during development:

```text
python -m pytest -q -p no:cacheprovider --basetemp=.pytest_pr135_focused_final \
  tests/test_pr135_semantic_search.py \
  tests/test_pr135_semantic_search_cli.py \
  tests/test_pr135_semantic_search_adversarial.py \
  tests/test_pr25_semantic_search.py \
  tests/test_pr105_public_api.py
```

Result: **104 passed in 1.07s**.

The related PR25/27/105/111/127--135 and M2 regression selection was also run:
**396 passed in 6.08s**. The final complete-suite result is recorded below after
the single required final execution.

<!-- FULL_SUITE_RESULT -->
The complete suite was executed exactly once after the focused and benchmark
validation:

```text
python -m pytest -q -rs -p no:cacheprovider --basetemp=.pytest_pr135_full_final
```

Result: **4005 passed, 3 skipped in 25.53s**. Pytest emitted no warnings. The
three skips are the expected Windows privilege limitations: one directory-symlink
test in `test_gradle_recursive_membership.py`, one file-symlink test in
`test_java_fixture_source_selection.py`, and one file-symlink test in
`test_production_review_remediations.py`.

## Benchmark search validation

All benchmark searches loaded existing snapshots read-only, built one index per
snapshot, ran every query twice on the warm service, asserted byte-identical JSON,
and asserted that the resolved checkout path was absent from each response.

| Repository | Accepted analysis state | Snapshot bytes | Indexed subjects | Index build | Slowest warm query |
|---|---:|---:|---:|---:|---:|
| Apache Maven | 92/92 | 33,715,785 | 24,282 | 3.967666s | 0.148317s |
| Quarkus | 1442/1442 | 337,186,920 | 149,048 | 28.393339s | 0.273157s |
| Spring Framework | 29/29 | 146,029,291 | 104,095 | 19.254374s | 0.263241s |
| Elasticsearch | 545/545 | 544,047,043 | 355,782 | 93.321507s | 0.353379s |

Maven queries were `plugin`, `dependency`, `repository`, `CLI`, and
`model builder`. Quarkus used `REST endpoint`, `dependency injection`,
`Hibernate`, `Kafka`, and `configuration`. Spring used `controller`,
`transaction`, `cache`, `scheduler`, and `dependency injection`. Elasticsearch
used `REST endpoint`, `transport action`, `index`, `security`, and `SQL`.

These search measurements were replayed after the final bounded-retrieval and
monotonic lexical-ranking changes. Candidate and hit counts remained stable, and
both executions of every query produced byte-identical canonical JSON.

Maven and Quarkus analysis were freshly executed in this PR validation and
completed 92/92 and 1442/1442 respectively. Spring's retained accepted run reports
29/29. Elasticsearch's reviewed accepted baseline reports 545/545 and its current
compatible snapshot contains 545 projects. No complete IntelliJ snapshot exists,
as required after failure: the retained run reports 119 projects, 118 succeeded,
and the accepted root `idea` failure. PR135 does not hide or alter that limitation.

The measured build cost justifies keeping PR135's index feature-local and
rebuildable for now. Repeated canonical-candidate projection and repeated safety
validation of the same PR130 evidence were removed after profiling. A persisted
index remains deferred until existing feature-cache contracts and invalidation can
be adopted without a second persistence framework.

## Maintainer decisions

| Area | Decision | Rationale |
|---|---|---|
| query interpreter | keep | Bounded deterministic grammar; ambiguity and unknown meaning stay explicit. |
| concept registry | keep | Compact, versioned aliases whose classifications require structured evidence. |
| search index | keep | Immutable source-free projection over existing canonical owners. |
| ranking | keep | Central documented weights, exact component accounting, deterministic ties. |
| resolver integration | keep | PR134 remains authoritative; PR135 only expands bounded candidates. |
| persistence | defer | Warm queries are interactive; a new global cache is unjustified. |
| CLI | keep | Provider-free human/JSON output follows existing exit conventions. |
| documentation | keep | Defines evidence rules, capability degradation, API, and measured limits. |

## Remaining limitations

- Relational search covers only safe, traceable canonical edges actually present;
  missing calls or composition never establish absence.
- Generic inheritance cannot distinguish `extends` from `implements` without an
  exact producer reference.
- Older or incompatible provider reports degrade to partial/unavailable.
- The fixed concept vocabulary is intentionally incomplete.
- Large snapshots have material one-time rebuild cost; warm retrieval remains
  bounded and interactive in the measured repositories.
- IntelliJ search cannot be replayed without a complete compatible snapshot.

PR136 functionality was not added. The next PR should begin only after an
independent roadmap and baseline review.
