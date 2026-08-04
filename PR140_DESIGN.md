# PR140 Design — Change Review

Status: implemented design record for the first safe PR140 slice.

## Roadmap authority

The official Atlas 2.x roadmap defines PR140 as **Change Review**:

> Analyze Git diffs and produce impact analysis, architectural concerns, test
> recommendations, risk assessment, and migration advice.

PR140 starts a new roadmap item. It does not continue PR139 Interactive Engineering
Chat, extend conversation memory, or add an autonomous coding agent. The roadmap is
broader than the before/after evidence currently available in Atlas, so PR140 v1 is a
partial implementation: every requested review area is represented, but a section is
`unavailable`, `insufficient`, `partial`, `incompatible`, or `stale` when its
authoritative prerequisite is absent.

PR140 does not implement PR141 Repository Evolution, PR142 Technical Debt, PR143
Architectural Drift, or any later roadmap item.

## Engineering objective

PR140 turns an existing source-free Git diff and an existing verified semantic
snapshot into one deterministic change-review response. It composes established Atlas
services rather than rediscovering their facts:

```text
GitDiffService                         AtlasSemanticSnapshot
      |                                         |
      |                                  PR129 KnowledgeGraph
      |                                  PR134 subject resolver
      +-------------- normalized paths --------+
                                                |
                              exact file-to-subject association
                                                |
                    +---------------------------+--------------------------+
                    |                                                      |
             PR136 impact/tests/risk                     PR137 verified cycle
                    |                                       seam context
                    +---------------------------+--------------------------+
                                                |
                              evidence closure and shared confidence
                                                |
                            deterministic ChangeReviewResponse
```

The review service is an orchestration boundary. It is not a second Git collector,
knowledge graph, resolver, impact predictor, risk scorer, test analyzer,
architecture detector, refactoring advisor, security scanner, confidence model, or
evidence model.

## Existing owners reused

| Responsibility | Authoritative owner | PR140 boundary |
| --- | --- | --- |
| Working-tree, staged, and base/head diff collection | PR92 `GitDiffService` | Collect outside domain review logic; retain normalized file and hunk facts only |
| Git history and churn | PR118 `GitContextService` | Existing PR132 input; not a substitute for PR92 diff facts |
| Repository identity and relationships | PR129 `KnowledgeGraph` | Query the resolver-owned canonical graph; do not copy it |
| Evidence and confidence | PR130 `EvidenceRecord`, `EvidenceIndex`, `EvidenceRole`, `ConfidenceCalculator` | Trace and score only structured retained evidence |
| Reachability and test linkage | PR131 report | Reused through PR136; missing calls never establish safety |
| Risk and hotspots | PR132 report | Context for already-associated subjects; never create an impact path |
| Canonical identity | PR134 `CanonicalSubjectResolver` | Own exact path and subject association |
| Semantic search | PR135 service | Optional discovery only; never authoritative path resolution |
| Impact prediction | PR136 `ImpactPredictionService` | Bounded impact, affected-test, breaking-uncertainty, and risk context |
| Refactoring advice | PR137 `RefactoringAdvisorService` | Only fully revalidated dependency-cycle seam advice is usable |
| Security intelligence | PR138 `SecurityIntelligenceService` | Intentionally deferred from v1: current-state findings cannot establish a diff-introduced or fixed vulnerability |
| Engineering questions | PR139 `AskEngine` | Unchanged and not required by deterministic change review |
| Performance observations | M2 `MeasurementSession` | Separate Git, mapping, integration, rendering, and serialization phases |

The existing PR115 `ReviewEngine` is a provider-backed semantic architecture review.
It is not Git-aware and provider prose is not Atlas authority. PR140 therefore does
not repurpose it. The new deterministic component is named `ChangeReviewService`, not
another generic `ReviewEngine`.

## Selected safe slice

PR140 v1 accepts:

- one checksum-verified `AtlasSemanticSnapshot`;
- one normalized `GitDiff` collected by the existing PR92 service;
- bounded review options such as maximum changed files, subjects, impact depth, and
  returned results;
- optional current-workspace identity needed to classify snapshot alignment.

The service produces:

- deterministic changed-file facts;
- exact current-snapshot subject associations where available;
- bounded PR136 structural impact findings;
- evidence-backed affected-test recommendations when PR131/PR136 can establish them;
- compatible PR132 risk context for directly changed or affected subjects;
- verified PR137 dependency-cycle seam context when a changed scope intersects it;
- explicit capability, coverage, truncation, lineage, and limitation records;
- a closed evidence index and shared deterministic confidence;
- deterministic JSON and human rendering.

This is independently useful because it connects the previously missing
Git-to-canonical-subject boundary while retaining all existing analysis authority.
It does not pretend that the current snapshot is a semantic before/after comparison.

## Git input and change facts

`GitDiffService.collect()` remains the only Git diff collector. Domain review logic
accepts its immutable result and does not execute Git itself.

PR140 normalizes and validates every path as a bounded, workspace-relative POSIX path.
Absolute paths, traversal, control characters, malformed records, and paths outside
the selected workspace are rejected or reported as incompatible. Repository roots
inside a larger Git checkout require an explicit Git-top-level-to-workspace prefix
translation; a top-level path must never be compared accidentally with a
workspace-relative semantic path.

The following file states are facts available from PR92 metadata:

- added;
- modified;
- deleted;
- renamed;
- binary;
- hunk and added/removed line counts.

The unified-diff parser reads patch text but retains only paths, flags, ranges, and
line numbers. PR140 never includes changed source lines in evidence, context,
serialization, rendering, prompts, or persistence.

A deterministic diff fingerprint is calculated from normalized file and hunk facts,
selection mode, declared refs, resolved full commit identities where applicable, and
the workspace prefix. PR140 extends the existing PR92 DTO additively with resolved
base/head commit provenance. Repository HEAD is retained as provenance but is
excluded from the ordinary working-tree fingerprint because it is not the selected
comparison input.

## Snapshot alignment and stale state

A valid snapshot checksum proves internal snapshot integrity; it does not prove that
the snapshot represents the current working tree or a requested historical Git head.
When a current workspace fingerprint is supplied, it is compared with
`snapshot.workspace_fingerprint` using the existing workspace/snapshot fingerprint
contract:

- equal fingerprints: current-snapshot semantic enrichment may proceed;
- unequal fingerprints: semantic sections are `stale` and no current semantic claim
  is emitted;
- unavailable fingerprint: alignment is explicit `unknown` and semantic enrichment
  is disabled unless the caller explicitly requests `assumed_current`.

The provider-free CLI performs no workspace rescan, so its default is `unknown`.
`--assume-current-snapshot` is an explicit, reported partial state rather than a
verification shortcut.

Historical base/head review cannot be described as a semantic delta unless a future
compatible producer binds both semantic snapshots to the resolved commits. Recovery
of an old snapshot does not make its grounding current.

## Exact path-to-subject association

The PR134 resolver already builds a deterministic exact path index from persisted
symbol sources, canonical node metadata, and declared-dependency source references.
PR140 extends that owner with the smallest concrete exact-path query required by a
second consumer. Every returned candidate carries resolver-owned
`PathCandidateEvidence` identifying the accepted persisted source references.
Change review must not access the resolver's private indexes, build a second path
resolver, or use PR135 search ranking as identity.

One source file may contain many canonical symbols. Without source spans in the
snapshot, every exact path match is a **file-associated candidate**, not proof that a
particular hunk changed that symbol. Associations are sorted by canonical identity
and bounded with exact total, returned, and omitted counts. A missing exact path may
return the deepest containing project as an explicitly marked structural fallback;
that fallback is not an impact root or declaration identity.

Per-file semantic confidence is computed by the shared `ConfidenceCalculator` from
required `git_change`, `path_mapping`, and `exact_path_identity` roles. Candidate
coverage and multiple-candidate ambiguity are applied deterministically. The
resolver provenance must exactly cover returned candidates, and project fallback
cannot satisfy the exact-identity role.

Current-snapshot association is normally possible for added and modified paths. A
deleted path may have no current subject. A rename does not prove that old and new
subjects are identical. Binary and submodule changes have no semantic member
attribution. These conditions produce explicit limitations rather than guessed
identity.

## Impact analysis

For exact associated subjects, PR140 invokes the existing snapshot-backed PR136
service with canonical `SubjectQuery` values. Git paths and hunks do not establish a
semantic change kind, so the default request uses `ImpactChangeKind.UNKNOWN`.
Multiple subjects are bounded deterministically through the existing additional-
subject contract or through a bounded sequence of independent requests.

PR140 preserves PR136 relationship authority:

- declared dependencies, resolved imports, inheritance, overrides, and ownership are
  used only under PR136's existing propagation policy;
- canonical call evidence remains unavailable for most normal snapshots;
- composition remains unsupported;
- structural ownership cannot become sibling behavioral impact;
- zero in-repository findings do not prove external compatibility or safety;
- no Git hunk becomes a proven API change, changed member, or breaking change.

PR140 does not alter `ImpactPredictionService` scoring, traversal, confidence,
evidence, or public constructor signatures.

## Test recommendations

Evidence-backed test recommendations come from PR136 affected-test findings, which in
turn accept only compatible PR131 call/reference paths and coverage. A recommendation
identifies the existing canonical test subject and the retained impact evidence.

When call coverage, source classification, or test-to-subject linkage is absent,
PR140 reports that targeted test selection is unavailable or partial. It must not:

- infer a test from a matching name;
- treat the same package or project as a direct test relationship;
- claim that no tests are required because no test was returned;
- invent a build command or test target.

A broad project test scope may be presented only as structural context and must be
distinguished from a directly linked test recommendation.

## Risk assessment

PR132 remains the risk scorer. A compatible report requires its supported producer
and schema, the active PR129 graph digest, canonical evidence records, and matching
evidence lineage. PR140 may retain:

- a hotspot already attached to an exact changed subject;
- PR136 risk context attached to an established impact finding.

Risk can prioritize review of an already established association or impact. It cannot
create subject identity, an impact edge, a security finding, an architectural
violation, or a migration recommendation. Missing metrics remain missing; they are
not zero.

## Architectural concerns and migration advice

PR128 provides repository-level architecture observations, but it does not provide a
before/after architecture comparison or persisted intended layer policies. Its raw
architecture labels must not be converted directly into a change-specific concern.

PR137 is the safe adapter for the first slice. It accepts only PR128 dependency cycles
that it can completely revalidate against authoritative PR129 relationships. When a
changed canonical scope intersects a verified cycle seam, PR140 may present the
existing seam review, preconditions, limitations, and verification steps as relevant
architectural and migration context.

The wording must say that the concern existed in the analyzed snapshot. PR140 cannot
claim the diff introduced the cycle or that a proposed dependency change is safe.
When no compatible verified seam exists:

- general architectural-concern detection is `insufficient` or `unavailable`;
- layer violation review is `unavailable` without intended-direction evidence;
- general migration planning is `unsupported`;
- no replacement is generated from names, directories, LLM output, or search rank.

PR141 evolution and PR143 architectural drift remain future roadmap work.

## Deferred security context

PR138 Security Intelligence remains authoritative for current-snapshot security
findings, but PR140 v1 does not project it. A current finding cannot establish that a
diff introduced, removed, or fixed a vulnerability, and the roadmap does not justify
a second scanner or a placeholder security section. Compatible before/after
security review remains intentionally deferred.

## Evidence and confidence

Every production review conclusion has a closed chain of structured evidence. PR140
reuses the shared model:

- normalized Git facts use repository-metadata evidence;
- exact path association uses persisted semantic identity evidence;
- impact, risk, test, and refactoring facts retain compatible upstream
  evidence records;
- aggregation creates bounded references but never replaces upstream authority;
- dangling, conflicting, non-canonical, stale, or unused evidence is rejected.

Confidence is calculated only by `ConfidenceCalculator`. File association requires
Git-change, path-mapping, and exact-path-identity roles; downstream conclusions keep
the domain evidence required by their authoritative producer. Missing required roles
produce the shared `insufficient` tier.
Optional risk context cannot raise a missing impact or identity role into a supported
conclusion.

No LLM may create or modify evidence, confidence, severity, priority, identity,
citations, lineage, or capability state.

## Response and serialization contract

PR140 response DTOs are immutable, bounded, source-free, and versioned. The response
records:

- normalized request and Git selection;
- producer and schema versions;
- diff fingerprint, snapshot ID, workspace fingerprint, and graph digest;
- snapshot-alignment state;
- changed-file facts and canonical subject associations;
- impact, architecture, test, risk, and migration sections;
- capability and coverage states;
- input, retained, and omitted counts;
- truncation, unavailable analyses, and limitations;
- exact evidence closure and deterministic confidence.

For valid output:

```python
response.to_dict() == ChangeReviewResponse.from_dict(
    response.to_dict()
).to_dict()
```

Canonical JSON uses sorted fields and stable arrays. Human rendering follows the same
section and item order. Ordering never depends on dictionary insertion, set
iteration, filesystem traversal, graph accidents, analyzer registration, timing,
provider behavior, process identity, or temporary paths.

Deserialization performs exact projection validation, not merely ID validation. It
reconstructs PR140 Git, mapping, and association evidence from changed-file facts;
recalculates per-file confidence; verifies candidate provenance, evidence closure,
lineage, graph digest, global counts, and the input fingerprint; and recomputes every
section's state, item IDs, and evidence IDs from nested results. Self-consistent but
re-projected or independently edited payloads are rejected.

## Source-free and trust boundary

PR140 v1 invokes no provider and builds no prompt. Paths are validated relative
repository metadata; source lines, patch bodies, secrets, credentials, absolute
private paths, commit-message prose, blame prose, and conversation text are excluded.

Repository-controlled names and paths remain untrusted display data. Renderers escape
or encode them according to their output format and never interpret them as
instructions. If a future PR139 integration consumes a change-review response, it
must use the existing token selection, sanitization, evidence closure, citation, and
grounding boundaries. That integration is not part of the first slice.

## Persistence and compatibility

Change reviews are request-specific and reconstructible. PR140 therefore introduces
no semantic-snapshot key, persistent review index, conversation turn, global cache,
or recovery journal. It loads a snapshot but never mutates or republishes it.

Consequences:

- old valid snapshots remain readable;
- ordinary semantic snapshot bytes and IDs remain unchanged;
- expected ordinary snapshot growth is `0 bytes / 0%`;
- no request-specific result can become stale persisted Atlas authority;
- PR139 conversation persistence and recovery remain unchanged.

The stable public API remains version `1.0` with its existing frozen signatures.
PR140 package-level DTOs and service do not require a public-facade change. Existing
Git and subject-resolution contracts receive only backward-compatible additive
fields or methods; impact, refactoring, security, semantic-search, AskEngine, and
legacy CLI contracts remain unchanged.

`atlas ai review` keeps its PR115 meaning. A PR140 CLI command is distinct and contains
only argument translation, snapshot loading, Git collection, service invocation, and
rendering. Domain decisions do not live in the CLI.

## Bounds and performance

The first slice is request-local and bounded by:

| Request field | Default | Maximum | Scope |
| --- | ---: | ---: | --- |
| `maximum_files` | 256 | 1,000 | Files retained for review |
| `maximum_subjects_per_file` | 32 | 128 | Candidates retained for one path |
| `maximum_subjects` | 64 | 128 | Global candidates across all paths |
| `impact_depth` | 4 | 64 | PR136 traversal depth |
| `impact_limit` | 100 | 1,000 | PR136 findings |
| `architecture_subject_limit` | 8 | 32 | PR137 scopes evaluated |
| `architecture_advice_limit` | 8 | 100 | Global PR137 advice across all scopes |

The global subject budget is allocated by deterministic round-robin over sorted
files. The architecture-advice budget is global rather than reset for each subject.
All truncation reports exact total, retained, and omitted counts. Git subprocess
output is materialized before these response bounds apply; v1 does not claim a
streaming Git parser.

Mapping uses the resolver's existing path index. Impact uses the canonical graph's
existing adjacency. No all-pairs closure, whole-repository reanalysis, persistent
cache, graph copy, new concurrency, or provider call is introduced.

Measurement separates Git collection, path association, upstream service calls,
evidence projection, sorting, rendering, and serialization. Cold and repeated
requests, peak memory, response bytes, and ordinary snapshot byte identity are
reported without claiming causality from uncontrolled cohorts.

## Compatibility and regression risks

- A stale snapshot can turn a deterministic response into a confidently wrong review
  unless semantic sections are disabled explicitly.
- Mapping every symbol in a large file can amplify work; candidates and upstream
  calls require deterministic bounds and omitted counts.
- Git top-level and workspace-relative paths can differ.
- A deleted or renamed file may not resolve in the current snapshot.
- Symbolic refs can move after collection.
- A current risk finding can be misworded as diff-introduced.
- Architecture labels can be mistaken for intended policy or change attribution.
- Missing call/test coverage can be mistaken for absence of impact.
- Copying upstream evidence incompletely can break evidence closure or lineage.
- Changing `atlas ai review`, PR139 capability ordering, public constructors, or
  snapshot content would create unrelated compatibility regressions.
- Running upstream services once per unbounded symbol can be unacceptable on large
  repositories.

Tests must cover these concrete failure modes, reversed input order, strict
serialization, output limits, old and partial snapshots, public API preservation,
and byte-identical unaffected PR139 behavior.

## Rejected alternatives

| Alternative | Decision and reason |
| --- | --- |
| Parse changed source or regex diff text to infer members | Rejected: duplicates semantic analysis and violates source-free operation |
| Build a Git-specific knowledge graph or reverse adjacency | Rejected: PR129 is canonical and PR136 already owns impact traversal |
| Use semantic-search ranking to map a path | Rejected: relevance is not identity evidence |
| Reuse PR115 provider output as review authority | Rejected: provider prose cannot create Atlas facts |
| Add another impact, risk, architecture, test, migration, or security engine | Rejected: existing specialized services remain authoritative |
| Infer change kind from file names, paths, extensions, or hunk shape | Rejected: no semantic before/after evidence |
| Treat current findings as introduced by the diff | Rejected: no compatible paired snapshot evidence |
| Treat no callers, tests, or findings as safety | Rejected: missing coverage is unknown, not negative evidence |
| Persist review results in semantic snapshots or conversations | Rejected: request-specific state would add growth, invalidation, and trust risks |
| Extend AskEngine or `atlas ai review` in v1 | Deferred: not required for a deterministic independently useful slice |
| Implement architecture drift, repository evolution, or technical debt | Rejected as PR141–PR143 scope |
| Introduce concurrency or a shared cache | Rejected: no measured need or deterministic-equivalence requirement |

## Explicit partial and deferred state

PR140 v1 completes the Git-to-current-semantic-subject integration and deterministic
review composition. The broader roadmap item remains partial.

Intentionally deferred until compatible evidence exists:

- commit-bound base/head semantic snapshots;
- symbol-span and hunk-level attribution;
- deleted-symbol identity and semantic rename tracking;
- proven API and binary compatibility deltas;
- diff-introduced/fixed security findings;
- intended architecture policies and architectural drift;
- complete call and test coverage;
- general migration planning;
- provider-assisted presentation through PR139;
- durable review caches or collaborative review state;
- automatic patches, code changes, or command execution.

Atlas reports these boundaries directly. It never fills a missing section with an
LLM inference, a name heuristic, or unsupported certainty.
