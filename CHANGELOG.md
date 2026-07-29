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

# Changelog

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
