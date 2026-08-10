# Atlas Platform Architecture

Status: proposed architecture review; no production implementation is authorized by this document.

## Decision

Atlas should evolve from a repository-intelligence product into an **Evidence
Intelligence Platform**. The platform is not a generic data lake, a universal
graph, or a rewrite of the current repository analyzer. It is a small set of
deterministic, evidence-preserving infrastructure and dependency rules that
allows independently owned intelligence domains to coexist.

Repository Intelligence remains the first and only implemented domain. Benchmark
Intelligence is a separate planned domain described by the frozen Atlas AI OC
workspace; it is not production code, a package, or an Atlas subsystem today.

This conclusion follows the PR143 discovery: PR128 observes current repository
architecture and PR141 compares graph facts between snapshots, but neither owns
an explicit intended architecture contract. Architectural Drift must therefore
remain unavailable until Repository Intelligence publishes an explicit,
versioned contract. Atlas must not infer intent from names, patterns, or graph
deltas.

## Inspection evidence

This review examined the PR142 baseline (`e021db2a2b659b3388e6adb85a0176302ff213ff`)
and its complete production import graph.

| Observation | Evidence | Architectural meaning |
| --- | --- | --- |
| 532 production Python modules and 262 test modules | Complete AST inventory of `moughorai/**/*.py` and `tests/**/*.py` | A repository-wide rename would be high-risk and is not justified. |
| 1,438 internal import edges | Static AST import analysis | Dependency control must be introduced incrementally and enforced mechanically. |
| `semantic_evidence` has 30 module consumers and no Atlas-package imports | Import fan-in/fan-out analysis | It is a shared repository contract, but its kinds and snapshot semantics must not yet be declared cross-domain. |
| `measurement` has 25 module consumers, 16 package consumers, and no Atlas-package imports | Import fan-in/fan-out analysis | Its session and operational metric model are the strongest existing platform-infrastructure candidate. |
| `repository_report.safety` has 21 module consumers | Import fan-in analysis plus imports from graph, search, impact, refactoring, AI, and security packages | A generic source-free safety utility is incorrectly located in a report package and is the one immediately justified relocation. |
| `atlas_cli` has 34 package dependencies | Import fan-out analysis and command inventory | It is a composition root, not a reusable domain dependency. Its high fan-out is expected but must remain at the edge. |
| A 16-module static strongly connected component spans context, snapshots, subject resolution, reports, prompts, and security intelligence | Static SCC analysis; several source files contain deliberate lazy imports to avoid initialization failures | The cycle is a managed risk. New cross-domain imports must not extend it, and PR144 should remove its narrowest type-level edge. |
| `public_api` is a versioned v1 facade with constructor-signature fixtures | `moughorai/public_api/__init__.py` and `tests/test_pr105_public_api.py` | Existing supported Python imports must remain type-identical and compatible. |
| `SemanticSnapshotStore` creates checksum-verified, immutable historical `.ass` files and atomically updates `latest.ass` | `semantic_snapshot/models.py`, `semantic_snapshot/store.py`, and PR111 tests | The current snapshot is a Repository Intelligence artifact, not yet a generic domain snapshot. |

## Current architecture

### Package hierarchy

The current `moughorai` hierarchy is a mature Repository Intelligence system,
not a small platform kernel. Its packages fall into these ownership groups:

| Current group | Packages and modules | Responsibility |
| --- | --- | --- |
| Entry points and adapters | `atlas_cli`, `cli`, `api`, `lsp`, `ai_ide`, `sarif`, `dashboard`, `ci_templates`, `cli_output` | User, editor, API, CI, and report-format adaptation. |
| Workspace and operational runtime | `workspace`, `workspace_distributed`, `incremental_analysis`, `project_inventory`, `project_index`, `project_locator`, `history`, `finding_baseline`, `watch` support, `measurement`, `profiling`, `structured_logging`, `governance` | Repository discovery, scheduling, persistence, recovery, operational observability, and lifecycle. |
| Language and semantic frontends | `semantic`, `passes`, `java_ast`, `java_semantics`, `java_symbols`, `java_workspace`, `java_analysis`, `java_resolution`, `python_semantics`, `cross_language`, `global_symbols`, `models` | Language-specific parsing, types, diagnostics, symbols, and semantic documents. |
| Repository relationship and analysis services | `dependency_graph`, `dependency_intelligence`, `knowledge_graph`, `architecture_detection`, `repository_summary`, `repository_report`, `risk_analysis`, `reachability`, `call_graph`, `data_flow`, `dataflow`, `cross_references`, `context_builder`, `subject_resolution` | Repository graph construction, source-free projections, and specialized repository facts. |
| Engineering-intelligence consumers | `semantic_search`, `impact_analysis`, `refactoring_advisor`, `repository_evolution`, `technical_debt`, `change_review`, `design_patterns`, `structured_explanation` | Bounded, evidence-backed repository questions and reports. |
| Security family | `security_analysis`, `java_security`, `security_intelligence`, `security_ci`, `security_explanations`, `security_knowledge`, `security_lsp`, `taint_policy`, `interprocedural_taint`, `symbolic_execution`, `advanced_symbolic`, `incremental_security`, `multi_module_security` | Security-specific source analysis and repository intelligence. |
| AI interaction | `ai`, `ai_context`, `ai_explain`, `ai_ask`, `ai_review`, `ai_patch`, `ai_memory`, `ai_git_context`, `ai_retrieval`, `llm`, `prompts`, `services` | Source-free context construction, deterministic projection, optional provider interaction, and conversation state. |
| Extension systems | `plugin_sdk`, `rule_sdk`, `policy_packs`, `rules`, `framework_models` | Repository analyzer, rule, reporting, and policy-pack extension mechanisms. |
| Legacy assistant path | `config`, `knowledge`, `memory`, `search`, `orchestrator`, the `moughorai` console script | Existing MoughorAI assistant workflow preserved as a compatibility surface. |

Several root modules (`adaptive_scheduler`, `quality_gate`, `git_diff`,
`gradle_syntax`, and others) support those groups. The similarly named
`data_flow` and `dataflow` packages are an existing naming hazard, not evidence
that either should be renamed during the platform transition.

### Current layers and dependency directions

The existing architecture guide correctly describes a downward flow from
interfaces to workspace orchestration, analyzers, semantic models, state, and
reports. The actual implementation adds a repository-intelligence projection
layer above the canonical graph:

```text
CLI / API / LSP / CI / legacy assistant
                 |
                 v
Repository application services and renderers
  (search, impact, refactor, security, evolution, debt, AI)
                 |
                 v
Repository semantic-context collection and specialized analyzers
                 |
                 v
Repository models: workspace, language semantics, symbols, graph
                 |
                 v
Operational primitives: measurement, logging, filesystem, standard library
```

`atlas_cli` is the primary composition root. It registers `analyze`, `check`,
`watch`, configuration, plugin, CI, history, dashboard, profile, governance,
change-review, evolution, search, impact, refactor, debt, security, and `atlas
ai` commands. The older `moughorai` script exposes a separate `ask` pipeline.
Both are published console-script boundaries and must be treated as adapters,
not as services to import from domain code.

### Current evidence, snapshot, rendering, and serialization pipelines

Repository Intelligence already has a strong evidence pipeline:

```text
workspace discovery and execution
  -> language semantic documents and specialized artifacts
  -> SemanticContextCollector
  -> WorkspaceSemanticContext
  -> canonical KnowledgeGraph plus specialized findings
  -> RepositoryReport and other source-free projections
  -> checksum-verified AtlasSemanticSnapshot (.ass)
  -> deterministic queries/renderers or bounded optional LLM explanation
```

`EvidenceRecord`, `EvidenceIndex`, and `ConfidenceCalculator` supply
deterministic IDs, producer/snapshot lineage, roles, coverage, limitations, and
confidence. The semantic collector creates repository summary, architecture,
security, pattern, reachability, risk, and repository-report projections before
the snapshot is captured. `SemanticSnapshotStore` canonicalizes, verifies,
stores immutably, and atomically publishes the snapshot.

Feature packages own their response models and JSON serializations. The CLI
selects deterministic text renderers such as `render_semantic_search`,
`render_impact_prediction`, `render_refactoring_advice`,
`render_security_intelligence`, `render_repository_evolution`, and
`render_technical_debt`; generic workspace output and SARIF have their own
adapters. This is a sensible domain-local rendering design. A platform renderer
is not justified.

## Target architecture

### Platform philosophy

Atlas should be a platform for **independent, evidence-first intelligence
domains**. A domain owns its source types, identity scheme, analyzers,
normalization, deterministic derivations, snapshots or datasets, policies,
queries, and renderers. The platform supplies only contracts proven to be
identical across domains.

The frozen AI OC design supports this direction. Its source registry, immutable
captures, extraction batches, identity resolution, canonical assertions,
deterministic analytics, and bounded context projection are a distinct domain
pipeline. Its benchmark definitions, hardware configurations, source captures,
external-model observations, authority policy, and retention requirements are
not repository semantic graph concepts. They must not be forced into
`KnowledgeGraph`, `WorkspaceSemanticContext`, or `.ass`.

### Future layers

```text
Adapters and composition roots
  atlas CLI | APIs | LSP | CI | domain-specific UIs
                 |
                 v
Domain application layer
  Repository Intelligence | Benchmark Intelligence | future domains
                 |
                 v
Domain internals
  analyzers | identity | evidence interpretation | derivations | projections
                 |
                 v
Small Atlas platform kernel
  deterministic operational measurement | source-free safety | versioning and
  compatibility conventions | explicit extension admission contracts
                 |
                 v
Python/runtime, approved storage adapters, operating-system controls
```

This is a dependency diagram, not a proposal to create all of these packages in
one change. The kernel must never import a domain. A domain may import a stable
platform contract. Only an adapter or explicitly versioned exchange boundary
may depend on more than one domain.

### Domain isolation

1. A domain owns the truth of its facts. Repository language analyzers remain
   authoritative for repository semantics. Benchmark sources and benchmark
   identity policies will remain authoritative for Benchmark Intelligence.
2. Domain A must not import Domain B models, analyzers, storage, renderers, or
   private implementation helpers.
3. Cross-domain exchange is allowed only through an explicit, versioned,
   source-free published projection with producer identity, input lineage,
   schema version, limitations, and compatibility state. No such generic
   exchange contract exists today; it must not be invented in PR144.
4. A generic name is not sufficient reason to share a type. `KnowledgeGraph`,
   `Workspace`, `SemanticSnapshotStore`, `SubjectQuery`, and the rule SDK all
   encode repository semantics and remain Repository Intelligence components.
5. An LLM, report, dashboard, and cache are consumers of facts, never their
   source of authority.

### Scalability direction

The future platform scales by isolating immutable, reproducible domain data
rather than by centralizing all data behind a single database. AI OC's proposed
raw, normalized, derived, model, report, quarantine, and cache zones are
Benchmark Intelligence design inputs. They are not a mandate to replace the
existing repository `.ass` archive or workspace state. Storage consolidation
requires two implemented domains with proven common lifecycle, retention,
identity, and replay needs.

## Migration strategy

1. **Architecture first.** Adopt the dependency rules and document the
   Repository Intelligence boundary before moving source.
2. **Minimal correction.** Relocate the generic source-free safety utility and
   preserve its old import path as a forwarding compatibility module. Remove
   the narrow `semantic_snapshot -> ai_context` type dependency without
   changing snapshot bytes or public v1 behavior.
3. **Characterize and enforce.** Add static dependency tests, snapshot golden
   tests, public API fixtures, and CLI contract tests before any broader move.
4. **Publish explicit repository architecture contracts.** Only then can a
   future Architectural Drift capability evaluate policy against verified
   repository evidence.
5. **Build the second domain as a vertical slice.** Benchmark Foundation first
   implements only AI OC's evidence spine and fixtures. It may request a
   platform contract when an identical need is demonstrated against the
   existing repository domain.
6. **Extract only after proof.** A shared facility needs two real consumers,
   matching lifecycle and compatibility requirements, and a migration plan.

## Explicit non-decisions

- No generic `AtlasEntity`, universal graph, generic intelligence record, or
  cross-domain database is proposed.
- No Benchmark Intelligence package, parser, source acquisition, hardware
  model, or HWBOT integration is authorized by this document.
- No repository snapshot is redefined as a platform artifact.
- No plugin sandbox or distributed runtime is claimed. Existing plugins remain
  trusted in-process Python code; manifest permissions are admission checks,
  not runtime containment.
- No module is split merely because it is large. Several 50--98 KiB models and
  services require behavior-focused characterization before any split.

## Architectural recommendation

Approve Atlas as an evidence-first multi-domain platform with a deliberately
small shared kernel. Approve only the incremental PR144 refactoring described
in `ATLAS_REFACTORING_PLAN.md`. Defer Architectural Drift until an explicit
Repository Intelligence architecture contract exists, and defer Benchmark
Intelligence implementation until the platform boundary and its fixtures are
reviewed.
