# PR131 Existing Capabilities and Extension Record

## Baseline and specification routing

PR131 starts from commit `b42138b`, which contains PR130. The detailed design is
`docs/PR131_DESIGN.md`; the shorter root `PR131_DESIGN.md` remains compatible
architectural guidance. The official roadmap is
`docs/roadmap/IMPLEMENTATION_ROADMAP.md`, and the approved dependency matrix is the
root `ROADMAP_DEPENDENCY_MATRIX.md`. No duplicate roadmap documents are introduced.

## Existing components reused directly

- PR129 `KnowledgeGraph` and its canonical node IDs, ownership, inheritance,
  override, project dependency, and optional call relations remain the only
  repository graph.
- `moughorai.call_graph.CallGraph` remains the authoritative optional producer for
  resolved calls, constructors, unresolved call sites, and call coverage.
- `java_semantics.ReachabilityAnalyzer` and `data_flow.ControlFlowGraph` remain
  authoritative for bounded intra-method CFG reachability. PR131 does not replace
  or reinterpret their block-level results.
- `RepositorySummaryService` already publishes project entry-point paths, framework
  dependency evidence, and aggregate production, test, and generated file counts.
- `JavaSymbolIndex` already carries modifiers and annotations. The Java analyzer
  already builds this index and the `JavaArchitectureGraph`; PR131 can preserve
  required structured metadata without reparsing source.
- `SpringAnalysisService`, Spring component/injection models, JPA analysis, and
  framework profiles provide specialized structural evidence when supplied. They
  remain authoritative and are not duplicated by the reachability classifier.
- `SemanticContextCollector`, `WorkspaceContextBuilder`, and
  `SemanticSnapshotStore` are the additive, source-free publication path.
- PR130 `EvidenceRecord`, `EvidenceIndex`, `ConfidenceCalculator`, producer lineage,
  deterministic IDs, and bounded fingerprint-cache convention are reused.
- Workspace execution already continues independent projects when `fail_fast` is
  false and records failed/blocked scopes explicitly.

## Existing but currently disconnected evidence

- Canonical `calls` is supported by the PR129 model but is normally absent.
- Specialized call graphs can provide calls but are not produced by the normal
  semantic-context pipeline.
- Java modifiers and annotations exist in `JavaSymbolIndex` but were not preserved
  in global-symbol metadata before PR131.
- Framework-specific component, injection, endpoint, and persistence analyzers exist
  but their reports are not currently attached to the workspace semantic document.
- CFG reachability exists at method/block scope but CFG artifacts are not published
  in repository semantic snapshots.
- Repository entry points are file paths; a path can only become a symbol root when
  it resolves uniquely through structured symbol-source metadata.

## Missing reliable production evidence

- No durable producer currently publishes resolved or unresolved reflection targets.
- No durable producer currently publishes Java `ServiceLoader`, module
  `provides/uses`, or `META-INF/services` registrations.
- Generated and test classification is aggregate in repository summaries; per-symbol
  classification is unavailable in the normal snapshot.
- Publication/export metadata is insufficient to prove a public symbol is an
  externally supported API.
- Complete call coverage and closed-world scope are not established by the normal
  pipeline. Therefore normal-pipeline absence of calls cannot create `likely_dead`
  or `unreachable` repository-symbol findings.
- Statement/basic-block findings cannot be attached to canonical symbols until an
  existing CFG producer publishes a stable method-to-CFG association.

## PR131 extensions

- Add immutable reachability roots, findings, paths, capabilities, coverage,
  statistics, and report serialization using PR130 evidence/confidence contracts.
- Add a bounded deterministic multi-source traversal over canonical or specialized
  authoritative call relations without copying either graph.
- Add explicit structured adapters for framework, reflection, Service Loader,
  generated/annotation-managed, external API, source classification, CFG, and
  partial-project evidence. Missing adapters remain unavailable or insufficient.
- Preserve Java modifiers and annotations already produced by `JavaSymbolIndex` so
  visibility and annotation evidence survives persistence.
- Publish an additive `semantic_context.reachability` report and a compact bounded
  repository-explanation projection.
- Use a feature-local bounded cache keyed by canonical graph, optional evidence,
  configuration, producer, and schema fingerprints.

## Regression and compatibility risks

- **False dead-code claims:** incomplete calls, unresolved reflection, public or
  protected visibility, and unsupported source classifications must force
  `unused`, `unknown`, or protected states instead of dead states.
- **Identity ambiguity:** specialized method names must resolve uniquely within a
  project before they become canonical evidence; ambiguous mappings are ignored and
  reduce coverage.
- **Framework false positives:** annotations are accepted only through explicit
  structured framework evidence; suggestive names and package names contribute no
  evidence.
- **Snapshot growth:** store one bounded deterministic path per finding and only
  referenced evidence; compact AI projections contain counts and bounded examples.
- **Persistence compatibility:** Java metadata and the reachability section are
  additive. Older documents and snapshots without either field remain valid.
- **Partial failures:** failed projects are coverage limitations, never synthetic
  empty successes. Existing snapshot publication policy for failed workspace runs is
  not weakened.
- **PR130 stability:** PR131 consumes the shared evidence and confidence APIs without
  changing their formulas or serialized contracts.
