# Atlas Dependency Rules

Status: normative dependency rules accepted by PR143 and updated with the
verified PR145 runtime graph. They define the required direction for future
changes.

## Basis

The rules preserve the existing Atlas engineering principles: evidence before
inference, deterministic reasoning, explicit uncertainty, specialized analyzer
authority, compatibility, and incremental abstraction. The PR145 inventory
contains 535 production Python modules, 1,441 statically resolvable runtime
edges, three typing-only edges, and no cyclic runtime strongly connected
component. The test methodology and its dynamic-import limitation are recorded
in `docs/PR145_PLATFORM_DEPENDENCY_RATCHET.md`.

## Layers

| Layer | Owns | May depend on |
| --- | --- | --- |
| Adapters | CLI commands, HTTP/API, LSP, CI, dashboards, output formatting, composition | Domain public services and platform contracts. |
| Domain application | Requests, use cases, deterministic queries, feature-local renderers, orchestration of domain internals | Its own domain internals and platform contracts. |
| Domain internals | Domain analyzers, identity, models, domain-specific evidence interpretation, storage adapters, snapshots/datasets | Its own lower domain modules and platform contracts. |
| Platform kernel | Cross-domain operational and safety contracts with no domain imports | Python/runtime libraries and explicitly approved external adapters. |
| External boundary | Filesystem, network, subprocesses, providers, databases, plugin processes | Nothing in Atlas; access is mediated by an adapter above it. |

Repository Intelligence is one domain within this model. It includes workspace,
language semantics, canonical repository graph, repository snapshots, subject
resolution, repository reports, security analysis, engineering-intelligence
features, and the existing repository-specific plugin and rule systems.

## Allowed dependencies

| From | Allowed imports | Conditions |
| --- | --- | --- |
| Adapter | Domain application public service; platform contract | The adapter performs parsing, composition, error mapping, rendering selection, and lifecycle only. |
| Domain application | Same-domain application/internals; platform kernel | It must not import another domain or adapter. |
| Domain internal | Same-domain lower-level internal; platform kernel | It must not reach upward to CLI, API, LSP, report presentation, or provider UI. |
| Platform kernel | Platform kernel | A platform module imports no `moughorai` domain package. |
| Compatibility forwarder | New canonical module | It contains no behavior beyond a documented re-export and deprecation path. |
| Test | Public and intended internal boundary | Tests may use white-box imports only to characterize or enforce a documented migration. |

## Forbidden dependencies

1. Platform code MUST NOT import Repository Intelligence or a future domain.
2. One intelligence domain MUST NOT import another domain's models, analyzers,
   private storage, or renderers.
3. Domain code MUST NOT import `atlas_cli`, `cli`, `api`, `lsp`, dashboard, or
   any other adapter to obtain functionality.
4. A report, prompt, provider response, or LLM output MUST NOT establish
   evidence, identity, confidence, architecture intent, or policy compliance.
5. A new feature MUST NOT create a second graph, confidence calculator,
   evidence index, resolver, snapshot archive, or cache when its own domain
   already has an authoritative owner.
6. Domain-neutral code MUST NOT import `repository_report.safety` after its
   migration. It must import the platform safety boundary instead.
7. `__init__.py` re-exports MUST NOT create a reverse dependency to satisfy a
   convenience import. Leaf imports or a narrow compatibility forwarder are
   required instead.
8. Plugin manifests and `PluginContext` MUST NOT be treated as a security
   sandbox or a cross-domain service locator. Existing plugins are trusted
   in-process code, as documented by PR106.

## Import rules

### Platform contracts

- A platform module has no import beginning with a domain package path.
- It exposes deterministic models, pure utilities, operational services, or
  explicit protocols only when at least two real consumers require the same
  contract.
- It never owns domain identifiers, domain taxonomy, domain-specific graph
  edges, semantic document fields, capture policy, or a domain's report shape.
- A platform contract must carry a schema/version and have compatibility tests
  before it becomes a dependency of more than one domain.

### Repository Intelligence

- Existing Repository Intelligence packages may continue to use their
  established `moughorai.*` paths during migration.
- `semantic_snapshot`, `knowledge_graph`, `workspace`, `subject_resolution`,
  `plugin_sdk`, `rule_sdk`, and `semantic_evidence` remain repository-owned
  until a second implemented domain proves an exact shared contract.
- Repository features use `semantic_evidence` and the canonical resolver rather
  than duplicate evidence and identity models.
- Architecture policy must be explicit, versioned repository input. PR128
  pattern observations and PR141 graph deltas cannot be imported as a proxy for
  intent.

### Adapters and renderers

- `atlas_cli` remains a high-fan-out composition root. Its 34 package
  dependencies do not authorize those packages to depend back on it.
- Feature text renderers and JSON serializers stay feature-local. A generic
  renderer is forbidden unless two implemented domains need the same stable
  output protocol.
- The public Python compatibility facade remains `moughorai.public_api` v1;
  it must preserve type identity and constructor-signature fixtures.
- The published `atlas` and `moughorai` console scripts remain supported until
  a separately approved deprecation plan exists.

## Circular-dependency policy

PR145 removes the remaining six-module runtime component by importing
`WorkspaceSemanticContext` from its PR144 canonical owner instead of the eager
`ai_context` compatibility facade. The statically resolvable runtime graph now
contains no cyclic strongly connected component.

- No new runtime import may introduce a cyclic strongly connected component.
- New code must import leaf modules rather than package aggregators when that
  avoids an upward dependency.
- Type-only dependencies must be classified separately and should use
  `TYPE_CHECKING`, protocols, mappings, or a domain-local adapter when runtime
  construction is unnecessary.
- Variable dynamic imports are not represented as static graph edges; existing
  plugin admission and runtime validation remain responsible for them.
- A dependency must be corrected with a tested inversion or canonical-owner
  import. Modules must not be moved merely to change a graph visualization.

## Extension boundaries

| Existing mechanism | Current boundary | Future rule |
| --- | --- | --- |
| `AnalyzerRegistry` / `LanguageAnalyzer` | Repository language-frontends produce repository `SemanticDocument` values | Remains Repository Intelligence; it is not a benchmark extractor protocol. |
| Rule SDK | Source-path and language `RuleContext` produces repository findings | Remains Repository Intelligence. |
| Plugin SDK | Trusted in-process analyzer, policy-pack, and reporter extensions with manifest/trust admission | Remains a repository extension boundary until a cross-domain extension contract is implemented and isolated. |
| LLM provider interfaces | Optional explanation/provider integration | May consume bounded projections only; it cannot become an evidence extension. |

## Enforcement plan

1. Parse production imports deterministically, classify `TYPE_CHECKING`
   imports separately, and reject every cyclic runtime strongly connected
   component. There is no runtime-cycle allowlist.
2. Import affected boundaries in a clean interpreter and verify that canonical
   imports do not load legacy package facades.
3. Keep existing public API fixture, snapshot checksum, deterministic JSON,
   CLI, plugin-trust, and renderer tests as required migration gates.
4. Treat a proposed exception as an architectural change requiring evidence
   and approval; do not silently add an allowlist entry.

## Review criterion

A proposed shared abstraction is accepted only when the review names two real
consumers, their shared input/output semantics, lifecycle, identity and
retention rules, schema/version policy, compatibility test, and owner. If any
of these are missing, the abstraction stays in its domain.
