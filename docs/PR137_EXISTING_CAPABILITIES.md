# PR137 Existing Capabilities

Status: pre-implementation audit for the first roadmap-compliant PR137 slice.

## Baseline and authority

The official roadmap identifies PR137 as **Refactoring Advisor**. The roadmap does
not contain M2.0 or M2.1 entries; those are completed stabilization records in Git
history and `docs/stability`. The unambiguous next numbered roadmap item after the
local PR136 implementation is therefore PR137.

The implementation baseline is local commit
`cef8d52b2a39ec019e3a6cd34e34450d36c85a55`. At audit time the worktree was clean,
but `origin/main` still referenced PR135 commit
`cddfefc09ee7ae2ceeb908f167568797c02041d0`. PR137 is built on the local PR136
commit; this discrepancy must be resolved before a later push.

The pre-change full suite completed with `4071 passed, 3 skipped in 36.86s`. The
three skips are existing Windows symlink-capability checks. Pytest also reported one
environmental warning because the existing `.pytest_cache` directory was not
writable; subsequent runs disable that optional cache provider.

## Reusable capabilities

| Responsibility | Existing owner | PR137 use |
| --- | --- | --- |
| Canonical repository relationships | PR129 `KnowledgeGraph` | Query existing nodes and edges; never construct a competing graph |
| Design intent | PR130 pattern findings | Not consumed by the first slice; future advice must protect intentional structures and patterns cannot create advice |
| Reachability and deletion uncertainty | PR131 reachability report | Not consumed by the first slice; absence of callers cannot become a deletion or cleanup claim |
| Risk and hotspot context | PR132 risk report | Not consumed by the first slice; future use may prioritize only an already proven candidate |
| Repository presentation | PR133 report | Optional downstream presentation; not refactoring evidence |
| Canonical identity and ambiguity | PR134 `CanonicalSubjectResolver` | Resolve request scope and project subjects without a second resolver |
| Semantic discovery | PR135 search | Not required and never authority for a refactoring relationship |
| Blast radius and breaking uncertainty | PR136 impact prediction | Optional bounded effort/impact context; never candidate creation |
| Evidence and confidence | PR130 `EvidenceRecord`, `EvidenceIndex`, and `ConfidenceCalculator` | Trace every retained conclusion and calculate confidence deterministically |
| Architecture cycles | PR128 architecture report | Candidate source only after every reported cycle hop is revalidated against authoritative PR129 edges |
| Measurement | M2 `MeasurementSession` | Opt-in request-local phase, time, and memory observations |

PR133 already emits investigation recommendations, but those are report prose rather
than a typed refactoring engine. The LLM-backed review and patch engines, LSP code
actions, rule fixes, duplicate-symbol errors, and specialized cycle detectors keep
their existing responsibilities and are not reused as refactoring facts.

## Evidence gaps

| PR137 design family | Current production evidence | Safe status |
| --- | --- | --- |
| Duplicate consolidation | No authoritative structural clone/duplicate producer | `unavailable` |
| Extract method/class | No complete complexity, cohesion, symbol-size, ownership, and dependency evidence | `insufficient` |
| Package restructuring | No authoritative dependency-cluster and intended-boundary producer | `insufficient` |
| Dependency cleanup | No complete build-and-usage producer; missing uses are not proof of an unused dependency | `insufficient` |
| Cycle breaking | PR128 cycles can be revalidated against authoritative canonical dependency/import edges | `available` or `partial` per snapshot |
| Layer violations | Observed directions exist, but no persisted intended layer-direction rules exist | `unavailable` |

PR128 package, port, adapter, and infrastructure labels may contain name-derived
candidates. They cannot establish a package move or layer violation. PR132 risk,
graph degree, PR135 relevance, Git co-change, and LLM text cannot substitute for a
missing structural producer.

## Smallest independently useful slice

PR137 v1 provides immutable, source-free advice for verified dependency-cycle
seams. It consumes, but does not rediscover, PR128 cycles. Every cycle member must
resolve uniquely to a canonical project and every cycle step must have authoritative
canonical evidence. A stale, fabricated, ambiguous, incomplete, or unexecuted cycle
produces no advice and an explicit limitation.

The advice is deliberately neutral: review and decouple a represented seam. It does
not claim that deleting a dependency is behaviorally safe, generate a patch, or move
code. PR136 may describe the bounded represented blast radius and effort uncertainty,
but it cannot create the advice.

The remaining design families stay visible as capabilities with explicit unavailable
or insufficient states. This is a first safe slice of the larger PR137 roadmap item,
not a claim that every refactoring family is complete.

## Compatibility and regression risks

- PR136's canonical edge-authority boundary must remain byte-for-byte compatible
  when shared with a second consumer.
- Older snapshots may omit PR128 through PR136 sections; one missing capability must
  not invalidate the whole response.
- Project names can be ambiguous across module scopes; no first-match selection is
  permitted.
- A reported cycle without a canonical authoritative hop is stale or incomplete,
  not evidence for a recommendation.
- Zero local impact findings do not imply low effort or absence of external users.
- Candidate ranking, evidence closure, estimates, rendering, and serialization must
  remain independent of input order, hash iteration, timing, and LLM output.
- Advice is reconstructed on demand. No semantic-snapshot payload, persistent cache,
  normal analysis pass, concurrency, or benchmark golden is changed.
