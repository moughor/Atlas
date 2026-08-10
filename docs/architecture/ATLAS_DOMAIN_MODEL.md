# Atlas Domain Model

Status: proposed domain map. Only Repository Intelligence is implemented.

## Definition

An Atlas intelligence domain is a bounded system that owns:

- its source and input authority;
- its identity scheme and normalization rules;
- its immutable observations and evidence interpretation;
- deterministic derivations and explicit availability/conflict states;
- domain-specific storage and retention semantics;
- source-free projections, queries, renderers, and optional explanations.

A domain is not a product label, a CLI subcommand, or a folder containing
unrelated features. It is a boundary that prevents one class of evidence from
being mistaken for another.

## Domains

| Domain | Status | Responsibilities | Explicit boundary |
| --- | --- | --- | --- |
| Repository Intelligence | Implemented through PR142 | Discover repositories; analyze languages; produce semantic documents, symbols, canonical repository relationships, risk, security, impact, refactoring, evolution, technical-debt observations, source-free snapshots, and grounded explanations. | It does not own external benchmark captures, hardware identity, benchmark validity, or overclocking advice. |
| Benchmark Intelligence | Planned only in frozen Atlas AI OC | Source registry; authorized immutable captures; extraction; benchmark definitions; hardware/configuration and run identity resolution; assertions; deterministic comparison analytics; calculator/model observations; bounded reports. | It must not use repository `Workspace`, semantic graph nodes/edges, `.ass` snapshot payloads, repository analyzer registry, or repository rule contexts as its data model. |
| Hardware Intelligence | Future possibility, not designed | Could own hardware catalog facts, device identity, specifications, compatibility, and observational evidence if an approved domain specification exists. | It is not implied by the Benchmark domain's hardware-configuration records and must not be created from them by assumption. |
| Log Intelligence | Future possibility, not designed | Could own log capture, parsing, correlation, retention, and operational assertions if an approved domain specification exists. | It must not reuse repository diagnostics or benchmark captures as a generic log schema. |

The last two rows are named only to establish isolation rules. They authorize no
package, API, storage, roadmap commitment, or implementation.

## Repository Intelligence model

Repository Intelligence currently has the following evidence chain:

```text
repository workspace
  -> language-specific source analysis
  -> immutable semantic documents and specialized artifacts
  -> symbols, repository summary, canonical KnowledgeGraph
  -> evidence-backed specialized findings and repository report
  -> checksum-verified source-free semantic snapshot
  -> bounded deterministic query/rendering and optional LLM explanation
```

Its central models are repository-specific:

| Component | Why it remains in the domain |
| --- | --- |
| `Workspace`, project discovery, execution, recovery, and cache | They encode source-tree, build, project, and workspace lifecycle semantics. |
| `semantic`, Java/Python/TypeScript analyzer packages, symbols, and types | They encode programming-language facts. |
| `KnowledgeGraph` and `SubjectQuery` | Their nodes, relations, resolution, and evidence are canonical repository identities. |
| `AtlasSemanticSnapshot` and `SemanticSnapshotStore` | They persist `WorkspaceSemanticContext`, workspace fingerprint, analyzer version, and repository history reference. |
| `RuleContext`, rule SDK, and analyzer registry | They expose source paths, language, and repository semantic documents. |
| Security, impact, refactoring, evolution, debt, and change-review services | They reason over repository facts and retain repository-specific availability limits. |

Architectural Drift also belongs here, but is not currently implementable: the
domain has current-state architecture observations and graph evolution, not an
explicit intended architecture contract.

## Benchmark Intelligence model

The frozen AI OC design demonstrates why a second domain needs its own vertical
model. Its planned evidence flow is:

```text
source registry
  -> immutable authorized capture
  -> extraction batch and source observation
  -> conservative identity resolution
  -> canonical assertion
  -> deterministic analytics or external-model observation
  -> bounded report/explanation projection
```

Its proposed entities include `source`, content-addressed `capture`, benchmark
and benchmark-definition, source submission, cautiously resolved run,
hardware configuration, assertion, derivation, and model observation. It also
requires authority-by-predicate, source/effective/recorded time, conflict
representation, legal/retention policy, and exact decimal/unit semantics.

Those responsibilities must stay with Benchmark Intelligence. In particular,
the AI OC raw/normalized/derived/models/reports/quarantine/cache zones are a
domain storage design, not a replacement for repository workspace state or the
`.atlas/ass` archive.

## Shared infrastructure versus shared domain data

The following distinction is mandatory:

| May become shared infrastructure | Must remain domain data |
| --- | --- |
| Deterministic operational measurement session and generic metrics | Repository workspace/project identity; benchmark source/run/hardware identity |
| Source-free output safety utility | Repository graph relations; benchmark authority predicates |
| Versioning, compatibility, determinism, and test conventions | Repository `.ass` payload; benchmark capture/dataset layout |
| Future explicitly versioned exchange protocol, after two consumers exist | Repository evidence record kinds; benchmark assertion schema |

Existing `semantic_evidence` demonstrates a valuable evidence discipline, but
its `GRAPH_EDGE`, `SEMANTIC_FACT`, `REPOSITORY_METADATA`, and `snapshot_id`
semantics are Repository Intelligence vocabulary. AI OC's capture, authority,
effective-time, and assertion requirements prove that a copied
`EvidenceRecord` would be a false common model. The platform shares
provenance requirements and compatibility discipline first, not one premature
record class.

## Cross-domain interaction model

No cross-domain consumer exists today. When one is approved, interaction must
be a one-way read of a versioned published projection:

```text
Domain-owned durable evidence
  -> domain-owned deterministic projection
  -> versioned exchange boundary
  -> consuming domain or adapter
```

The exchange boundary must declare producer, schema version, input identities,
lineage, scope, redaction/safety state, limitation/availability state, and
compatibility result. It must not expose private mutable domain storage,
unbounded source content, plugin contexts, or a live domain service locator.

## Domain ownership rules

1. A domain can enrich only facts it is authoritative for or explicitly consume
   a compatible published projection from another domain.
2. A domain never converts absence in another domain into a negative fact.
3. Domain confidence models may share a deterministic method only after their
   input roles and interpretation are proven identical; confidence values are
   not interchangeable merely because both are numeric.
4. Domain snapshots or datasets retain their own identity and retention
   semantics. A shared archive is a later storage decision, not a package move.
5. An optional LLM receives only a bounded, source-free domain projection and
   cannot create domain evidence, citations, confidence, or policy intent.

## Recommendation

Adopt Repository Intelligence as the first isolated Atlas domain. Treat the
frozen AI OC artefacts as Benchmark Intelligence's authoritative planning
specification, not as Atlas source code or a shared model. Introduce a shared
contract only in response to a demonstrated, identical requirement from both
implemented domains.
