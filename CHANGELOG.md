# Changelog

## PR138 deterministic security intelligence

- Began the official PR138 Security Intelligence roadmap item with a deliberately
  partial Java slice; PR138 does not continue or complete the partial PR137
  Refactoring Advisor item.
- Reused selected Java source already held by the normal language-analysis pass and
  the existing `JavaSecurityAnalyzer`, then consolidated its bounded findings against
  PR129 canonical identity with PR130 evidence and confidence and PR134 resolution.
- Added explicit `analyzed`, `partial`, `not_analyzed`, and `incompatible` category
  states for secrets, SQL injection, weak cryptography, path traversal, SSRF, XSS,
  unsafe deserialization, unsafe reflection, and general taint; zero findings never
  means that a scope is secure.
- Added additive, source-free `semantic_context.security_intelligence` persistence,
  strict deterministic serialization and lineage validation, bounded evidence and
  request work, and v6 analysis-result producer invalidation for recovery safety.
- Added snapshot-only `atlas security` human and canonical JSON queries with
  repository/project/symbol scopes, project/language/category/severity filters,
  deterministic limits, priority details, and opt-in M2 measurement.
- Added a bounded aggregate Security Intelligence section to the provider-free
  default repository explanation while preserving the accepted rendering of
  snapshots that predate the PR138 field.
- Preserved all specialized security, taint, CI, SARIF, LSP, policy, and incremental
  APIs. XSS, project-wide interprocedural and cross-project taint, non-Java producers,
  PR136 blast-radius enrichment, runtime testing, feeds, and automatic fixes remain
  explicitly unavailable or deferred.

## PR137 deterministic refactoring advisor

- Added a conservative first PR137 slice that turns only fully revalidated PR128
  dependency cycles into deterministic project-seam review advice over the PR129
  canonical graph; it never discovers a second cycle graph or changes source.
- Added exact canonical participants and direction, shared evidence/confidence,
  explicitly unknown gain and effort, optional bounded PR136 impact context,
  limitations, verification steps, strict serialization, and source-free lineage.
- Added provider-free `atlas refactor` human and canonical JSON output with bounded
  family/scope/result controls and opt-in M2 measurement.
- Reported duplicate consolidation, extraction, package restructuring, dependency
  cleanup, and layer repair as unavailable or insufficient until authoritative
  upstream producers exist; names, risk, search, Git, and LLMs cannot create advice.
- Kept advice request-local so analysis snapshots, accepted benchmark artifacts,
  recovery, persistence, and pre-PR137 behavior remain unchanged.

## PR136 deterministic impact prediction

- Added bounded, deterministic impact prediction over PR129 canonical relationships
  with PR134 subject resolution, explicit direct/transitive paths, conservative
  breaking-change states, and exact source-free response serialization.
- Reused shared semantic evidence and confidence contracts, compatible PR131
  reachability and PR132 risk context, and existing graph adjacency without creating
  another graph, resolver, cache, or semantic pass.
- Added provider-free `atlas impact` human and JSON output with scope/relation/change
  filters, explicit capability degradation, zero-result success, score explanations,
  and opt-in M2 measurement.
- Added the immutable request/response/service contract and required `SubjectQuery`
  dependency to the version-1 public facade while preserving legacy PR26 behavior.
- Kept missing calls, composition, external consumers, module identity, and optional
  Git/search enrichment explicit as unavailable, unsupported, or partial rather than
  treating missing evidence as proof of no impact.
- Require producer-bound `moughorai.call_graph.v1:calls` evidence before a canonical
  call edge can create impact; generic call labels remain non-authoritative.

## PR135 deterministic semantic search

- Added source-free, deterministic intent search over PR129 canonical subjects,
  structured symbol facts, dependency/framework evidence, and compatible PR130--132
  findings while preserving the PR25 symbol-search API unchanged.
- Reused the PR134 canonical subject resolver for exact identities and ambiguity,
  and reused PR129 bounded adjacency for relational queries without duplicating the
  graph or treating missing call/composition evidence as absence.
- Added a compact versioned concept registry, immutable rebuildable in-memory index,
  central explainable ranking weights, shared evidence/confidence integration,
  explicit partial capability states, and exact request/response round trips.
- Added provider-free `atlas search` human and canonical JSON output with bounded
  filters, score explanations, zero-result success, and opt-in M2 measurement phases.
- Added the minimal service/request/response contract to the version-1 public facade,
  strict DTO restoration, bounded posting predicates for large scopes, and explicit
  unknown-subject/ambiguity retrieval.
- Restricted canonical edge evidence to established structured producer references
  and publish only fixed lineage plus deterministic hashes of accepted references.
- Kept raw source, docstrings, arbitrary metadata, repository/Explain prose,
  absolute paths, embeddings, vector databases, LLMs, and persistent search caches
  outside the search boundary.

## M2.1 recovery checkpoint amplification

- Proved that PR74 recovery caused one complete PR70 workspace fingerprint after
  every successful project: Maven performed 940,470 hashes and 950,338 reads with
  recovery, versus 10,005 hashes and 19,873 reads without it.
- Retained the verified fingerprint set for one recovery operation and refreshed
  only each completed project; no persistent cache, schema change, checkpoint
  batching, or reduced journal/state-save frequency was introduced.
- Preserved full encoded semantic results in interrupted journals so resumed
  dependency values cannot degrade to report-only metadata.
- Added an isolated, source-free recovery diagnostic and regression coverage for
  sequential/concurrent checkpoint counts, snapshot validation, mutation
  invalidation, deterministic evidence, and production resume boundaries.
- Advanced the result producer fingerprint to v5 so pre-M2.1 report-only semantic
  journals and PR70 state are invalidated rather than silently reused.
- Measured Maven recovery at 248.292 seconds before and 97.033 seconds after under
  an isolated unprofiled protocol, a 60.92 percent reduction with identical
  deterministic semantic evidence.

## M2.0 performance measurement foundation

- Added an opt-in, run-local measurement model with stable phase IDs, explicit
  measured/unavailable/unsupported states, source-free filesystem counters, and
  best-effort process-memory probes.
- Added `atlas analyze --profile`, `--profile-output`, `--profile-memory`, and
  owned-lifetime `--profile-python-memory` while preserving normal stdout and the
  existing PR96 `atlas profile` contract.
- Added the same opt-in sidecar controls to deterministic `atlas ai explain`
  projection while excluding provider latency from Atlas phase measurements.
- Added atomic, versioned JSON sidecars and concise human summaries on stderr without
  placing operational metrics in semantic context or snapshots.
- Kept aggregation evidence honest: additive work, inclusive sample sums, and
  non-additive distributions are distinct; concurrent process CPU is unavailable
  rather than misattributed, while existing worker queue facts remain scope-local.
- Marked filesystem observations explicitly partial, counted physical bytes without
  re-encoding full source payloads, and made sidecar/tracemalloc finalization unable
  to change or mask Atlas command outcomes.
- Added bounded, source-free repeat-read correlation with exact untracked coverage,
  deterministic sampling coverage, strict provider/cross-field validation, and an
  additive history annotation that excludes profiled timings from adaptive-worker
  decisions without hiding those runs from normal history.
- Documented the architecture, schema, CLI behavior, and evidence limitations; no
  optimization, roadmap change, or enterprise-scale performance claim is included.

## M1.1 hardening - IntelliJ fixture source isolation

- Added evidence-ordered Java source selection that keeps complete repository
  inventory while excluding fixture-only `testData`/`test-data` and structured
  resource inputs from compiled semantics.
- Reused bounded literal Gradle evidence and root-registered IntelliJ IML metadata,
  with deterministic containment, source/resource precedence, and canonical file
  identity; no build logic is executed.
- Preserved standard test, test-fixture, JMH, generated, versioned, explicit custom,
  and independently owned nested-project sources, plus genuine duplicate rejection.
- Advanced the analysis-result producer fingerprint to v4 so persistence and crash
  recovery invalidate stale pre-classification semantic results.
- Resolved both original IntelliJ fixture collisions. The 119-project corpus remains
  diagnostic at 118/119 because two legitimate registered JPS modules define the
  same qualified type and Atlas does not yet model their module-scoped identity.
- Validated the complete Atlas suite at 3,827 passed and 3 platform skips; Maven at
  92/92, Quarkus at 1,442/1,442, Spring at 29/29, and Elasticsearch at 545/545 with
  the documented portable semantic gates preserved.
- Kept accepted benchmark goldens unchanged; the IntelliJ failure correctly prevents
  snapshot publication and canonical promotion.

## M1.1 hardening - Elasticsearch benchmark investigation

- Added narrowly verified recursive Gradle membership discovery that remains within
  literal roots and fails closed for unsupported helper behavior, path identities,
  symlinks, and preceding unmodeled settings membership mutations.
- Separated version-specific Java overlays only when an exact baseline counterpart
  is analyzed, and retained additive version-specific files.
- Added conservative source-set-scoped symbol identity only after a duplicate type
  is proven across conventional Gradle source sets; unavailable cross-source-set
  architecture relations are omitted and reported as partial rather than guessed.
- Advanced the analysis-result producer fingerprint to v3 so PR70 persistence and
  PR74 recovery invalidate stale pre-hardening analysis results.
- Validated the complete Atlas suite at 3,803 passed and 2 skipped; Elasticsearch
  twice at 545/545; Maven at 92/92; Quarkus at 1,442/1,442; and Spring at 29/29.
- Kept the accepted Maven and Quarkus golden baselines unchanged.

## M1 hardening — portable semantic paths and Java member identity

- Narrowed UNC detection to complete server/share roots while retaining recursive
  rejection of literal, encoded, nested, device, drive, URI, temp, and POSIX machine
  paths in portable artifacts.
- Corrected Java field initializers containing constructor or factory calls so they
  no longer produce malformed synthetic method symbols.
- Preserved legal field/nested-type name collisions through kind-aware global symbol
  identity while retaining exact duplicate rejection and deterministic lookup.
- Added an analysis-result producer fingerprint to PR70 persistence and PR74 recovery;
  legacy payloads remain readable but stale pre-fix results are invalidated.
- Validated Spring twice at 29/29 with stable portable semantics, Maven at 92/92,
  Quarkus at 1,442/1,442, and the complete Atlas suite at 3,772 passed with one
  platform skip.
- Kept Maven and Quarkus M1.1 goldens unchanged and deferred Spring promotion to a
  reviewed M1.2 baseline transition because corrected producer semantics change all
  three repositories.

## M1 hardening — Spring Framework Gradle discovery

- Added bounded static parsing for top-level literal Gradle `include(...)` and
  Groovy command-style `include "module"` declarations without executing Gradle.
- Preserved explicitly declared Gradle children beyond generic marker discovery,
  merged settings evidence into projects already found through another marker, and
  retained deterministic project ownership and ordering.
- Made ambiguous resolved aliases, flattened project-name collisions, conditional
  control flow, and expression continuations fail closed instead of fabricating
  workspace membership.
- Separated a version-specific Gradle Java file only when its exact baseline path is
  also analyzed, emitting an explicit warning while retaining additive custom source
  sets such as test fixtures and benchmarks.
- Kept variables, conditional declarations, included builds, directory remapping,
  custom build-file dependency extraction, and alternative source-set modeling
  explicitly unsupported instead of guessing.
- Validated the pinned Spring Framework checkout twice with 29 discovered projects,
  29 successes, stable semantic/report/explanation hashes, and no weakening of
  duplicate Java type detection.

## PR134 — Explain Anything

- Added the first canonical subject resolver over PR129 identities with exact-ID,
  scoped qualified-name, and unique normalized-name resolution plus bounded explicit
  ambiguity candidates.
- Added immutable structured explanations for repository/workspace, project,
  package/module, class/type, method, dependency, framework, build system/real build
  target, generic symbol, and canonical relationship subjects.
- Reused PR130 evidence, confidence, lineage, and deterministic-ID contracts; every
  available or partial fact retains exact traceable evidence closure and limitations.
- Bound PR131 root and relationship evidence to the persisted path for the requested
  subject, and kept absent or malformed repository inventory counts unknown instead of
  manufacturing zero values.
- Bound PR130 relationship evidence to the finding's canonical participants and
  rejected non-trivial PR131 paths without their own relationship evidence.
- Added deterministic whole-fact context selection with a 7,000-token engine ceiling,
  exact omission counts, stable context digests, and no partial citation records.
- Replaced targeted full-snapshot prompts with bounded source-free structured context
  while keeping optional provider prose separate from authoritative facts.
- Added provider-free canonical JSON output and kind, project, language, relative-path,
  target, and relation constraints to the existing `atlas ai explain` command.
- Preserved the accepted default PR133 repository explanation, old snapshots, public
  request/result field prefixes, conversation memory, and the sole PR129 graph.
- Attached structured PR134 metadata to default API results without changing PR133
  Markdown, and hardened deterministic candidate/count parsing plus Windows, POSIX,
  and repeatedly encoded absolute-path rejection.
- Added deterministic synthetic 10K/100K/1M indexed-resolution and context-selection
  benchmark support plus checksum-verified Maven/Quarkus snapshot replay.

## PR133 — AI Repository Report

- Added one immutable, deterministic repository-report model composed from PR127
  through PR132 facts, with exact serialization round trips and stable lineage.
- Added executive, architecture, repository-health, strengths, weaknesses, risks,
  technical-debt, quality, and recommendation sections with explicit capability and
  observation states; unavailable analyses remain visible instead of being filled.
- Reused the PR129 canonical graph for bounded in-degree, out-degree, fan-in, and
  fan-out summaries without introducing another graph or analyzer.
- Reused PR130 evidence and confidence contracts, verified upstream citations, and
  kept legacy producer confidence fields distinct from shared confidence results.
- Published additive `semantic_context.repository_report` data and added a
  deterministic 7,000-token selector that retains whole items and their citations.
- Updated default `atlas ai explain` to prefer the persisted report without creating
  an LLM provider; explicit subjects retain the existing grounded provider path.
- Preserved old snapshot explanations, removed duplicate legacy rendering for PR133
  snapshots, and excluded raw source, absolute paths, and author identities.
- Bounded report items, evidence references, limitations, and rendered repetition
  with exact omitted counts and compact cross-references.
- Bound every retained evidence record to its citing item and report lineage,
  rejected inconsistent selection/count metadata, and canonicalized reordered
  section and nested-evidence inputs.
- Added five-repeat synthetic, Maven, and Quarkus replay measurements; the 149K-node
  Quarkus report remains deterministic, builds below two seconds p95, and adds
  0.030312% to its replayed snapshot.

## PR132 — Risk and Hotspot Analysis

- Added deterministic, top-k repository risk indicators over the PR129 canonical
  graph using documented weights, comparable cohorts, exact raw units, bounded
  evidence, explicit availability, and separate confidence.
- Added positive distinct-neighbour fan-in/fan-out, project inventory size,
  bounded Git change-frequency and change-author-concentration inputs without
  interpreting absent graph relations or missing test mappings as zero.
- Added file-size completeness metadata so stat failures make size unavailable,
  and hardened external metric evidence so free-form upstream text cannot enter
  source-free PR132 snapshots.
- Published an additive, source-free `risk_analysis` snapshot field and compact
  repository-explanation projection while preserving older snapshot behavior.
- Added exact serialization, lineage-aware caching, scope exclusions, heatmaps,
  deterministic scale/replay benchmarks, and focused adversarial tests.
- Ranked with full-precision values before deterministic presentation rounding,
  froze and synchronized cached reports, and bounded producer, evidence, and
  heatmap projections with explicit omitted counts.
- Unified test/source scope classification and made bounded Git evidence
  locale-independent on Windows while preserving traceable UTF-8 paths.

## Atlas AI Explain accuracy hardening

- Replaced the default repository LLM response with deterministic Markdown
  rendered from a bounded, source-free Atlas projection; targeted subject
  explanations retain the existing provider path.
- Added explicit inventory count/byte aliases while preserving legacy repository
  summary keys and older snapshot compatibility.
- Added mathematically exact language percentages, overlapping build-system
  counts without percentages, conservative framework/technology presentation,
  unresolved entry-point roles, and evidence-aware architecture suppression.
- Removed broad Maven substring matching that confused internal integration and
  reactive artifact names with Spring or React adoption.

## PR131 — Dead Code and Reachability Analysis

- Added deterministic production/test reachability over the PR129 graph and
  optional authoritative specialized call graphs.
- Added structured roots, bounded paths, conservative states, project coverage,
  capability availability, confidence, evidence, lineage, and exact round trips.
- Required complete call/root coverage and an explicit closed-world scope before
  producing a `likely_dead` candidate.
- Protected public/protected, framework-managed, reflection-discovered, Service
  Loader, generated, annotation-managed, test-only, and external API subjects.
- Published additive source-free `semantic_context.reachability` data and a compact
  repository-explanation projection.
- Preserved PR129, PR130, specialized CFG/call APIs, older snapshots, and failed-run
  snapshot publication behavior.

## PR130 — Design Pattern Detection

- Added deterministic Strategy and Builder detection through the normal Java
  pipeline and optional call-evidence support for five additional patterns.
- Added shared source-free evidence records, deterministic confidence, lineage,
  bounded caching, and compact repository-explanation integration.
- Preserved canonical and specialized graph contracts.

## PR129 — Unified Knowledge Graph

- Consolidated PR125 semantic facts and PR127 repository metadata through the
  existing queryable `KnowledgeGraph`.
- Added repository, workspace, project, package, module, type, method, field,
  dependency, framework, and build-system nodes.
- Populated resolved imports, Java/Python inheritance, verified Java
  overrides, dependencies, and ownership with deterministic evidence.
- Kept composition, calls, and concrete build targets explicitly unpopulated
  until reliable normal-pipeline evidence exists.
- Preserved the PR27 builder API and the PR125 serialized node fields.
- Added deterministic graph serialization, restoration, kind queries, and
  exact-name queries without inspecting raw source.

## PR128 — Architecture Detection

- Added evidence-backed detection for eight repository architecture styles.
- Reported dependency directions, cycles, bounded contexts, ports/adapters,
  and infrastructure layers.
- Consumed existing source-free repository summaries and semantic graphs.
- Preserved and optionally reused the existing Java architecture graph.
- Prevented substring false positives such as treating `Support` as a port.
- Required structural relationships for weak naming-based architecture
  patterns and exposed dependency-check execution evidence.
- Added explicit reconciliation metadata for modular-monolith/microservices
  conflicts.

## PR127 — Repository Summary Engine

- Composed existing inventory, workspace, framework, and dependency services
  into one deterministic repository model.
- Added language, build-system, framework, entry-point, module, source-role,
  generated-source, and dependency summaries.
- Prevented nested workspace projects from being double-counted.
- Published source-free repository metadata in semantic snapshots for AI use.
- Prioritized a compact repository summary in default `atlas ai explain`
  prompts while preserving detailed subject explanations.
- Distinguished declared dependency records from distinct manifests and added
  project-local versus test/sample framework evidence.

## PR126 — Dependency Intelligence

- Normalized Maven, Gradle, pip, Poetry, npm, and Cargo declarations.
- Added deterministic ecosystem, version, scope, optionality, and source data.
- Persisted dependency facts through recovery and semantic snapshots.
- Kept parsing local and non-executing; malformed manifests remain isolated.

## PR125 — Cross-Language Workspace

- Added a shared deterministic semantic graph for Java, Python, and TypeScript.
- Added a built-in TypeScript/TSX declaration frontend through PR124.
- Published project-scoped graph nodes plus ownership and resolved-import edges.
- Kept existing semantic snapshot fields backward compatible.

## PR124 — Analyzer Registry

- Replaced hard-coded language routing with a synchronized analyzer registry.
- Kept Java and Python as built-in analyzers.
- Added a deterministic plugin contract for Kotlin, JavaScript, TypeScript,
  Rust, Go, and additional language frontends.
- Preserved the `SemanticProjectAnalyzer` facade and stable report shape.

## PR123 — Project-Scoped Java Type Identity

- Scoped global symbol identity and lookup by workspace project.
- Allowed duplicate Java qualified names across independent projects.
- Preserved duplicate rejection within a project with source-aware diagnostics.
- Kept legacy unscoped symbol IDs, persistence, and lookup compatibility.

## PR122 — Python Semantic Analyzer

- Added AST-backed Python modules, classes, functions, decorators, async declarations, imports, globals, dataclasses, enums, annotations, and docstrings.
- Published Python symbols and type annotations through semantic snapshots and AI context.
- Preserved Python type tables across workspace recovery and mixed Java/Python analysis.

## PR121 — Complete AI Context Pipeline Integration

- Replaced the default file-count analyzer with project-level semantic documents.
- Connected parsed Java ASTs, diagnostics, and global symbols directly to ASS publication.
- Added source-free, backward-compatible persistence for semantic recovery results.
- Preserved deterministic workspace reports and legacy/custom analyzer behavior.
- Hardened runtime discovery against hidden, generated, and inaccessible tool trees.
- Normalized semantic documents to stable structured values in JSON reports.

## PR107 — LLM Provider Abstraction

- Added provider-neutral LLM requests, responses, chunks, and provider protocol.
- Added a synchronized provider registry and deterministic retry/timeout policy.
- Added safe streaming retries that never duplicate already-emitted output.

## Chronological index (newest first)

- **PR106:** Plugin Trust Model
- **PR105:** Public API Boundary
- **PR104:** Large-Workspace Benchmarks
- **PR103:** Structured Logging
- **PR102:** Global Symbol Concurrency
- **PR101:** Semantic Table Builders
- **PR100:** Atlas 2.0 Stabilization
- **PR96–PR99:** Profiler, adaptive scheduling, distributed workers, and governance
- **PR91–PR95:** SARIF, Git diff, CI templates, history, and dashboard
- **PR86–PR90:** Rule authoring, testing, metadata, fixes, and packs
- **PR81–PR85:** Workspace LSP and editor integration
- **PR74–PR80:** Recovery, unified CLI, reports, baselines, watch, gates, and packaging
- **PR67–PR73:** Workspace model, persistence, configuration, events, and concurrency
- **PR36–PR66:** Interprocedural analysis, security platform, plugins, policies, LSP, and API
- **PR18–PR35:** Project inventory, indexes, symbols, graphs, search, and Spring modeling
- **PR1–PR17:** Semantic foundations, typing, flow analysis, patterns, CFG, and reachability

Detailed release notes follow in their original historical sections. The index
is the canonical navigation order; per-PR documentation in `docs/` contains the
complete implementation detail.

## Post-PR106 production hardening

- Completed strict incremental-state persistence round trips.
- Added immutable indexes to global symbol snapshots.
- Replaced production wildcard imports with explicit dependencies.
- Applied bulk type construction to expression inference, clarified pass APIs,
  and preserved Java result compatibility.
- Added deterministic adversarial parser coverage and architecture guidance.

## PR77 — Finding Baselines

- Added cross-language finding baselines with stable project-aware fingerprints.
- Added atomic, checksummed baseline persistence and strict schema validation.
- Added deterministic new/existing comparison and filtering of accepted findings.
- Integrated `--baseline` and `--write-baseline` with `atlas analyze` and `atlas check`.
- Applied baseline filtering consistently to text, JSON, JSONL, and SARIF output.

## PR76 — CLI Output Formats

- Added deterministic `text`, `json`, `jsonl`, and SARIF 2.1.0 output for `atlas analyze` and `atlas check`.
- Added stable structured report payloads that omit timing-dependent fields.
- Added one-record-per-project JSONL output with a final summary record.
- Added sorted SARIF findings, rule metadata, severity mapping, locations, and analysis metadata.
- Preserved PR75 plain-text output and command exit-code behavior.

## PR75 — Unified CLI

- Added the `atlas` executable with `analyze`, `check`, `watch`, `config`, and `plugins` commands.
- Unified workspace execution, PR74 recovery, PR73 concurrency, PR71 configuration, and plugin discovery behind one deterministic command surface.
- Preserved the existing `moughorai` executable and `ask` command.
- Kept output intentionally plain-text; structured formats remain scoped to PR76.
- Added snapshot initialization for `watch`; continuous analysis remains scoped to PR78.

## PR74 — Workspace Recovery Manager

- Added atomic, checksummed recovery journals for interrupted workspace analyses.
- Added deterministic status inspection and selective resume of unfinished projects.
- Invalidated corrupt, inconsistent, stale, workspace-mismatched, and configuration-mismatched journals.
- Integrated recovery with workspace persistence, layered configuration, lifecycle events, and concurrent execution.
- Preserved the existing orchestration API while adding an opt-in recovery manager.

## PR73 — Concurrent Project Execution

- Added dependency-aware parallel workspace analysis with configurable worker limits.
- Preserved deterministic topological report ordering across concurrent completion.
- Added cancellation, fail-fast scheduling, cache reuse, failure blocking, and incremental-plan support.
- Added regression coverage for concurrency limits, events, dependency results, and sequential compatibility.

## PR71 — Workspace Configuration Layers

- Added deterministic layered workspace configuration resolution.

## PR70 — Persistent Workspace State

- Added atomic, checksummed workspace state persistence with selective project restoration and orchestrator integration.

## PR69 — Workspace Analysis Orchestrator

- Added deterministic dependency-aware workspace analysis execution, result reuse, failure blocking, cancellation, and incremental-plan integration.

## PR68 — Incremental Workspace Watcher

- Added portable workspace file snapshots, deterministic file events, rename detection, debounce/coalescing, and dependency-aware incremental invalidation plans.

## PR67 — Workspace & Project Model

- Added deterministic multi-project workspace loading, discovery, dependency planning, impact analysis, and content snapshots.

## Atlas Sprint 3 - PR #7

### Added
- Deterministic method and constructor overload resolution.
- Exact matching, primitive widening, boxing/unboxing, Object fallback, and varargs ranking.
- Static-versus-instance context validation.
- Diagnostics for missing, incompatible, ambiguous, and context-invalid invocations.
- Immutable `MethodSignature` and `MethodResolutionResult` APIs.

### Validation
- Focused method-resolution tests.
- Complete regression suite required before commit and tag.
## Atlas Sprint 3 - PR #6

### Added
- Statement and control-flow type checking for blocks, local declarations, returns, throws, `if`, and `while`.
- Boolean-condition validation and full-expression declaration compatibility checks.
- Return-type checking using an explicit pass option or `expected_return_type` document metadata.
- Loop-context validation for `break` and `continue`.
- Basic unreachable-statement warnings after non-completing statements.
- `StatementTypeCheckingPass` and reusable `check_statement_types` API.

### Validation
- Focused statement-type-checking tests.
- Complete regression suite required before commit and tag.
## Atlas Sprint 3 - PR #5

### Added
- Expression type inference for literals, names, unary, binary, assignment, cast, object creation, array access, and conditional expressions.
- Java numeric promotion, boolean-result operators, and String concatenation.
- Expression diagnostics and immutable `TypeTable` integration.
- `ExpressionTypeInferencePass` using variable symbols produced by PR #4.

### Validation
- Focused expression-inference tests.
- Complete regression suite required before commit and tag.
## Atlas Sprint 3 - PR #4

### Added
- Immutable `VariableSymbol` and `SymbolTable` semantic models.
- Explicit and `var` local-variable type inference.
- Java primitive widening compatibility.
- Variable initializer mismatch diagnostics.
- `VariableTypeInferencePass` integration with `SemanticDocument`.

### Validation
- Focused variable-inference tests.
- Complete regression suite required before commit and tag.

## Atlas PR8 - Generic Type Inference

- Added explicit generic method type-parameter inference.
- Added nested generic and array constraint collection.
- Added explicit type-argument validation and generic substitution.
- Added conflict, unresolved-variable, and arity diagnostics.

## Atlas PR9 - Lambda and Method Reference Typing

- Added functional-interface target descriptors.
- Added implicit and explicit lambda parameter validation.
- Added lambda return compatibility and primitive widening.
- Added static, bound, unbound, and constructor method-reference resolution.
- Added diagnostics for arity, parameter, return, ambiguity, and context mismatches.

## Atlas PR10 - Constant Folding and Compile-Time Evaluation

- Added a reusable compile-time constant value model and expression evaluator.
- Added Java-style integer promotion, overflow, division, remainder, shifts, and unsigned shifts.
- Added unary, arithmetic, bitwise, boolean, comparison, and string-concatenation folding.
- Added primitive constant casts and named constant propagation.
- Added explicit errors for non-constant expressions and integral division by zero.

## Atlas PR11 - Flow-Sensitive Analysis and Definite Assignment

- Added a reusable variable-state lattice for definite and possible assignment.
- Added branch joins that ignore terminated paths.
- Added conservative while-loop and mandatory do/while-loop transfer rules.
- Added final-variable single-assignment validation.
- Added unassigned-read, duplicate-declaration and unreachable-statement diagnostics.
- Added a semantic-pass facade and focused regression coverage.

## Atlas PR11.5 - Architecture Cleanup

- Consolidated primitive widening conversions into `semantic.types.relations`.
- Added stable `ATLAS-FLOW-*` codes and a standard diagnostic adapter.
- Documented semantic pass ordering and the mutable flow-state contract.
- Added focused architectural regression tests.

## Atlas PR12 - Java Pattern Matching Foundations

- Added an AST-independent Java type-pattern semantic model.
- Added true-edge and false-edge scopes for pattern variables.
- Added guarded `&&`, conservative `||`, and negation flow composition.
- Added duplicate, invalid-name, primitive-pattern, and compatibility diagnostics.
- Added standard `Diagnostic` conversion for pattern errors.
- Added optional class-hierarchy compatibility checks and a facade API.

## Atlas PR13 - Sealed Hierarchies and Exhaustive Switches

- Added parser-independent sealed, final, and non-sealed type declarations.
- Added a validated hierarchy graph with permits checks and cycle detection.
- Added recursive finite-leaf discovery for nested sealed hierarchies.
- Added switch exhaustiveness analysis for type patterns and default cases.
- Added duplicate-case and type-pattern dominance diagnostics.
- Added standard Diagnostic conversion for hierarchy and switch errors.
- Added 24 focused regression tests for hierarchy and switch semantics.

## Atlas PR14 - Java Record Patterns

- Added parser-independent record declarations and recursive record-pattern nodes.
- Added typed, var, unnamed, and nested component patterns.
- Added recursive decomposition validation and binding extraction.
- Added generic record component substitution.
- Added component-count, type-compatibility, duplicate-binding, nested-pattern,
  and unsupported-decomposition diagnostics.
- Added standard Diagnostic conversion for record-pattern errors.
- Added 28 focused regression tests for Java record-pattern semantics.

## Atlas PR15 - Control Flow Graph Infrastructure

- Added parser-independent basic blocks, typed flow edges, and CFG diagnostics.
- Added structured CFG construction for sequences, branches, loops, break, continue, return, and throw.
- Added reachability, predecessor/successor queries, reverse post-order, and dominator computation.
- Added 41 focused regression tests.

## Atlas PR16 - Flow-Sensitive Nullability Analysis

- Added a null-state lattice and environment merging over Atlas CFGs.
- Added null-check branch refinement, loop fixpoint propagation, assignment transfer functions, and dereference diagnostics.
- Added 40 focused regression tests.

## Atlas PR17 - Reachability and Dead-Code Analysis

- Added conservative CFG reachability with constant-condition pruning.
- Added dead-block and dead-statement diagnostics.
- Added guaranteed-return and missing-return analysis.
- Added invalid break/continue validation and infinite-loop detection.
- Added 52 focused regression tests.
## PR72 — Workspace Event Bus

- Added a thread-safe deterministic workspace event bus with filtering, priorities, one-shot subscriptions, bounded history, and structured delivery reports.
# PR78 - Watch mode

- Added continuous and bounded polling modes to the unified `atlas watch` command.
- Connected debounced file changes to incremental dependency-aware analysis.
- Preserved deterministic report ordering and concurrent project execution.
- Kept the existing one-shot watch snapshot behavior for backward compatibility.
# PR79 - Quality gates

- Added report-level severity and finding-count quality gates.
- Added independently configurable finding and analysis-failure exit codes.
- Integrated workspace configuration, CLI overrides, and PR77 baseline filtering.
- Preserved the prior `atlas check` behavior when no gate is configured.
# PR80 - Atlas 1.0 packaging

- Promoted the distribution and runtime version to 1.0.0.
- Corrected setuptools discovery to package the repository's actual modules.
- Added release metadata, README, MIT license, and canonical version API.
- Added `atlas --version` and verified the built wheel and console entry point.
# PR81 - Workspace LSP

- Added workspace-aware document routing to the most-specific Atlas project.
- Added resolved project configuration to workspace analyzer callbacks.
- Added workspace diagnostic requests and workspace-folder lifecycle support.
- Preserved the PR65 document-local language-server API.
# PR82 - Incremental editor analysis

- Added ordered LSP range-edit application and validated document versions.
- Added incremental workspace analyzer callbacks with normalized change sets.
- Added full-analysis fallback for existing PR81 analyzers.
- Added deterministic publication of incremental findings.
# PR83 - LSP code actions

- Added deterministic explain, suppress, and rescan actions for diagnostics.
- Added LSP code-action capability advertisement and context filtering.
- Added a provider protocol for host-defined code actions.
- Kept actions command-based; source auto-fixes remain reserved for PR89.
# PR84 - LSP configuration synchronization

- Added synchronized client configuration overrides with generation tracking.
- Added scoped `workspace/configuration` responses.
- Added watched `atlas.yaml` reload with rollback on invalid configuration.
- Added deterministic diagnostic republishing and notification draining.
# PR85 - LSP progress reporting

- Added deterministic LSP work-done progress tokens and lifecycle messages.
- Added percentage, message, completion, and cancellation state.
- Integrated progress reporting with workspace diagnostics in URI order.
- Added notification queue delivery through the PR84 LSP flow.
# PR86 - Rule authoring API

- Added a public cross-language rule protocol and immutable author context.
- Added validated finding reporting with locations, severities, and properties.
- Added deterministic rule execution, deduplication, and exception attribution.
- Added a sorted, conflict-safe rule registry.
# PR87 - Rule testing framework

- Added dependency-free rule test cases, harnesses, and deterministic results.
- Added exact and subset expected-finding matching.
- Added clean/count assertions with descriptive failure output.
- Added stable multi-case and multi-rule execution.
# PR88 - Rule metadata

- Added validated rule titles, descriptions, categories, tags, languages, and links.
- Added enablement, deprecation, and replacement metadata.
- Added decorator attachment and backward-compatible metadata synthesis.
- Added deterministic rule catalogs and metadata filtering.
# PR89 - Auto-fix framework

- Added safe and review-required rule fixes with validated source edits.
- Added deterministic fix planning, stale-source checks, and conflict detection.
- Added in-memory preview/application with review gating.
- Added root-confined, staged file application with rollback on replacement errors.
# PR90 - Rule pack builder

- Added validated rule pack specifications and explicit rule entry points.
- Added canonical metadata manifests with per-file sizes and SHA-256 hashes.
- Added byte-reproducible ZIP construction with fixed timestamps and permissions.
- Added archive schema, path, declaration, size, and checksum verification.
# PR91 - SARIF 2.1.0

- Added a reusable validated SARIF 2.1.0 workspace exporter.
- Added deterministic rule descriptors, results, locations, and fingerprints.
- Added PR88 metadata enrichment, invocation status, automation IDs, and fixes.
- Integrated the exporter with the backward-compatible PR76 CLI format.
# PR92 - Git diff analysis

- Added safe Git working-tree, staged, and base/head diff collection.
- Added deterministic unified-diff files, hunks, renames, binary flags, and lines.
- Added report filtering to findings on newly added lines.
- Added `analyze` and `check` Git diff CLI options after PR77 baseline filtering.
## PR93 — CI Templates

- Added deterministic GitHub Actions, GitLab CI, and Azure Pipelines templates.
- Added `atlas ci` with canonical output paths, Python version selection, and safe overwrite controls.
- Configured generated jobs to run Atlas quality gates and retain or upload SARIF results.
- Added atomic template writes while preserving all existing CLI behavior.
## PR94 — Historical Database

- Added a versioned, transactional SQLite database for workspace analysis history.
- Recorded stable run metadata and ordered per-project results after CLI filtering.
- Added deterministic history queries, lookup, pagination, and retention pruning.
- Added `atlas history` while preserving existing analysis report formats and exit codes.
## PR95 — Dashboard

- Added a self-contained HTML dashboard backed by the PR94 historical database.
- Added stable run summaries, status metrics, finding counts, and project activity.
- Added responsive, accessible rendering without external assets or network services.
- Added `atlas dashboard` with deterministic output and bounded history selection.
## PR96 — Performance Profiler

- Added opt-in elapsed-time profiling with thread-safe concurrent sample collection.
- Added stable aggregate call, total, minimum, maximum, and average metrics.
- Added analyzer wrapping and workspace-level timing through `atlas profile`.
- Preserved ordinary analysis behavior and avoided scheduler policy changes.
## PR97 — Adaptive Scheduler

- Added deterministic worker recommendations from dependency-wave parallelism.
- Added CPU and user caps plus historical-duration overhead avoidance.
- Added opt-in `--adaptive` execution for `atlas analyze` and `atlas check`.
- Reused PR73 concurrency without changing default scheduling behavior.
## PR98 — Distributed Workers

- Adapted workspace projects to the PR58 transport-neutral lease coordinator.
- Added deterministic project jobs, dependency results, capabilities, retries, and failure blocking.
- Added stable distributed execution and workspace report conversion.
- Preserved local and concurrent executors without introducing a mandatory network stack.
## PR99 — Governance

- Added role-based authorization for view, analysis, fixes, distribution, configuration, and rules.
- Added project, worker, and force-analysis policy constraints with PR71 option parsing.
- Added append-only, SHA-256-chained governance audit records and verification.
- Added opt-in `atlas governance` audit validation without changing existing CLI authorization.
## PR100 — Atlas 2.0 Stabilization

- Promoted the canonical package, CLI, and SARIF tool version to Atlas 2.0.0.
- Added end-to-end compatibility coverage across CLI, history, dashboard, CI, profiling, and governance.
- Updated release documentation and retained plugin/rule API 1.x compatibility.
- Added final packaging, deterministic-output, and clean-replay verification.
## PR101 — Semantic Table Builders

- Added validated mutable builders for bulk type and symbol table construction.
- Added additive bulk APIs while preserving immutable copy-on-write methods.
- Refactored variable inference to freeze semantic tables once per pass.
- Added scaling benchmarks and a 250-declaration regression test.
## PR102 — Global Symbol Concurrency

- Made every `GlobalSymbolDatabase` operation linearizable under one `RLock`.
- Added atomic batch insertion with all-or-nothing duplicate validation.
- Added detached, immutable, versioned snapshots for multi-step readers.
- Added contention, duplicate-race, concurrent removal, and invariant tests.
## PR103 — Structured Logging

- Added opt-in JSON/text logging with correlation IDs and stable event schemas.
- Bridged all workspace lifecycle events without changing event subscriptions.
- Added recursive sensitive-field redaction and Atlas-only logger configuration.
- Added CLI logging controls while preserving silent default output.
## PR104 — Large-Workspace Benchmarks

- Added a reproducible 23,000-file, multi-project benchmark using production indexing and workspace fingerprinting.
- Added phase timings, throughput, peak-memory reporting, and deterministic content verification.
- Kept generated corpora temporary by default and avoided machine-dependent performance test thresholds.
## PR105 — Public API Boundary

- Added a curated, versioned `moughorai.public_api` facade for external consumers.
- Added a frozen constructor-signature manifest and deterministic compatibility checks.
- Preserved legacy imports and object identity while documenting versioning and deprecation policy.
## PR106 — Plugin Trust Model

- Documented the exact plugin integrity and permission controls Atlas enforces.
- Explicitly documented in-process execution, opt-in defaults, TOCTOU risk, and absent sandbox/signature guarantees.
- Added production isolation guidance, trust assumptions, and documentation contract tests.
## PR108 — Workspace Context Builder

- Added deterministic semantic JSON snapshots for workspace, project,
  diagnostic, history, symbol, type, and performance data.
- Added strict normalization that rejects process-specific context values.
## PR109 — Prompt Builder

- Added deterministic, versioned semantic prompt templates.
- Added provider-neutral token estimation and preflight input budgets.
- Preserved the existing `PromptBuilder` API.
## PR110 — Ollama Integration

- Added local Ollama chat completion and NDJSON streaming through the PR107
  provider interface.
- Integrated `llm.provider`, `llm.endpoint`, and `llm.model` with PR71 layered
  configuration.
## PR111 — Atlas Semantic Snapshot

- Added immutable, checksummed semantic snapshot archives under `.atlas/ass/`.
- Added atomic `latest.ass` publication, workspace fingerprints, analyzer
  versioning, history references, and offline PR108 context restoration.
## PR112 — Atlas AI CLI

- Added the `atlas ai` namespace with `context`, `explain`, `ask`, `review`,
  and `fix` entry points.
- Added deterministic ASS context output and explicit future-engine boundaries.
## PR113 — Conversation Memory

- Added versioned, workspace-scoped SQLite conversation memory.
- Added ordered messages and structured references to Atlas semantic facts.
## PR114 — Explain Engine

- Added grounded Markdown explanations from ASS through the provider abstraction.
- Activated `atlas ai explain` with optional conversation-memory recording.
## PR115 — Review Engine

- Added semantic architecture reviews with deterministic category selection.
- Activated `atlas ai review` and conversation-memory recording.
## PR116 — Ask Engine

- Added grounded semantic questions with bounded conversation context.
- Activated `atlas ai ask` with durable follow-up memory.
## PR117 — Patch Engine

- Added grounded Git patch proposals with strict diff/path validation.
- Activated non-applying `atlas ai fix` with `git apply --check`.
## PR118 — Git Context

- Added deterministic branch, changes, commits, blame, PR metadata, and snapshot IDs.
- Added `atlas ai git-context`.
## PR119 — IDE Assistant

- Added a shared ASS-based protocol for five supported IDEs.
- Added semantic navigation and safe routing to Atlas AI engines.
## PR120 — Atlas AI 1.0

- Released the stable `moughorai.ai` facade and capability manifest.
- Added `atlas ai version` and end-to-end release verification.
- Documented Ollama as the only currently implemented AI provider.
## AI context pipeline integration fix

- Connected successful `atlas analyze` runs to PR108 semantic collection and
  PR111 ASS publication.
- Added real Java symbol aggregation plus compatible diagnostic/type collection.
- Ensured failed analyses cannot replace `latest.ass`.
