# PR135 — Deterministic Semantic Search

## Purpose and scope

PR135 adds intent-based search over structured Atlas knowledge. It locates canonical
repository subjects such as REST endpoints, scheduled work, cache participants,
dependencies, design-pattern participants, reachability findings, and risk hotspots
without reading or retaining source text. Search is deterministic, bounded,
source-free, and does not require an LLM.

This feature extends the existing `SemanticSearchService`. It does not replace exact
subject resolution, Explain Anything, specialized analyzers, or the canonical
repository graph. Existing PR25 query/hit behavior remains compatible; PR135 adds a
structured semantic response for new consumers.

PR135 explicitly does not provide grep, arbitrary full-text search, fuzzy filename
search, impact prediction, explanation generation, learned ranking, embeddings, or a
vector database.

## Authoritative structured inputs

The index is rebuilt from a compatible Atlas Semantic Snapshot (ASS). Its inputs are:

- PR129 `KnowledgeGraph` nodes, edges, stable identities, and graph digest;
- symbol identities and structured symbol metadata;
- repository, project, package, module, dependency, framework, and build inventory;
- compatible PR128 architecture findings;
- compatible PR130 design-pattern findings and evidence;
- compatible PR131 reachability findings and evidence;
- compatible PR132 risk/hotspot findings and evidence;
- the shared evidence and deterministic confidence contracts;
- PR134 `CanonicalSubjectResolver` results for exact identity and ambiguity.

PR128 and PR130–PR132 findings are optional enrichment. PR134 supplies canonical
identity resolution rather than a finding stream. A snapshot remains searchable when
one or more producers are absent, incompatible, or partial. Generated PR133
repository-report text, Explain Anything output, provider output, and other prose are
never inputs.
Specialized analyzers remain authoritative for their domains; search projects their
facts and never reconstructs them.

## Source-free boundary

Index construction and responses may retain canonical IDs, safe display and qualified
names, subject kinds, explicit project/module/package context, language, graph
relations, structured findings, a bounded response evidence index, confidence, and
limitations. They do not retain source locations. Test, generated, production,
vendored, external, and unsupported classifications are labeled only when an
analyzer or compatible PR131 finding publishes that structured scope.

Only the following symbol metadata keys are eligible for semantic indexing:

- `annotations`;
- `decorators`;
- `inherits`;
- `bases`;
- `overrides`;
- `entry_point`;
- `visibility`;
- `generated`;
- `source_set`;
- `source_scope`;
- `source_classification`;
- `test`.

Values are accepted only as bounded structured identifiers or classifications. An
unknown metadata key is ignored rather than copied into the index. This allowlist is
the privacy boundary: raw source, comments, docstrings, string literals, arbitrary
metadata, exception text, usernames, hostnames, absolute paths, report prose, and LLM
text must not enter the index or response. Repository-relative references do not count
as semantic evidence by themselves.

Language is projected separately from the canonical PR129 subject. Atlas retains only
built-in analyzer language IDs or language IDs corroborated by the structured repository
inventory; arbitrary symbol metadata cannot establish a language.

PR130–PR132 evidence records are not copied wholesale. PR135 emits a bounded
search-owned projection containing the canonical subject, the upstream canonical
evidence ID, its reliability/specificity, and a fixed provider-field reference.
Arbitrary upstream details, exception text, host/user strings, and free-form provider
limitations are not copied into a response. Metadata values, annotation identities,
edge references, candidates, retained evidence, and output hits have fixed bounds;
an omission that can affect results is reported as a limitation.

Canonical edge evidence is accepted only from the established PR27/PR129 structured
reference families. Accepted references are published as fixed `semantic_graph.edges`
lineage plus a SHA-256 reference ID; their original payload is never copied into a
response. Unknown, prose-like, absolute, or malformed edge references are ignored and
reported as unavailable/partial evidence rather than treated as proof.

## Query contract and bounded grammar

Queries are immutable. A semantic query contains raw text, deterministic normalized
terms, optional kind/project/module/package/language/relation filters,
optional minimum confidence, and a bounded result limit. Normalization uses Unicode
normalization, case folding, punctuation separation, stable token ordering where order
is not semantically meaningful, and a fixed alias registry. It does not use locale,
filesystem state, an LLM, or embeddings.

The interpreter recognizes these intent families:

- exact subject or member identity;
- repository, workspace, project, package, or module;
- dependency subjects and dependency relationships;
- architecture role and design pattern;
- typed graph relationship;
- security, risk, or dead/reachability finding;
- structured engineering concept;
- a bounded compound of one concept or relation with explicit scope/kind filters.

Representative forms are:

```text
UserService
com.example.auth.UserService
project api
dependency org.springframework:spring-web
REST endpoint in project api
Kafka consumer in module messaging
high risk method
dead class in package billing
implements UserService
extends BaseController
depends on spring-web
calls PaymentService
used by CheckoutController
```

`used by` is deliberately an ambiguous form because it could mean calls, imports,
composition, or dependency. Without `--relation`, it returns an explicit ambiguity
and no inferred hit. `implements` and `extends` are accepted only when traceable
inheritance-edge evidence establishes that exact subtype; generic inheritance
evidence supports only `inherits`.

Exact identities and qualified names are delegated to the PR134 canonical resolver.
Explicit relation verbs are mapped only to canonical relation kinds. Relational
search is evaluated only when authoritative, safely traceable edges exist. In particular, unavailable
call or composition evidence yields reduced coverage, not an inferred relationship
or a claim that no relationship exists.

Unknown syntax or concepts remain unsupported. Multiple valid interpretations remain
explicitly ambiguous and are returned in deterministic order; the interpreter never
selects an arbitrary meaning.

## Engineering concept registry

The compact, versioned registry maps supported concepts to structured evidence rules.
Initial concepts include authentication, authorization, REST endpoint, controller,
service, repository/data access, SQL, ORM, scheduling/background work, caching,
messaging, Kafka, configuration, logging, security, serialization, dependency
injection, event listener, transaction, entry point, framework extension, testing,
generated code, dead/unreachable code, design pattern, risk hotspot, and the subset of
architecture findings that carries a canonical subject reference.

Eligible evidence is limited to typed symbol properties, known annotations, resolved
inheritance or interface relationships, canonical dependencies, compatible framework
classifications, entry-point roles, canonical graph edges, and compatible structured
findings. A dependency may establish technology presence but does not prove use by an
unrelated symbol. A name or package token supplies weak lexical relevance only; it
cannot by itself produce a strong semantic match. Class names such as
`AuthenticationHelper`, `CacheService`, `BaseController`, or `schedule` therefore do
not establish the corresponding concepts.

Rules are repository-independent and versioned. Benchmark-specific names, source
snippets, and report sentences are forbidden registry inputs.

The implemented evidence rules are:

| Concepts | Required structured evidence |
|---|---|
| authentication, authorization, security | Exact allowlisted Quarkus/Jakarta/Javax/Spring security annotation, or a canonical Spring Security, Keycloak, or Shiro dependency subject |
| REST endpoint | Exact allowlisted JAX-RS, Spring Web, or Micronaut HTTP annotation, or a canonical Spring Web/RESTEasy dependency subject |
| controller | Exact allowlisted Spring or Micronaut controller annotation |
| service | Exact Spring service annotation |
| repository/data access | Exact Spring repository annotation, or canonical Hibernate/Spring Data dependency subject |
| SQL query | Exact JPA `NamedQuery`/`NamedNativeQuery` or Spring Data query annotation |
| ORM | Exact Jakarta/Javax persistence annotation, or canonical Hibernate/Spring Data dependency subject |
| scheduling, background job | Exact Spring/Quarkus scheduled or Spring async annotation; Quartz dependency subjects additionally establish technology presence |
| caching | Exact Spring cache annotation, or canonical Caffeine/Ehcache dependency subject |
| messaging, Kafka | Exact Kafka/JMS/MicroProfile messaging annotation, or canonical Kafka/Spring AMQP dependency subject |
| dependency injection | Exact Jakarta/Javax Inject, CDI, or Spring component/bean/autowired annotation, or canonical Spring Context/Inject dependency subject |
| configuration | Exact Spring, Quarkus, SmallRye, or MicroProfile configuration annotation |
| logging | Canonical SLF4J, Log4j, or Logback dependency subject |
| serialization | Exact Jackson/Micronaut serialization annotation, or canonical Jackson/Gson dependency subject |
| event listener | Exact Spring event or CDI observes annotation |
| transaction | Exact Spring/Jakarta/Javax transactional annotation |
| entry point | Explicit analyzer entry-point metadata or compatible evidence-backed PR131 root finding |
| framework extension | Compatible evidence-backed PR131 Service Loader root finding |
| testing, generated code | Exact allowlisted test/generated annotation or explicit structured source classification |
| dead/unreachable code | Compatible PR131 dead-code-candidate finding with retained evidence |
| design, Builder, Strategy pattern | Compatible PR130 finding, mapped canonical participant, and retained evidence |
| risk hotspot | Compatible graph-bound PR132 hotspot with retained evidence |
| architecture | Compatible PR128 finding from the fixed architecture vocabulary with a canonical subject reference |

Exact fully qualified allowlists and dependency-coordinate prefixes are versioned with
the index producer. A recognized simple annotation name remains weak evidence and is
explicitly limited; an unknown or lookalike fully qualified annotation is ignored.

## Index architecture and invalidation

PR135 uses one immutable feature-local in-memory index. It reuses the canonical graph
and resolver rather than creating another repository model. Indexed dimensions are
bounded representations of canonical identity, normalized name tokens, kinds, scopes,
languages, allowlisted semantic metadata, dependency/framework identities, relation
endpoints, structured findings, evidence references, and capability availability.

The index is rebuildable from the snapshot and is not added to the semantic snapshot.
PR135 introduces no persistent global cache. A future feature-local persisted form is
justified only by measured rebuild cost and must reuse existing persistence contracts.

The logical invalidation key contains, in stable order:

- snapshot identity and lineage;
- canonical graph digest;
- search producer and schema versions;
- concept-registry version;
- normalized search configuration;
- supported-language set.

Changing any component invalidates the derived index. Producer incompatibility does
not silently reuse findings; the affected capability is marked unavailable or
partial.

## Retrieval and ranking

Search normalizes and interprets the query, resolves exact identities, retrieves
bounded indexed candidates, applies structured filters, performs relation-specific
bounded graph expansion, joins compatible findings, scores each canonical graph
subject once, and sorts.

Project, module, language, and package constraints are membership predicates over
immutable postings. Queries do not construct a complete set of every subject in a
large scope before applying the candidate bound. Exact-name ambiguity expansion and
unknown multi-token lexical fallback are also bounded and report truncation.

The normative relevance weights are:

| Component | Weight |
|---|---:|
| exact identity | `0.35` |
| lexical match | `0.25` |
| intent fit | `0.15` |
| graph proximity | `0.15` |
| evidence quality | `0.10` |

Unsupported or unavailable components are excluded and the remaining applicable
weights are renormalized. Missing evidence is never scored as negative evidence.
Names alone cannot create a strong semantic result even after renormalization. Full
precision is retained in the response and canonical serialization; evidence-free,
non-exact lexical relevance is multiplied by a fixed `0.39` factor so full token
coverage remains stronger than partial coverage without reaching an evidence-backed
tier. The human renderer formats values to a compact fixed precision.

Confidence is separate from relevance. Relevance answers “how well does this subject
match the query?” Confidence answers “how strongly is the underlying conclusion
supported?” PR135 reuses the common deterministic confidence result and cannot tune,
replace, or let an LLM modify it.

Each hit exposes its score components, matched concepts, capability source, evidence
IDs resolvable through the bounded response evidence index, confidence when available,
limitations, and a compact source-free rationale through its concepts, relation
summary, capability sources, and score components. Equal
scores sort by subject kind, qualified name, then canonical ID. Candidate expansion,
relation traversal, evidence retention, and returned hits all have stable bounds;
omitted counts and truncation are explicit.

## Capability and partial-result semantics

Every producer used by a query is reported as `available`, `partial`, `unavailable`,
`incompatible`, or `unsupported`, following the established Atlas vocabulary where a
producer has a narrower compatible state set. A response includes the state and
limitations for each relevant capability.

Available compatible capabilities contribute candidates and score components.
Unavailable or incompatible capabilities are omitted and weights are renormalized.
A query may return useful partial results while stating, for example:

```text
No authoritative call evidence is available for this scope.
Call-based matches were not evaluated.
```

A zero-hit result means only that no indexed compatible fact matched within reported
coverage. It is not a repository-wide absence claim. Old snapshots without PR128 or
PR130–PR132 findings remain readable and provide the exact/symbol/graph features their
structured content supports through PR134-compatible identity resolution.

## Determinism and serialization

Immutable query, interpretation, hit, score-component, capability, and response DTOs
provide exact `to_dict()` / `from_dict()` round trips. Maps serialize with sorted keys;
sets become sorted arrays; inputs, evidence, alternatives, capabilities, and hits use
defined stable ordering. Canonical JSON contains no timestamps, random IDs, runtime
addresses, or machine-local paths.

For the same compatible snapshot, invalidation key, and query, ordered results and
canonical JSON are byte-identical regardless of input order, dictionary insertion
order, Python hash randomization, filesystem traversal order, or worker completion
order. Warm searches and index rebuilds use the same immutable representation and
ordering rules.

## CLI

The top-level command performs deterministic local search against the latest compatible
snapshot for the selected workspace:

```powershell
atlas search "authentication"
atlas search "REST endpoint" --limit 20
atlas search "authentication" --project api
atlas search "SQL query" --kind method
atlas search "depends on spring-web"
atlas search "Kafka consumer" --json
atlas search "high risk" --explain-score
```

Human output is bounded and shows the interpretation, ranked hits, confidence,
limitations, and omitted count. `--json` emits deterministic structured JSON and does
not invoke a provider. Filters narrow structured candidates. No results is a successful
query and exits with status zero; malformed input, invalid options, or internal failure
uses a nonzero exit according to existing CLI conventions.

## Python API

The additive API builds one reusable immutable service from a snapshot:

```python
from moughorai.public_api import SemanticSearchRequest, SemanticSearchService

service = SemanticSearchService.from_snapshot(snapshot)
response = service.search_semantic(
    SemanticSearchRequest(text="REST endpoint", limit=20)
)
```

`response` exposes the recognized interpretation, ordered hits, capability states,
candidate/returned/omitted counts, limitations, producer version, schema version, and
exact serialization. Existing `SemanticSearchService` construction and legacy
`search()` behavior remain available. Mutable index internals are not public.

The service, request, and response types are additive version-1 exports from
`moughorai.public_api`. Their DTO fields, serialization schema, legacy `search()`
behavior, and `from_snapshot()`/`search_semantic()` entry points follow the PR105
compatibility policy. Index, interpreter, renderer, score-component, and nested-hit
types remain internal implementation details.

Search results may supply canonical candidates to PR134 Explain Anything after a user
or caller selects one. PR135 does not perform explanation generation or change PR134
resolution semantics.

## Measurement and performance methodology

PR135 integrates with the M2 measurement framework using separate phases for:

- `semantic_search.index`;
- `semantic_search.interpret`;
- `semantic_search.retrieve`;
- `semantic_search.score`;
- `semantic_search.sort`;
- `semantic_search.evidence`;
- `semantic_search.render`.

Measurements may record wall time, CPU time, RSS or Python allocations when enabled,
source subject count, candidate count, hit count, and warm-query time. Retained-object
counters cover feature outputs and must not be interpreted as a byte-accurate heap
size. Performance
comparisons must use the same snapshot digest, invalidation key, query set,
configuration, process mode, and measurement settings. Index construction is measured
separately from snapshot loading, and warm lookup separately from cold construction.

Candidate and traversal bounds are part of the reported result. Performance targets
must be based on collected benchmark evidence; this document does not assert an
unmeasured latency, memory, or repository benchmark result. Normal analysis must not
pay search-index construction cost when PR135 is unused.

## False-positive boundaries

- Name and package matches are lexical hints, never proof of authentication,
  controllers, caching, scheduling, SQL, or another engineering role.
- A framework or dependency coordinate proves declared presence at its recorded scope,
  not runtime use by every project or symbol.
- A trusted fully qualified annotation supports only the concept explicitly assigned
  by its versioned rule. A recognized unresolved simple annotation is retained only as
  weak evidence with an explicit limitation; a similarly named custom FQN is ignored.
- Missing canonical relations, especially `calls` and `composition`, are unknown rather
  than absent.
- Test, generated, and project-local evidence retains its scope and is not promoted to
  a repository-wide conclusion.
- Pattern, reachability, and risk matches require compatible structured findings and
  traceable evidence. Prose mentioning those concepts is ignored.
- Ambiguous identities remain distinct candidates; equal display names across projects
  are not collapsed.

These conservative rules can produce false negatives when an analyzer has not emitted
the required structured fact. That limitation is preferable to unsupported certainty
and is disclosed through capability and coverage metadata.

## Compatibility, limitations, and deferred work

- PR129 remains the only canonical repository graph and its IDs are unchanged.
- PR134 remains the only canonical subject resolver; PR135 adds candidate expansion
  after resolution rather than duplicating it.
- PR130 evidence, confidence, lineage, deterministic IDs, and serialization conventions
  are reused.
- Existing PR25 search callers and PR127–PR134 snapshots remain compatible.
- Search does not rescan a repository and cannot recover facts omitted from the saved
  snapshot.
- Relational coverage is limited to authoritative edges actually populated by the
  production pipeline.
- Exact qualified-name ambiguity across projects or modules requires explicit scope.
- Module filters require explicit canonical module membership; a project is not
  silently relabeled as a module.
- The bounded concept registry is intentionally incomplete and is extended only with a
  real consumer and structured evidence rule.
- Persistent search indexes and feature-local disk caches are deferred pending measured
  rebuild cost.
- Embeddings, vector databases, learned ranking, federated cross-repository search, and
  LLM query interpretation are deferred.
- PR136 impact prediction is not part of PR135. Search may later provide selected
  canonical subjects to PR136 without implementing impact traversal here.
