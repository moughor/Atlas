# PR135 Existing Capabilities

Status: preimplementation audit recorded before PR135 production changes. The
implementation document and verification report describe the delivered behavior.

## Baseline

PR135 starts from commit `c9b6b13cc5cd0520bd9e5576ba374172f21accb6`.
At inspection time the worktree was clean, `HEAD` matched `origin/main`, and the
active `moughorai` package resolved from this checkout.

## Capability audit

| Capability | Existing owner | Reuse strategy | Missing PR135 work |
| --- | --- | --- | --- |
| Canonical identity | PR129 `KnowledgeGraph` and PR134 `CanonicalSubjectResolver` | Keep graph node identities and use resolver projections for public subject identity | Search-specific candidate records and filters |
| Exact subject lookup | PR134 `CanonicalSubjectResolver` | Delegate IDs, qualified names, normalized names, scope constraints, and ambiguity | Feed resolved/ambiguous outcomes into search responses |
| Graph neighborhood | PR129 bounded adjacency APIs | Traverse only relation-specific bounded canonical edges and retain their evidence | Relational query planning, coverage messages, and ranking signals |
| Symbol facts | `GlobalSymbolDatabase` and source-free snapshot `symbols` | Index names, kinds, project/language scope, annotations, inheritance metadata, and entry-point roles | Immutable feature-local projections and deterministic token indexes |
| Repository inventory | PR127 repository summary | Use structured project, language, framework, dependency, and entry-point facts only | Search projections for repository concepts; never index report prose |
| Dependencies and frameworks | Existing dependency intelligence and PR129 dependency/framework nodes | Search canonical coordinates/nodes and their traceable ownership/dependency relations | Intent aliases, precise capability scope, and conservative technology-presence limitations |
| Architecture findings | Existing architecture analysis | Consume compatible structured findings as optional enrichment | Version checks, subject joins, and explicit unavailable state |
| Design patterns | PR130 pattern report | Consume compatible findings and their evidence IDs | Pattern-intent projection and bounded participant joins |
| Reachability | PR131 dead-code report | Consume compatible grouped findings and their evidence IDs | Reachability-intent projection without treating missing call edges as absence |
| Risk and hotspots | PR132 risk report | Consume compatible hotspots and their evidence IDs | Risk-intent projection and explicit partial coverage |
| Evidence lookup | Shared `EvidenceIndex` / `EvidenceRecord` | Reuse upstream indexes and create deterministic search evidence records for indexed structured facts | Merge compatible evidence without a second evidence model |
| Confidence | Shared `ConfidenceCalculator` | Calculate confidence from structured evidence independently of relevance | Search-specific evidence roles and coverage values |
| Ranking | PR25 lexical scoring only | Preserve PR25 behavior for existing callers | Central PR135 weights, renormalization, component explanations, and stable ties |
| Query interpretation | No semantic interpreter | Reuse resolver vocabulary, graph enums, and structured capability names | Bounded deterministic grammar and versioned concept registry |
| Explain Anything | PR134 structured explanation | Return canonical IDs suitable for optional follow-up explanation | No explanation engine inside search |
| Snapshots | `AtlasSemanticSnapshot` / `SemanticSnapshotStore` | Rebuild an index from compatible source-free snapshot fields | Compatibility checks, lineage/index fingerprint, and partial-snapshot behavior |
| Persistence | Existing snapshot and feature-cache infrastructure | Do not persist the initial search index; repeated queries reuse one in-memory service instance | Document invalidation key and measure rebuild cost before any future persistence |
| Measurement | M2 `MeasurementSession` | Add stable feature phase identifiers and opt-in CLI profiling | Index, interpretation, retrieval, scoring, sorting, evidence, and rendering counters |
| CLI | Unified Typer CLI and deterministic JSON conventions | Load an existing snapshot without workspace rediscovery or an LLM | Add top-level `atlas search` with human/JSON output and filters |

## Reusable production evidence

- Canonical graph nodes and edges provide identity, ownership, membership,
  dependencies, imports, inheritance, overrides, calls, and other relations only
  when those edges are actually present. Edge evidence remains traceable.
- Source-free symbol metadata provides analyzer-produced annotations,
  inheritance/override references, visibility, entry-point roles, language, and
  project scope. Arbitrary source text, comments, literals, and report prose are
  excluded.
- PR128 and PR130--PR132 findings provide architecture, pattern, reachability, and risk classifications
  only when their schema, producer, subject, and evidence are compatible.
- Repository inventory provides structured framework and build metadata. A
  dependency or framework presence proves technology presence, not use by every
  symbol.

Names remain lexical evidence. They cannot independently establish a strong
semantic concept match. Missing edges or findings remain unknown and are never
converted into negative evidence.

The normal snapshot producer currently populates ownership, membership,
dependencies, resolved imports, inheritance, and conservative override evidence.
Canonical `calls` and `composition` are model-supported but not normally populated;
search must therefore report those capabilities as unavailable instead of claiming
an empty result. Canonical inheritance uses one relation kind. PR135 reports
`extends` or `implements` only when the traceable edge evidence establishes that
exact producer subtype; generic inheritance evidence supports only `inherits`.

Symbol metadata is not safe as an unrestricted input because some language
analyzers retain docstrings. PR135 therefore uses an allowlist of structured keys
(annotations/decorators, inheritance, overrides, visibility, entry-point role,
and source classification), uses a bounded canonical language identifier, and
explicitly excludes docstrings, arbitrary
metadata, diagnostics, history, exception text, and absolute paths.

## Missing work and extensions

PR135 will extend `moughorai.semantic_search` with immutable request,
interpretation, score, hit, capability, index, and response contracts. It will add
a bounded concept registry, an in-memory index builder, a deterministic query
interpreter, structured scoring, snapshot construction, CLI rendering, and focused
tests. Existing PR25 query/hit behavior stays available unchanged.
The minimal service/request/response embedding contract is exposed additively through
the PR105 `moughorai.public_api` facade; lower-level index and ranking types remain
internal.

No new graph, resolver, evidence model, confidence model, report model, semantic
pass, persistent cache, embedding service, vector store, or LLM dependency is
needed.

## Regression and compatibility risks

- PR25 and PR28/PR29 callers rely on `SemanticSearchService.search()` returning
  legacy symbol hits; snapshot search must be an additive mode.
- Older snapshots may lack the canonical graph, PR128/PR130--PR132 findings, and
  PR134-compatible identity metadata; the
  engine must return explicit partial/unavailable capabilities rather than fail.
- Canonical relation coverage varies by language and producer. Relational queries
  must report reduced coverage and never infer missing relationships.
- Duplicate names across projects must retain distinct canonical IDs and explicit
  ambiguity.
- Snapshot metadata can contain portable relative paths, but responses and indexes
  must reject absolute paths and never retain source text.
- Enterprise graphs require bounded candidate retrieval, expansion, output, and
  deterministic top-k sorting.

## Implementation plan

1. Add exact round-trippable PR135 contracts while preserving the PR25 types.
2. Build a versioned immutable source-free index from the PR129 graph, symbol
   metadata, compatible PR128/PR130--PR132 structured findings, and PR134 identity.
3. Interpret a bounded query grammar and delegate exact identity to the PR134
   resolver.
4. Retrieve bounded candidates, apply structured filters, traverse only available
   canonical relations, and rank with the approved central weights.
5. Expose snapshot Python and CLI entry points with explicit capability and
   limitation reporting plus opt-in M2 measurements.
6. Validate round trips, source-free behavior, conservative false-positive bounds,
   determinism, partial snapshots, legacy callers, CLI behavior, and benchmarks.
