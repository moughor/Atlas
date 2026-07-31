# Atlas 2.x Roadmap Dependency Matrix — PR130–PR139

## Required and optional dependencies

| PR | Required inputs | Optional enrichment | Produces | Required predecessors |
|---|---|---|---|---|
| 130 Patterns | PR129 canonical graph; authoritative specialized semantic graphs where available | Additional language-specific semantic evidence | Pattern findings | PR129 |
| 131 Dead code | PR129 canonical graph; existing CFG, entrypoint, framework, and reachability evidence | Specialized call-graph evidence | Reachability states and dead-code findings | PR129 |
| 132 Risk | PR129 graph degrees and ownership; existing complexity, Git, and test metadata | PR130 pattern and PR131 reachability findings | Normalized metrics and hotspots | PR129 |
| 133 Report | PR127 repository summary, PR128 architecture summary, PR129 graph, and structured evidence | PR130–PR132 findings and historical compatible snapshots | Deterministic partial or enriched repository report | PR127–PR129 |
| 134 Explain | Semantic snapshots, PR129 canonical graph, evidence index, and canonical subject resolver | PR130–PR133 findings and reports | Scoped explanation context | PR129 |
| 135 Search | Symbols, structured semantic facts, PR129 graph, canonical subject resolver, and structured findings | PR130–PR134 findings when available | Ranked semantic hits and search indexes | PR129, shared resolver introduced by PR134 |
| 136 Impact | Existing impact services, PR129 graph, Git/API metadata, and canonical subject resolver | PR132 risk and PR135 search/ranking | Impact paths and risk context | PR129, shared resolver introduced by PR134 |
| 137 Refactoring | Existing architecture/dependency findings plus PR130–PR136 structured results | PR133 report presentation | Refactoring advice | PR130–PR136 |
| 138 Security | PR129 canonical graph and the existing Atlas security/taint platform | PR136 impact and blast-radius context | Consolidated security intelligence | PR129 |
| 139 Chat | Existing conversation memory, snapshots, graph, evidence, PR134 explain, and PR135 search | PR133 reports and PR136–PR138 impact, refactoring, and security capabilities | Grounded conversation responses with explicit capability availability | PR134, PR135 |

PR133 must be able to produce a deterministic partial repository report using only
PR127–PR129 data. PR130–PR132 findings enrich that report when compatible results are
available; they are not mandatory predecessors. Every missing analysis is represented
explicitly as unavailable. The report builder must not fabricate findings, prose, or
apparently complete sections for analyses that did not run.

PR134 does not require PR133. It operates directly from semantic snapshots, the
canonical graph, and evidence, and consumes PR130–PR133 outputs only when compatible
findings are available.

PR135 indexes structured semantic facts, canonical identities, graph relations, and
structured findings. Generated repository-report prose is not an index source and is
not a dependency.

PR136 reuses the shared canonical subject resolver introduced for PR134 and extended
for PR135. It does not depend on the complete PR135 search engine.

PR138 depends on PR129 and the existing security platform. PR136 impact information is
optional prioritization and explanation enrichment.

PR134 and PR135 are the minimum required predecessors for PR139. PR136 impact, PR137
refactoring, and PR138 security are optional capability providers. When one of those
providers is absent or incompatible with the current snapshot, chat must state that
the relevant structured analysis is unavailable and must not infer or synthesize a
replacement answer.

## PR131 call-evidence boundary

The PR129 `KnowledgeGraph` is the canonical repository graph, but canonical `calls`
edges are not currently populated by the normal production pipeline. PR131 therefore
must distinguish:

- canonical relationships that are present and traceable;
- optional call relationships supplied by an authoritative specialized call graph;
- scopes for which no reliable call evidence is available.

Specialized call-graph evidence remains authoritative in its domain and may be adapted
to canonical subject IDs without being copied into a competing graph. When reliable
call evidence is unavailable, PR131 reports reduced coverage and confidence and must
not interpret missing calls as proof that code is unreachable or dead.

## Shared capability ownership

Each shared abstraction is introduced by its first real PR130–PR139 consumer and then
extended only when another concrete consumer requires it.

| Shared capability | First owning PR | First concrete use |
|---|---|---|
| Confidence calculator | PR130 | Score evidence-backed design-pattern findings |
| Evidence index | PR130 | Deduplicate and trace evidence supporting pattern findings |
| Snapshot producer versions and lineage | PR130 | Validate and invalidate persisted pattern results against their producing snapshot |
| Invalidation and compact caches | PR130 | Reuse pattern results safely during incremental analysis |
| Token-budgeted context selection | PR133 | Build the source-free AI repository-report context |
| Canonical subject resolver | PR134 | Resolve Explain Anything subjects against snapshot and graph identities |

Ownership does not authorize speculative generalization. PR130 implements only the
confidence, evidence, lineage, invalidation, and cache behavior required by its pattern
consumer. PR133 implements only the context-budget behavior needed for repository
reports. PR134 implements only the subject-resolution behavior needed for explanation.
Later PRs extend these contracts incrementally and preserve backward compatibility.

## Shared graph queries and semantic inputs

| Shared operation | Consumers |
|---|---|
| Relation-filtered canonical neighborhood | PR130–PR139 |
| Roots and reverse reachability | PR131, PR136, PR137, PR138 |
| Deterministic in-degree, out-degree, fan-in, and fan-out summaries | PR132, PR133, PR135, PR137 |
| Canonical subject resolution | PR134–PR139 |
| Evidence lookup and citation | PR130–PR139 |
| Project/package/module hierarchy | PR130, PR133–PR139 |
| Git and ownership lookup | PR132, PR136–PR139 |

Authoritative specialized semantic passes remain responsible for their existing
domains. Downstream PRs consume their structured results and do not duplicate symbol,
dependency, ownership, call, inheritance, override, control-flow, impact, or security
analysis.

Shared graph metrics begin with deterministic in-degree, out-degree, fan-in, and
fan-out. More expensive centrality algorithms are introduced only when a concrete
consumer requires them, a bounded algorithm is specified, and measured performance
justifies their snapshot, execution-time, and memory cost.

## Cache and invalidation rules

Derived keys include snapshot lineage, canonical graph digest, producer versions,
configuration fingerprint, supported-language set, and feature schema. Missing
upstream results remain unavailable; downstream consumers do not recompute them with a
duplicate pass.

Compact caches are feature-local at first. A cache becomes shared only after a second
real consumer demonstrates identical identity, lifecycle, and invalidation semantics.
Canonical `calls` and `composition` support in the model is not evidence that those
relations are populated: consumers use a reliable specialized producer or return
insufficient coverage.
