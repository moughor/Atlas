# PR140 Existing Capabilities

Status: completed capability audit and implementation disposition for PR140 v1.

## Baseline and authority

The official roadmap identifies PR140 as **Change Review**:

> Analyze Git diffs and produce impact analysis, architectural concerns, test
> recommendations, risk assessment, and migration advice.

PR140 is the roadmap item immediately after PR139 Interactive Engineering Chat. It is
a new Git-aware engineering-intelligence capability, not another chat phase. The
authoritative implementation baseline is PR139 commit
`2e8e27097dbcb43625639ea4234172409a8ed36c`.

The roadmap outcome is larger than one safe implementation because Atlas does not
currently persist paired before/after semantic state for Git commits. The first slice
therefore connects existing Git diff facts to current-snapshot canonical identity and
composes only conclusions that existing specialized services can support. Missing
semantic delta evidence remains explicit.

## Existing Git capabilities

| Capability | Existing owner | Reusable behavior | Boundary |
| --- | --- | --- | --- |
| Working-tree diff | PR92 `GitDiffService` | Deterministic tracked-file paths, hunks, added/removed line numbers, rename and binary flags | Untracked files are not included; source text is deliberately discarded |
| Staged diff | PR92 `GitDiffService` | `git diff --cached` through the same parser | Does not include unstaged changes |
| Base/head diff | PR92 `GitDiffService` | Validated refs and deterministic normalized diff facts | PR140 extends the same DTO additively with resolved full commit identities |
| Changed-line finding filter | PR92 `GitDiffFilter` | Select existing findings on added lines | It is not impact, architecture, test, risk, or migration review |
| Current branch/status/history | PR118 `GitContextService` | Branch, HEAD, changed paths, bounded commit metadata, source-free history counts | Status/history is not a semantic diff and must not duplicate PR92 collection |
| Historical churn | PR118 plus PR132 | Bounded repository-wide non-merge numstat history | Co-change and churn do not prove impact or architectural intent |

`GitDiffService` is the collection owner. PR140 must not add a second subprocess
wrapper, unified-diff parser, repository-status scanner, or history collector.

## Existing semantic and engineering capabilities

| Responsibility | Existing owner | Direct PR140 reuse | Current limitation |
| --- | --- | --- | --- |
| Canonical graph | PR129 `KnowledgeGraph` | Existing nodes, relationships, bounded adjacency, stable digest | Calls are normally absent; composition is unsupported; represented edges do not imply complete coverage |
| Exact identity | PR134 `CanonicalSubjectResolver` | Restore and validate graph-backed subjects | PR140 adds one bounded exact-path query with resolver-owned provenance; no fuzzy mapping is added |
| Symbol source metadata | Global symbols projected into snapshots | Workspace-relative source path per symbol where available | No persisted source span, end line, or hunk ownership |
| Dependency source metadata | PR129 canonical dependency evidence | Exact build/dependency source paths where represented | Does not prove runtime use or changed coordinate semantics |
| Impact | PR136 `ImpactPredictionService` | Bounded canonical traversal, breaking uncertainty, affected partitions, evidence closure | No compatible Git adapter, before/after API diff, full calls, or external-consumer proof |
| Tests | PR131 reachability consumed by PR136 | Existing direct test/reference paths when compatible | Missing calls or coverage cannot prove no test impact |
| Risk | PR132 `RiskAnalysisReport` consumed by PR136/search | Existing hotspot and risk context for canonical subjects | Risk prioritizes established facts; it cannot create an impact or change classification |
| Architecture | PR128 report | Repository observations and dependency cycles | No before/after comparison, intended layer rules, or shared evidence IDs on raw architecture labels |
| Refactoring | PR137 `RefactoringAdvisorService` | Fully revalidated dependency-cycle seam review | Other families are unsupported or insufficient; no general migration planner |
| Security | PR138 `SecurityIntelligenceService` | Remains authoritative for current-state findings | Intentionally not projected by PR140 v1 because it cannot attribute introduction or remediation |
| Semantic discovery | PR135 `SemanticSearchService` | Optional user-facing discovery | Relevance cannot establish path identity, impact, or change causality |
| Conversation | PR139 `AskEngine` | No use required by the first deterministic slice | Provider prose is untrusted and chat integration would expand scope |
| Architecture review prose | PR115 `ReviewEngine` | None as authority | Provider-backed, not Git-aware, and not a deterministic evidence producer |
| Patch proposals | PR117 `PatchEngine` | None | Non-applying proposal validation is not change review or migration proof |
| Evidence | PR130 `EvidenceRecord` and `EvidenceIndex` | Deterministic identity, deduplication, ordering, and closure | Feature DTO must still validate source-free references and exact closure |
| Confidence | PR130 `ConfidenceCalculator` | Evidence/coverage/agreement-based confidence | Cannot replace missing required evidence |
| Measurement | M2 `MeasurementSession` | Request-local phases, bytes, object counts, and memory observations | Measurement does not authorize a cache or concurrency |

## Existing persistence and compatibility contracts

| Contract | Existing behavior | PR140 requirement |
| --- | --- | --- |
| Semantic snapshot | Schema 1, content-derived snapshot ID, checksum envelope, atomic latest publication | Load and verify only; do not mutate or republish request-specific review state |
| Workspace fingerprint | Hash of deterministic per-project fingerprints | Use to classify current-snapshot alignment when available |
| Impact/refactoring persistence | PR136 and PR137 responses are ephemeral and reconstructible | Follow the same request-specific model |
| Security persistence | One bounded current-state report is co-published in the snapshot | Leave unchanged and do not project it into PR140 v1 |
| Conversation memory | Durable PR113/PR139 store with PR139 sanitization and lineage | Do not persist PR140 output in the first slice |
| Public API | Version `1.0` with 30 frozen constructor signatures | Do not alter existing signatures or the independent v1 fixture |
| CLI compatibility | `atlas ai review` is PR115; `atlas ai ask` and `chat` share `AskEngine` | Use a distinct change-review command and keep existing aliases unchanged |

Adding a `change_review` package-level service does not require exposing it through
the stable public facade. Public-facade expansion can be evaluated later only when an
external contract is required.

## Exact evidence available now

### Git change evidence

PR92 can establish that Git reported a normalized path and its added, modified,
deleted, renamed, binary, and hunk metadata for the observed selection. This is
structured repository metadata. It does not establish which declaration changed or
the semantic meaning of that change.

### Exact current path association

The PR134 resolver has enough persisted data to associate a safe relative path with
all current canonical subjects carrying that exact path. This is the missing adapter,
not a missing semantic parser. An additive exact-path query on the existing resolver
is reusable; a new resolver or PR135 relevance query is not.

The implemented query returns resolver-owned `PathCandidateEvidence` for every
retained candidate. Accepted provenance identifies exact `GlobalSymbol` source
metadata, canonical node path metadata, or declared-dependency source references.
The evidence set must exactly cover the returned candidates. Conflicting symbol
metadata is excluded rather than selected arbitrarily.

The association proves only that a canonical subject is recorded in that file. The
snapshot contains no symbol line span, so it cannot prove that a particular diff hunk
changed the subject.

When no exact path matches, the resolver may return the deepest containing project
as an explicit structural fallback. It may scope PR137 cycle context, but it is not
an exact changed subject and is never used as a PR136 impact root. File-level
confidence uses the shared calculator with required Git-change, path-mapping, and
exact-path-identity roles plus exact retained coverage and ambiguity. Fallback cannot
satisfy the exact-identity role.

### Existing downstream conclusions

Once a current subject is associated exactly:

- PR136 can produce represented structural impact;
- PR136/PR131 can identify a bounded directly linked test when compatible evidence
  exists;
- PR132 can identify an existing hotspot for that subject or an affected subject;
- PR137 can identify an existing verified dependency-cycle seam intersecting scope;
- PR138 can select an existing current-snapshot security finding for exact scope,
  but PR140 v1 intentionally does not consume it because that is not a security
  before/after conclusion.

Each downstream result retains its original limitations. None becomes a before/after
change fact simply because it is presented in a Git-aware review.

## Missing authoritative evidence

| Required conclusion | Missing prerequisite | Safe PR140 state |
| --- | --- | --- |
| Exact changed method/type/member | Persisted symbol source ranges or compatible semantic diff | `insufficient` at file association level |
| Deleted semantic subject | Compatible base snapshot bound to the reviewed base commit | `unavailable` |
| Semantic rename/move | Stable before/after identity mapping | `unavailable` |
| Proven source/API/binary break | Typed before/after API or bytecode comparison | `insufficient` or `unavailable` |
| Complete behavioral impact | Complete authoritative call and runtime-dispatch coverage | `partial` or `unavailable` |
| Complete targeted test set | Complete production-to-test reference/call/coverage mapping | `partial` or `unavailable` |
| Diff-introduced architecture issue | Paired architecture snapshots and intended policy | `unavailable` |
| Layer violation | Persisted intended layer-direction rules | `unavailable` |
| General migration plan | Authoritative target architecture, compatibility, and transformation evidence | `unsupported` |
| Diff-introduced/fixed vulnerability | Compatible before/after security analysis | `unavailable` |
| Safety from no local consumers | External consumer inventory | `unknown` |
| Historical semantic identity | Commit-bound semantic snapshots for both resolved refs | `unavailable`; Git commit identity alone does not bind semantic state |
| Historical snapshot alignment | Commit-bound semantic snapshot lineage | `unavailable` |

Names, packages, paths, extensions, directory layout, comments, LLM output, search
rank, co-change, and absent callers cannot replace any prerequisite in this table.

## Capability-by-capability gap analysis

| Roadmap capability | Already implemented | Missing for PR140 | First-slice decision |
| --- | --- | --- | --- |
| Git diff analysis | Safe deterministic PR92 collection and hunk metadata | Strict workspace path alignment, diff fingerprint, canonical subject adapter | Implement only the adapter and typed change facts |
| Impact analysis | PR136 canonical evidence-backed prediction | Mapping changed paths to exact current subjects | Reuse PR136 with unknown semantic change kind |
| Architectural concerns | PR128 observations and PR137 verified cycle seams | Change attribution and intended policies | Surface only intersecting verified existing cycle context; otherwise explicit insufficiency |
| Test recommendations | PR131/PR136 affected-test findings | Complete call/reference and coverage evidence | Retain direct evidence-backed tests; report incomplete coverage |
| Risk assessment | PR132 hotspot scores and PR136 risk context | No new scorer is needed | Reuse current compatible risk; do not recompute or infer |
| Migration advice | PR137 cycle-seam preconditions and verification | General migration planning and target architecture | Present verified seam guidance only; general capability remains unsupported |
| Security enrichment | PR138 current-state consolidated report | Before/after security delta | Intentionally defer; do not add a security section or duplicate scanner |
| Natural-language review | PR115 and PR139 provider paths | No provider is required for roadmap-safe facts | Defer; deterministic renderer is sufficient |

## Selected smallest independently useful slice

The implemented first slice introduces a feature-local deterministic
`ChangeReviewService` and
immutable response contracts. The service accepts a verified snapshot and a PR92
`GitDiff`; Git execution remains in the collector/CLI boundary.

It performs:

1. validate and normalize Git selection and workspace-relative paths;
2. compute deterministic observed-diff identity;
3. classify snapshot alignment as current, assumed current, stale, or unknown;
4. query the existing resolver for exact current path associations;
5. bound and order associated canonical subjects;
6. call PR136 for structural impact, tests, and risk;
7. call PR137 only for compatible verified cycle-seam context;
8. retain and validate exact evidence closure and feature projection, including
   reconstructed evidence, candidate provenance, confidence, section state, counts,
   lineage, graph digest, and request fingerprint;
9. serialize and render explicit capability states and limitations.

Every roadmap review section is present. A missing producer yields an explicit state
instead of generated prose. The roadmap item remains partial because this slice does
not implement semantic before/after comparison.

## Architectural ownership boundaries

- `GitDiffService` owns Git subprocesses and unified-diff parsing.
- `CanonicalSubjectResolver` owns exact identity and path association.
- `KnowledgeGraph` owns canonical relationships and adjacency.
- `ImpactPredictionService` owns propagation and affected partitions.
- `RiskAnalysisReport` owns risk scores and rankings.
- `RefactoringAdvisorService` owns supported advice.
- `SecurityIntelligenceService` continues to own security selection and priority;
  PR140 v1 does not consume or duplicate it.
- `EvidenceIndex` owns evidence identity and closure.
- `ConfidenceCalculator` owns confidence.
- `ChangeReviewService` owns only bounded orchestration and projection.
- The CLI owns argument translation and output selection, not review decisions.
- Renderers own presentation, not capability state or ranking.
- No provider owns any Atlas conclusion.

## Rejected alternatives

| Proposal | Reason rejected |
| --- | --- |
| Add a second Git collector/parser | Duplicates PR92 and risks different path/ref semantics |
| Parse patch source in PR140 | Duplicates analyzers and violates source-free snapshot/context guarantees |
| Create a change graph | Duplicates the PR129 canonical graph and PR136 traversal |
| Build a new file/symbol resolver | PR134 already has the exact path index |
| Use PR135 relevance as identity | Search rank cannot establish exact subject association |
| Re-score impact, risk, refactoring, or security | Specialized services remain authoritative |
| Infer semantic change kinds from Git metadata | File status and hunks do not prove API/member semantics |
| Interpret missing callers/tests/findings as safety | Coverage is partial or unavailable |
| Use PR115/PR139 LLM output as facts | Provider output cannot create evidence or confidence |
| Persist review results in snapshots | Request-specific state adds snapshot growth and stale invalidation |
| Persist provider review prose in conversations | Not required by the deterministic first slice and expands the trust boundary |
| Implement general migration, evolution, debt, or drift | Outside PR140 or missing authoritative evidence |
| Add concurrency or a shared cache | No measured need and no deterministic-equivalence proof |

## Regression and compatibility risks

- Changing existing Git DTO positional fields could break PR92 callers; any extension
  must be additive and defaulted or feature-local.
- A resolver path query must preserve existing resolution behavior and public
  constructor signatures.
- Path prefix mistakes can map a sub-workspace diff to the wrong subject.
- A stale snapshot must not produce semantic findings for a current diff.
- A many-symbol file can cause request amplification without hard subject bounds.
- Deleted and renamed paths can be silently lost if current-only identity is assumed.
- Raw PR128 architecture labels are not sufficient change evidence.
- Current PR132 findings can be misrepresented as newly introduced.
- PR136's unavailable call/test capability can be misread as an empty complete result.
- Incomplete upstream evidence projection can create dangling IDs.
- New public-facade exports or changed constructor signatures would alter the frozen
  v1 fixture.
- Reusing the `ReviewEngine` name or changing `atlas ai review` would blur PR115 and
  PR140 semantics.
- Extending PR139 optional-capability ordering can change otherwise unaffected chat
  JSON, prompts, and rendered results.
- Adding snapshot content changes all snapshot IDs and benchmark goldens.

## Persistence, performance, and benchmark implications

PR140 review results are ephemeral and reconstructible. Normal snapshot content is
unchanged, so expected ordinary snapshot growth is `0 bytes / 0%`. There is no new
cache, journal, index, or recovery state.

The expected cost is bounded path lookup plus the selected existing downstream
queries. Work is capped before invoking PR136/PR137. Measurements should
separate:

- diff collection;
- path association;
- subject and upstream candidate counts;
- traversal and selection;
- evidence projection;
- serialization and rendering;
- cold and repeated latency;
- peak working set and response bytes.

The implemented request defaults and hard maxima are respectively: files 256/1,000;
subjects per file 32/128; global subjects 64/128; impact depth 4/64; impact findings
100/1,000; architecture subjects 8/32; and global architecture advice 8/100. Subject
retention is allocated by deterministic round-robin across sorted files, and the
advice budget is global across all scopes. Git output is materialized before these
response bounds apply.

Because PR140 uses snapshots and shared AI/CLI surfaces but does not alter normal
analysis, the official repository benchmarks remain regression targets. No new large
benchmark repository is justified by the first slice.

## Explicit partial and deferred state

Implemented by the first slice:

- deterministic Git fact normalization;
- exact current-file canonical association;
- bounded composition of existing impact, tests, risk, and verified cycle guidance;
- shared evidence/confidence and explicit capability states;
- source-free deterministic output;
- unchanged snapshots, public API v1, PR115, and PR139 behavior.

Intentionally deferred:

- base/head semantic graph comparison;
- symbol-span and hunk-level attribution;
- deleted-symbol and semantic rename identity;
- API and binary compatibility diffing;
- architecture drift and intended layer policy;
- complete test selection;
- PR138 current-state or diff-aware security projection;
- general migration planning;
- LLM or chat presentation;
- persistence, caching, collaboration, automatic patches, and code execution.

These are not silently approximated. PR140 v1 remains an explicitly partial Change
Review implementation until compatible authoritative producers are available.
