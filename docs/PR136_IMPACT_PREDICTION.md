# PR136 Deterministic Impact Prediction

## Scope and ownership

PR136 provides bounded, deterministic impact prediction over facts already produced
by Atlas. It does not parse source, discover new dependencies, create graph edges, or
infer relationships from names. The PR129 `KnowledgeGraph` remains the canonical
repository graph and PR134 `CanonicalSubjectResolver` remains the canonical identity
service.

The minimum inputs are a checksum-verified semantic snapshot, its compatible PR129
graph, and PR134 resolution. Compatible PR131 reachability and PR132 risk reports are
optional context. PR136 v1 defines bounded Git/search request flags and capability
states but has no compatible Git or PR135 injection adapter; both therefore report
`unavailable` and neither service is executed. No LLM is used.

PR136 does not implement PR137 refactoring recommendations or any later roadmap
capability.

## Architecture

The snapshot-backed flow is:

```text
AtlasSemanticSnapshot
  -> CanonicalSubjectResolver.from_snapshot()
  -> existing PR129 KnowledgeGraph and graph digest
  -> immutable, feature-local impact configuration
  -> subject resolution
  -> authoritative direct-edge selection
  -> bounded relation-aware traversal
  -> evidence and confidence projection
  -> deterministic ranking and response
```

The implementation reuses the graph's existing incoming and outgoing adjacency. It
does not copy the graph into another model or build an unbounded transitive closure.
The resolver's restored graph is used so malformed nodes, duplicate identities,
dangling relationships, unsupported schemas, and source-free identity projection
follow the PR134 contract.

The legacy PR26 `ImpactAnalysisService` and the specialized Java impact service remain
available and unchanged. They are not silently reinterpreted as PR136 evidence. A
specialized producer may contribute only through an explicit compatible adapter whose
endpoints resolve to canonical PR129 subjects.

## Request contract

`ImpactPredictionRequest` identifies one primary source subject by canonical ID or a
PR134 query and may include a bounded tuple of additional exact source queries. Every
requested source must resolve before traversal begins. The request may also add
structured kind, project, language, package, or module constraints and bounded
options such as:

- change kind;
- maximum traversal depth;
- result limit;
- permitted relation kinds;
- whether test, dependency, or compatible risk context is requested.

Supported change kinds are bounded values such as `implementation`, `signature`,
`visibility`, `removal`, `rename`, `move`, `dependency`, `inheritance`,
`configuration`, and `unknown`. A specific change kind is never inferred from a name
or from the current graph. `unknown` means that Atlas can report structural exposure
without claiming a more precise compatibility consequence.

All integer and floating-point fields are strictly typed and bounded. Booleans are
not accepted as integers. Unknown enum values, non-finite numbers, absolute paths,
and malformed collection shapes are rejected.

## Resolution semantics

Resolution order and identity are owned by PR134:

1. exact canonical ID;
2. exact qualified name under supplied constraints;
3. unique normalized name;
4. deterministic bounded ambiguity candidates.

PR136 never selects the first ambiguous candidate. An ambiguous, not-found,
unsupported, or unavailable source produces a valid response with no fabricated
impact path. A caller can retry with a canonical ID or narrower structured scope.

PR135 discovery remains an extension point. PR136 v1 does not execute or inject it,
and a future search rank could not become canonical identity or resolve ambiguity by
itself.

## Evidence authority taxonomy

Source-free and traceable evidence is necessary but not sufficient for impact. PR136
also verifies that the evidence family is authoritative for the relationship being
used.

| Evidence class | Examples | Permitted use |
| --- | --- | --- |
| Authoritative direct relationship | resolved canonical dependency, inheritance, override, import, or authoritative call edge | direct impact and bounded propagation |
| Authoritative structural relationship | explicit ownership, membership, project/module hierarchy, public-surface ownership | aggregation, scope, and API context; not behavioral fan-out |
| Compatible analyzer context | PR131 paths and coverage, PR132 risk findings | coverage, confidence limitations, and prioritization only |
| Weak optional context | future compatible PR135 relevance or Git co-change adapter | candidate discovery or review ordering only; unavailable in PR136 v1 |
| Unsupported or unsafe input | names, package similarity, arbitrary metadata, LLM prose, raw edge text, incompatible producer data | no impact conclusion |

The canonical evidence families currently understood are:

| Relation | Authoritative production evidence | Boundary |
| --- | --- | --- |
| `depends_on` | workspace project dependencies and declared dependency records with canonical endpoints | proves a declared potential dependency, not runtime use |
| `imports` | uniquely resolved structured import metadata | Java imports are not normally persisted; ambiguous and external targets are omitted |
| `inheritance` | resolved Java extends/implements or Python bases metadata | external and ambiguous bases remain unknown |
| `overrides` | conservative resolved Java override metadata | unannotated, erased-generic, external, and ambiguous cases remain unknown |
| `calls` | canonical edges carrying the exact producer-bound `moughorai.call_graph.v1:calls` marker | the normal snapshot pipeline does not populate canonical calls; repository-wide coverage remains unknown |
| `ownership` / `member_of` | explicit PR129 container and owner relationships | aggregation only; never sibling reachability |
| `composition` | no reliable normal producer | unsupported for propagation |

Generic fallback strings such as `calls` and `semantic_graph:calls` are safe to hash
but do not establish producer authority or call coverage. Missing, rejected, or incompatible
edge evidence reduces capability; it is never interpreted as evidence of no impact.

Every retained PR136 conclusion cites deterministic evidence IDs. Public responses
project accepted graph evidence into bounded one-way references rather than copying
raw producer text. Compatible upstream evidence is accepted only when its producer,
schema, graph digest, subject binding, and canonical evidence identity match.

## Relation propagation matrix

Canonical edge direction is significant. `calls`, `imports`, `inheritance`,
`overrides`, and `depends_on` point from consumer or child to provider or parent.
Impact normally travels through their incoming direction when the provider changes.

| Changed subject | Change kind | Canonical relation and direction | Propagate | Classification and boundary |
| --- | --- | --- | --- | --- |
| method | implementation | incoming authoritative `calls` | yes | caller behavioral impact; unavailable without call coverage |
| method | signature, removal, visibility | incoming authoritative `calls` | yes | caller source/API compatibility impact |
| method | signature, removal, visibility | incoming `overrides` | yes | overriding member compatibility impact |
| method | implementation | outgoing `calls` | no | a callee is not affected merely because the changed method invokes it |
| overriding method | implementation | outgoing `overrides` | no | the ancestor declaration is not affected by an overriding implementation |
| type | signature, removal, inheritance | incoming `inheritance` | yes | subtype structural/API impact |
| type | implementation | incoming `inheritance` | no in v1 | inherited-behavior or authoritative call evidence would be required; inheritance alone does not prove execution |
| package, type, or module | supported structural change | incoming `imports` | yes | importer source/build impact; not runtime behavior |
| dependency coordinate | dependency change | incoming `depends_on` | yes | declaring consumer dependency impact, qualified by represented scope |
| project or module API | signature, removal, dependency | incoming `depends_on` | yes | reverse dependent project/module impact |
| project or module implementation | implementation | incoming `depends_on` | conditionally | declared dependency exposure, not proven runtime impact |
| member | any | outgoing `member_of` or matching incoming `ownership` | aggregate only | owning type/module/project may be listed as affected scope; traversal stops |
| container | any | outgoing `ownership` | no | a container change does not make every child or sibling affected |
| any | any | `related_to`, `provides`, `belongs_to`, `represents` | no | contextual relationships do not establish impact |
| any | any | same name or same package without an edge | no | no evidence-backed relationship |

Transitive traversal may continue only across another permitted propagation row. It
cannot use ownership as a bridge into siblings, treat framework presence as a call,
or mix search relevance into a graph path. A path that begins with an override may
continue to authoritative callers of that overriding method. Reverse project
dependencies may continue through dependent projects while the configured depth and
candidate bounds permit it.

Traversal is cycle-safe and records a bounded canonical path. Shorter paths rank
before longer paths. For equal lengths, stronger authoritative evidence ranks before
weaker evidence, followed by stable relation and canonical-subject ordering. Cycles
never cause the source subject to reappear as an impacted result.

## Immutable response semantics

`ImpactPredictionResponse` is immutable and contains:

- the normalized request, primary PR134 resolution, and bounded additional
  resolutions;
- explicit availability or ambiguity state;
- direct and transitive findings;
- affected API, test, dependency, project, module, and package projections when
  supported;
- possible breaking-change classifications;
- capability and coverage records;
- exact retained and omitted counts within evaluated bounds;
- traversal truncation and unavailable-analysis notices;
- score components, confidence, evidence IDs, and limitations;
- producer, schema, graph, configuration, and snapshot-lineage identities.

Each finding identifies the canonical impacted subject, impact category, direct or
transitive status, path length, relation sequence, canonical path, confidence, score,
and limitations. Partitions reference the same immutable findings rather than
creating contradictory copies.

Serialization is canonical and source-free. For a valid response:

```python
response.to_dict() == ImpactPredictionResponse.from_dict(
    response.to_dict()
).to_dict()
```

All referenced evidence must exist, every evidence record must reproduce its own
deterministic ID, and the response evidence index contains the exact retained
closure. Dangling, conflicting, tampered, or unused evidence is rejected. Reordered
inputs cannot change canonical JSON bytes.

An output limit applies after bounded traversal. If traversal itself reaches a hard
bound, counts beyond that bound are unknown and the response says so; it never labels
an unknown remainder as an exact zero.

## Confidence and ranking

PR136 reuses the shared PR130 `EvidenceRecord`, `EvidenceIndex`,
`ConfidenceCalculator`, and confidence tiers. It does not add another confidence
model. Coverage, agreement, ambiguity, and explicit limitations affect confidence
only through the shared deterministic contract. Path confidence cannot exceed the
weakest required relationship coverage.

Impact score is a deterministic ordering of already evidence-backed findings. Its
central components may include directness, path length, relationship authority, API
exposure, test-link strength, and represented dependency scope. Missing optional
components are excluded rather than treated as adverse zero values. Full precision
determines order; display rounding cannot change ties. Canonical subject ID is the
final tie-breaker.

Compatible PR132 risk may reprioritize established findings and provide review
context. It cannot create or remove an impact relationship. Git and PR135 enrichment
are unavailable in PR136 v1; any future compatible adapter must keep them capped as
weak context that cannot outrank or create an authoritative direct impact.

## API and breaking-change boundaries

Breaking-change status is one of:

- `proven_breaking` when compatible structured before/after evidence establishes the
  change and the supported compatibility rule;
- `potentially_breaking` when a requested scenario affects a represented
  public/protected surface but complete compatibility evidence is absent;
- `not_evaluated` when the required API or change evidence is unavailable;
- `unsupported` when Atlas has no authoritative rule for the represented subject;
- `not_applicable` when the represented scenario is outside an exposed API surface.

The PR136 v1 snapshot-backed service cannot produce `proven_breaking` because it has
no compatible before/after API-diff producer.

A hypothetical request states a scenario; it is not itself a proven diff. Public or
protected visibility prevents a false safety claim but does not prove that the
symbol is an externally supported API. Repository-local absence of consumers never
establishes external compatibility. When appropriate, the response states:

```text
No affected in-repository consumer was proven. External consumers may still exist.
```

PR136 does not claim binary compatibility without bytecode/API-diff evidence, and it
does not claim source compatibility from names or graph proximity.

## Test-impact boundaries

Tests are separated into:

- directly linked tests, supported by explicit test-to-subject or authoritative
  call/reference evidence;
- structurally related tests, supported by explicit ownership or scope facts;
- weak suggestions, reserved for a future compatible relevance or co-change adapter;
- unavailable test linkage.

Only direct references can produce strong test-impact confidence. The same project,
module, package, vocabulary, or test name is prioritization evidence at most. If call
coverage or per-symbol test classification is absent, PR136 reports that test impact
was not evaluated instead of returning an empty definitive set.

## Dependency and module boundaries

Dependency nodes retain PR129 identity, including represented ecosystem, version,
scope, and optional status. Distinct versions or scopes are never merged by PR136.
Unknown or legacy placeholder values are preserved and disclosed; they are not
upgraded into fabricated resolution. A declared dependency establishes potential
build/source exposure, not runtime linkage.

Test, optional, compile, and runtime scopes are distinguished only when the canonical
metadata represents them. A test-scoped declaration cannot become a production
runtime-impact claim.

Current PR129 module nodes are frequently project-derived module-like containers,
not complete build targets or source-set identities. Module aggregation is therefore
partial unless stronger identity is supplied. The accepted IntelliJ duplicate-type
case remains an explicit limitation:

```text
Module-level impact may be broader than represented.
```

## Capability and coverage states

Every evaluated domain reports one of `available`, `partial`, `unavailable`,
`incompatible`, or `unsupported`.

| Capability | Available when | Conservative degradation |
| --- | --- | --- |
| canonical subjects | compatible PR129 graph and PR134 resolver | malformed or absent graph is unavailable/incompatible |
| dependencies | authoritative canonical dependency edges exist | declaration scope or transitive coverage may be partial |
| inheritance | authoritative resolved inheritance edges exist | unsupported languages and external bases are partial/unavailable |
| overrides | authoritative resolved override edges exist | absent coverage is unavailable, not no overrides |
| calls | producer-bound canonical calls from `moughorai.call_graph.v1` exist | normal snapshots usually report unavailable; represented scope has unknown repository-wide coverage |
| API surface | compatible visibility/publication and change evidence exist | visibility alone is partial; binary checks are not evaluated |
| tests | explicit test classification and reference evidence exist | structural suggestions are partial; missing calls are unavailable |
| modules | independent module identity is represented | project-derived modules remain partial |
| PR131 reachability | producer/schema/graph/evidence bindings are compatible | otherwise unavailable or incompatible |
| PR132 risk | producer/schema/graph/evidence bindings are compatible | otherwise omitted from ranking and reported unavailable/incompatible |
| Git | no compatible PR136 v1 adapter | `--git-context` records the request but reports unavailable; never a structural edge |
| PR135 search | no compatible PR136 v1 adapter | `--search-enrichment` records the request but reports unavailable; never impact proof |

The critical rule is always:

```text
missing edge != no impact
```

## CLI and Python API

The provider-free CLI is intended to support:

```powershell
atlas impact "com.example.UserService"
atlas impact "com.example.UserService" --change signature
atlas impact "dependency:maven:example" --depth 3 --limit 50
atlas impact "com.example.UserService" --tests
atlas impact "com.example.UserService" --additional-subject "com.example.UserRepository"
atlas impact "com.example.UserService" --json
atlas impact "com.example.UserService" --explain-score
```

Human output is compact and deterministic. `--json` emits canonical response JSON.
Ambiguity, no proven impact, and unavailable optional capabilities are valid results,
not internal errors. Malformed requests and missing or invalid snapshots follow the
existing CLI error convention and do not expose local snapshot paths or unbounded
exception text. No command requires an LLM.

`--git-context` and `--search-enrichment` record explicit capability requests, but
PR136 v1 has no compatible adapter for either input. Both therefore remain
`unavailable` and do not scan Git or build the PR135 search index.

The additive Python API is:

```python
from moughorai.public_api import (
    ImpactPredictionRequest,
    ImpactPredictionService,
    SubjectQuery,
)

service = ImpactPredictionService.from_snapshot(snapshot)
response = service.predict(ImpactPredictionRequest(SubjectQuery(canonical_id)))
```

One service instance owns immutable snapshot-derived state and supports repeated warm
queries. Public responses do not expose mutable graph internals. Existing PR26 and
Java impact imports and behavior remain backward compatible.

## Source-free and privacy guarantees

Requests, indexes, responses, rendered output, and measurements contain no raw
source, comments, arbitrary string literals, docstrings, diagnostics, unbounded
exceptions, absolute paths, usernames, hostnames, private Git remotes, or LLM prose.
Repository-relative references are retained only where existing Atlas source-free
rules permit them.

Canonical graph evidence is allowlisted, bounded, and projected through deterministic
one-way references. Arbitrary edge evidence and upstream limitation prose are not
republished. Absolute Windows, POSIX, UNC, file-URI, and repeatedly percent-encoded
paths are rejected or omitted. Git authors, commit subjects, and contributor
identities are never part of an impact response.

## Determinism and performance

For identical compatible inputs and configuration, PR136 guarantees byte-identical
JSON across repeated runs, reversed graph insertion order, reversed candidate and
evidence order, cold rebuild versus warm query, and snapshot/response round trips.
Output contains no timestamps, random IDs, worker-completion ordering, or hash-table
iteration order.

Traversal is bounded by depth, visited subjects, candidate paths, retained findings,
and evidence references. It uses existing adjacency, cycle checks, canonical
ordering, and top-k selection rather than all-pairs paths or centrality. Ownership
aggregation is terminal and cannot expand to a repository subtree.

M2 measurement is opt-in and semantically inert. Stable feature phases are
`impact_prediction.resolver_index`, `impact_prediction.index`,
`impact_prediction.query`, `impact_prediction.resolve`,
`impact_prediction.neighbors`, `impact_prediction.traverse`,
`impact_prediction.cycle_check`, `impact_prediction.direct`,
`impact_prediction.sort`, `impact_prediction.score`, `impact_prediction.evidence`,
`impact_prediction.serialize`, and `impact_prediction.render`. Measurements record work counts
such as nodes and edges visited, candidates, paths, results, retained objects, and
serialized bytes. Wall time, CPU, and optional memory observations remain operational
sidecar data and never influence semantic ordering or identity.

Snapshot loading and one-time resolver construction are reported separately from
warm query latency. PR136 does not serialize the full graph merely to fingerprint a
query; it reuses the compatible graph digest. The planning target is a bounded warm
query within one second while preserving explicit truncation rather than weakening
evidence checks.

## Persistence decision

Impact predictions depend on a subject and hypothetical or structured change. Atlas
therefore does not publish a default `impact_prediction` payload during normal
workspace analysis. Responses are ephemeral and reconstructible from compatible
snapshot facts.

No persistent impact index or global cache is introduced. This avoids snapshot
growth, stale request-specific conclusions, duplicated persistence infrastructure,
and cache invalidation that has not been justified by measurement. Loading or using
PR136 does not mutate the snapshot, its identifier, or its on-disk bytes. Older
snapshots remain readable; missing PR131, PR132, PR135, or Git context degrades only
the corresponding optional capability.

## Maintainer decisions

| Area | Decision | Reason |
| --- | --- | --- |
| existing impact services | reuse | PR26 and Java-specific services retain their contracts; PR136 is additive and snapshot-backed |
| traversal engine | keep | bounded PR129 incoming adjacency is deterministic and avoids a second graph or closure |
| API analysis | keep conservative | structured visibility supports potential exposure, while binary/source compatibility remains unevaluated |
| test prediction | keep | only internally consistent typed PR131 call/reference paths can create test findings |
| ranking | keep | centralized deterministic relation, proximity, and represented-exposure components are fully explained |
| PR135 integration | defer | no compatible source-free adapter is needed to establish structural impact, and relevance cannot create edges |
| persistence | defer | predictions are request-specific, reconstructible, and not yet expensive enough to justify invalidation/cache state |
| CLI | keep | the provider-free command exposes bounds, ambiguity, capability degradation, JSON, and opt-in profiling |

## Explicit limitations and deferred work

- Producer-bound canonical calls are normally absent, so caller and behavioral blast
  radius are commonly unavailable.
- Canonical composition has no reliable normal producer and is not propagated.
- Java imports are not normally persisted in the canonical graph.
- Complete external/public API publication and binary compatibility evidence are not
  available from visibility alone.
- Complete production-symbol-to-test linkage is not available in normal snapshots.
- Reflection, dynamic dispatch, generated linkage, framework lifecycle, and runtime
  configuration can broaden actual impact beyond represented static evidence.
- Dependency declarations do not prove runtime use, and unresolved/inherited
  versions or scopes remain unknown.
- Module/source-set identity is incomplete for repositories such as IntelliJ.
- PR131 and PR132 are consumed only when their producer, schema, graph, lineage, and
  evidence bindings are compatible.
- PR135 and Git enrichment have no compatible PR136 v1 adapter. Their request flags
  report `unavailable` and cannot create impact findings.
- No source parsing, bytecode compatibility engine, runtime tracing, ML, embeddings,
  LLM ranking, persistent cache, graph database, refactoring recommendation, or
  security analysis is added by PR136.

These limitations produce explicit partial, unavailable, incompatible, unsupported,
or insufficient outcomes. They are never converted into unsupported certainty.
