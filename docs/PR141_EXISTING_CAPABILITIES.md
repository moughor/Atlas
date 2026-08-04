# PR141 Existing Capabilities

Status: completed capability audit and implementation disposition for the first
PR141 slice.

## Baseline and roadmap authority

The official roadmap identifies PR141 as **Repository Evolution**:

> Track semantic evolution across commits.

PR141 starts Milestone C after PR140 Change Review. The authoritative baseline is
PR140 commit `fde3ae84154b460cee5c39d6bc58448a3be0a911`.

The roadmap sentence describes a larger outcome than current persisted evidence can
support safely. Atlas archives semantic snapshots, and Git services can identify
commits, but existing snapshots do not prove that their semantic payload was captured
from a clean worktree at a particular commit. The first independently useful slice is
therefore an explicit pairwise semantic-snapshot comparison with a separately stated,
optional, partial Git commit association.

## Existing snapshot and history capabilities

| Capability | Existing owner | Reusable behavior | Boundary |
| --- | --- | --- | --- |
| Immutable semantic archive | PR111 `SemanticSnapshotStore` | Checksum verification, content-derived snapshot ID, immutable timestamped artifacts, atomic `latest.ass` | Archive filenames are capture times, not commit ordering |
| Snapshot identity | PR111 `AtlasSemanticSnapshot` | Schema, analyzer version, workspace fingerprint, history reference, semantic context, snapshot ID | `history_reference` is not a Git revision |
| Operational run history | PR94 `HistoryDatabase` | Run timestamp, success, requested projects, analysis order, project results | No Git commit, graph digest, or reverse snapshot link |
| Workspace persistence | PR70 `WorkspaceStateStore` | Current compatible project results with fingerprint invalidation | Overwritten operational state, not semantic history |
| Interrupted-run recovery | PR74 `WorkspaceRecoveryManager` | Durable checkpoints and stale-state invalidation | Recovery journal is transient operational state, not an evolution record |
| File-index comparison | PR20 `ProjectFileIndexer` | Content-addressed added, modified, and removed file paths | Source-file state, not semantic identity or source-free evolution |
| Finding baselines | PR77 `FindingBaselineService` | Stable comparison of generic finding fingerprints | Not a semantic graph or repository-evolution model |

`SemanticSnapshotStore.load()` is the authoritative input boundary. PR141 must not
introduce another archive, database, persistence layer, or cache. The base snapshot
is explicit. The head is explicit at the service boundary and may use the established
`latest.ass` pointer at the CLI boundary. Atlas never combines `latest.ass` with the
lexically previous archive as an implicit semantic timeline.

## Existing Git capabilities

| Capability | Existing owner | Available evidence | Limitation for PR141 |
| --- | --- | --- | --- |
| Base/head selection | PR92 `GitDiffService` | Resolved full commit identities and a deterministic source-free diff fingerprint | Does not bind either semantic snapshot to a commit |
| Current repository context | PR118 `GitContextService` | Branch, HEAD, changed paths, and bounded commits | Transient; optional snapshot labels are caller-supplied |
| Bounded history | PR118 `GitContextService.collect_history()` | HEAD, workspace prefix, shallow/truncated state, non-merge path changes | History is churn evidence, not semantic state |
| Persisted Git-head reference | PR132 risk evidence | Compatible `git-head:<object-id>` source references when bounded Git history ran | Does not record or prove a clean worktree |

One unique, valid Git head extracted from a compatible PR132 report can associate a
snapshot with the HEAD observed by that producer. It cannot prove that tracked,
untracked, ignored, generated, or concurrently changing inputs equal that commit.
Consequently this association is **partial**, never complete commit binding.

Missing PR132 data is `unavailable`. Multiple or malformed heads are `incompatible`.
PR92 remains the Git-diff authority but is not invoked by this first slice; a diff
does not bind either snapshot to a commit. Git ancestry, chronology, merge intent,
and developer intent are not inferred.

## Existing semantic identity and evidence

| Responsibility | Existing owner | PR141 reuse | Current limitation |
| --- | --- | --- | --- |
| Canonical repository graph | PR129 `KnowledgeGraph` | Stable node identities, relationship tuples, canonical ordering, graph digest | No graph-delta API; supported relation kinds are not evidence of population |
| Safe public identity | PR134 `CanonicalSubjectResolver` | Restore snapshot graphs and project internal IDs into source-free candidates | Cross-checkout repository identity is path-scoped |
| Evidence | PR130 `EvidenceRecord` and `EvidenceIndex` | Deterministic IDs, ordering, deduplication, and closure | PR141 must create only derived comparison evidence, not upstream facts |
| Confidence | PR130 `ConfidenceCalculator` | Structured support, coverage, agreement, ambiguity, and missing roles | Confidence cannot repair absent commit binding or producer comparability |
| Measurement | M2 `MeasurementSession` | Request-local loading, comparison, rendering, serialization, and memory observations | Measurement is not semantic evidence and authorizes no cache |

The PR129 graph is the canonical comparison model. A feature-local ordered difference
is not a second graph or traversal engine. Node identity is compared by canonical
graph ID. Relationships are compared by `(source, target, relation)`; changes in the
evidence tuple are reported separately from relationship addition or removal.

PR134 remains responsible for public subject projection. Internal repository and
workspace IDs may contain checkout-root material and must not be serialized directly.

## PR135 through PR140 disposition

| PR | Capability | PR141 disposition |
| --- | --- | --- |
| PR135 | Deterministic semantic search | Search rank is discovery, not identity or change evidence; do not use it as a comparator |
| PR136 | Impact prediction | Describes represented impact in one snapshot; does not prove a before/after change or runtime behavior |
| PR137 | Refactoring advisor | Current-state advice is not repository evolution; appearing or disappearing advice does not establish architectural change |
| PR138 | Security intelligence | Current-state consolidation remains authoritative; it is not diff-aware and cannot establish introduced or fixed vulnerabilities |
| PR139 | Interactive engineering chat | Provider output is untrusted and cannot create evolution evidence or confidence |
| PR140 | Change Review | Reviews one current snapshot against a Git diff and explicitly does not compare semantic before/after state |

PR141 does not extend `AskEngine`, `ChangeReviewService`, or any provider/prompt path.
It composes the established snapshot, graph, resolver, evidence, and confidence
contracts directly.

## Existing partial trend behavior

PR132 already owns risk-trend comparison through a compatible `previous_report`.
That comparison checks producer, configuration, subject, metric, unit, and window
identity. The normal snapshot pipeline does not currently supply a previous report,
so persisted trends usually remain unavailable.

PR141 must not duplicate that algorithm or compare bounded hotspot rankings as if
they were complete repository state. Historical risk integration is deferred until
the existing PR132 owner can consume a compatible prior report without changing its
meaning.

## Gap analysis

| Roadmap capability | Existing state | First-slice disposition |
| --- | --- | --- |
| Load two verified semantic states | Implemented | Reuse explicit PR111 snapshot paths |
| Restore canonical identity | Implemented | Reuse PR129 and PR134 independently for both snapshots |
| Compare canonical nodes | Missing | Add exact added, removed, and metadata-changed observations |
| Compare canonical relationships | Missing | Add exact added, removed, and evidence-changed observations |
| Commit selection | Implemented independently | Not consumed; PR92 diffs do not bind snapshots to commits |
| Snapshot-to-commit binding | Partial | Use only compatible PR132 Git-head association and label it partial |
| Stable identity across checkout roots | Missing | Require compatible persisted workspace identity; otherwise report incompatible |
| Complete producer/configuration comparability | Missing | Require analyzer-version equality, report exact snapshot observations only, and document that equality cannot establish every producer input |
| Historical timeline/index | Missing | Defer; no timestamp-based auto-selection and no new persistence |
| Rename or move identity | Missing | Report added/removed observations; never infer a rename |
| API/ABI compatibility | Missing | Unavailable; canonical presence does not prove a compatibility guarantee |
| Architecture evolution | Future PR143 | Do not infer architecture or drift |
| Security evolution | Missing before/after security contract | Do not claim introduced, fixed, or unchanged vulnerabilities |
| Runtime evolution | No runtime evidence | Unavailable |
| Developer intent | No authoritative producer | Unknown |

## Selected smallest independently useful slice

The approved slice compares an explicit checksum-verified snapshot pair. The CLI may
resolve the head through the established `latest.ass` pointer. It returns a bounded
deterministic projection of PR129 canonical node and relationship differences and
provides:

1. exact base/head snapshot and graph identity;
2. explicit compatibility and optional commit-association states;
3. added, removed, and structurally modified canonical nodes;
4. added, removed, and evidence-modified canonical relationships;
5. deterministic total, retained, unchanged, and omitted counts;
6. safe PR134 subject projections;
7. PR130 evidence closure and confidence with missing roles preserved;
8. stable ordering, limits, omitted counts, fingerprints, JSON, and rendering.

The response is ephemeral and rebuildable. It does not enter semantic snapshots,
history, workspace state, recovery, conversation memory, or another cache.

## Risks and compatibility requirements

- Valid schema-v1 snapshots without PR132 risk data must remain readable and yield
  unavailable commit association.
- A producer, configuration, or analyzer change can alter a graph without a
  repository change. Analyzer-version equality is necessary but not complete
  comparability, so the result remains an exact snapshot observation and does not
  assign developer causality.
- A removed subject can reflect unavailable analysis coverage. The report states an
  observed graph absence, not source deletion or dead code.
- Repository/workspace node identities can encode an absolute checkout root. All
  output uses PR134-safe public projections.
- Relationship evidence changes are not relationship changes.
- Bounds apply globally and disclose exact omitted counts; input reordering cannot
  alter selection.
- Loading two large snapshots can approximately double the live snapshot payload;
  pairwise linear work must be measured before considering timelines or caches.
- Existing public API signatures and the frozen v1 facade remain unchanged unless a
  later explicit public-contract decision requires expansion.

## Rejected alternatives

- A second graph, resolver, traversal engine, evidence model, or confidence model.
- A new evolution database, snapshot format, cache, or recovery journal.
- Automatic comparison of timestamp-neighboring archive files.
- Search-score, filename, package-name, or LLM-based identity matching.
- Comparing generated repository-report prose as semantic truth.
- Treating optional Git HEAD evidence as clean commit binding.
- Recomputing PR132 risk trends, PR136 impact, PR137 advice, or PR138 security.
- Inferring renames, architecture, ownership, API guarantees, migration, runtime
  behavior, or developer intent.
