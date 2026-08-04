# PR140 Change Review

## Scope and status

PR140 implements the first safe slice of the official **Change Review** roadmap
item. It reviews source-free Git change metadata against one verified Atlas
semantic snapshot and returns deterministic impact, test, risk, architecture, and
migration capability sections.

The implementation is deliberately conservative. It does not compare semantic
state before and after a commit, parse changed source, invoke an LLM, or infer facts
from names. Missing, stale, incompatible, or incomplete evidence remains explicit.

PR140 is an additive request-time feature. It does not implement PR141 Repository
Evolution, PR142 Technical Debt, PR143 Architectural Drift, or any later roadmap
item.

## Architecture

```text
GitDiffService                         verified AtlasSemanticSnapshot
      |                                           |
      |                                  PR129 KnowledgeGraph
      |                                  PR134 subject resolver
      +----------- safe relative paths ----------+
                                                  |
                                 exact file association
                                                  |
                     +----------------------------+-------------------+
                     |                                                |
          PR136 impact, tests, risk                     PR137 verified cycle seams
                     |                                                |
                     +----------------------------+-------------------+
                                                  |
                         PR130 evidence, confidence, and lineage
                                                  |
                               ChangeReviewResponse + renderer
```

`ChangeReviewService` owns only orchestration and projection. Existing specialized
services remain authoritative:

- `GitDiffService` owns Git execution and unified-diff parsing;
- `CanonicalSubjectResolver` owns canonical identity and path association;
- `KnowledgeGraph` owns repository relationships;
- `ImpactPredictionService` owns structural impact, linked tests, and compatible
  risk context;
- `RefactoringAdvisorService` owns fully revalidated dependency-cycle advice;
- `EvidenceIndex` and `ConfidenceCalculator` own evidence and confidence semantics.

No second graph, resolver, impact engine, risk scorer, test selector, architecture
detector, confidence model, evidence model, cache, or semantic pass is introduced.

## CLI

The provider-free command is separate from the legacy PR115 command
`atlas ai review`:

```text
atlas change-review .
atlas change-review . --staged
atlas change-review . --base main
atlas change-review . --base main --head HEAD
atlas change-review . --snapshot path/to/snapshot.ass --json
atlas change-review . --assume-current-snapshot --json
atlas change-review . --no-architecture
atlas change-review . --profile
```

Git selection rules are validated by `GitDiffService`. `--head` requires `--base`,
and a staged comparison cannot also specify `--head`. Declared refs are retained for
display while resolved full commit IDs bind explicit and staged comparisons.

The CLI loads an existing snapshot through the established snapshot loader. It does
not analyze or rescan the workspace. Therefore, without an independently supplied
workspace fingerprint, the default alignment is `unknown` and semantic enrichment
is disabled. `--assume-current-snapshot` is an explicit opt-in: it permits
enrichment but reports `assumed_current` and `partial`, never verified currency.

`--profile` writes the default M2 sidecar to
`.atlas/measurements/latest-change-review.json`; `--profile-output` selects another
path. Profiling changes neither stdout nor the semantic response.

The service API can instead receive `current_workspace_fingerprint`. An exact match
produces `current`; a mismatch produces `stale` and disables semantic conclusions.

## Git facts

PR140 retains only deterministic Git metadata:

- added, modified, deleted, and renamed file state;
- binary state;
- hunk ranges;
- added and removed line numbers and counts;
- working-tree, staged, base-to-working-tree, or base-to-head selection;
- declared refs, compatible resolved commit IDs, repository HEAD provenance, and
  the Git-top-level-to-workspace prefix;
- a canonical SHA-256 diff fingerprint.

Paths are normalized to safe workspace-relative POSIX paths. Absolute paths,
traversal, malformed refs, control characters, replacement characters, duplicate
file identities, paths outside a selected sub-workspace, and inconsistent hunk
ranges are rejected. Untracked files are not collected and this limitation is
always disclosed.

Source lines and patch bodies are discarded by the diff parser. They do not enter
evidence, responses, renderers, snapshots, prompts, or persistence.

## Snapshot alignment

Snapshot checksum validity proves envelope integrity, not currency. PR140 records
one of four alignment states:

| State | Meaning | Semantic behavior |
| --- | --- | --- |
| `current` | Supplied workspace fingerprint equals the snapshot fingerprint | Exact association and compatible downstream services may run |
| `assumed_current` | Caller explicitly accepts unverified currency | Enrichment may run, but alignment remains partial with a limitation |
| `stale` | Supplied workspace fingerprint differs | Association and semantic advisors are disabled |
| `unknown` | No fingerprint and no explicit assumption | Association and semantic advisors are disabled |

A historical Git base/head selection is not a semantic before/after comparison.
Commit-bound paired snapshots are intentionally deferred.

## File association, provenance, and confidence

PR140 extends the shared PR134 resolver with a bounded exact-path query. The resolver
owns the index and provenance; Change Review does not inspect private indexes or use
semantic-search relevance as identity.

Accepted path provenance is structured and source-free:

- `GlobalSymbol` source metadata;
- canonical graph node `path` metadata;
- declared-dependency source references already retained by canonical graph edges.

Each returned candidate carries `PathCandidateEvidence`, and the candidate-evidence
set must exactly cover the returned canonical subjects. If no exact subject path is
available, the resolver may return the deepest containing project as an explicitly
marked structural fallback. A project fallback can scope PR137 cycle-seam review,
but it is never an impact root or proof that a declaration changed.

One source file can contain several declarations. Because snapshots do not retain
declaration spans, an exact file association does not prove which declaration a hunk
changed. Deleted files require a compatible base snapshot, binary files have no
declaration attribution, and Git rename detection does not prove semantic identity
continuity.

Every changed file retains:

- one reconstructed Git evidence record;
- one reconstructed path-mapping record;
- one association record per retained candidate, including resolver-owned source
  references;
- exact total, returned, and omitted subject counts;
- deterministic `semantic_confidence`.

The shared `ConfidenceCalculator` uses three required roles: `git_change`,
`path_mapping`, and `exact_path_identity`. Coverage is the retained-candidate count
divided by the exact total. Multiple exact candidates receive the shared ambiguity
penalty. A project fallback supplies no exact-identity role, so it cannot acquire
supported semantic confidence merely from containment.

## Review sections

Every response contains exactly these eight sections:

| Section | Producer and meaning |
| --- | --- |
| `git_diff` | Observed bounded Git facts |
| `snapshot_alignment` | Current, assumed, stale, or unknown alignment |
| `subject_mapping` | Exact current-file candidates or explicit fallback/absence |
| `impact` | Bounded PR136 structural findings from exact subjects |
| `tests` | PR131/PR136 evidence-linked tests only |
| `risk` | Existing compatible PR132 context attached through PR136 |
| `architecture` | Existing fully revalidated PR137 dependency-cycle seams intersecting scope |
| `migration` | Only PR137 preconditions and verification for those seams |

Section states are `available`, `partial`, `insufficient`, `unavailable`,
`incompatible`, `unsupported`, `stale`, or `not_requested`. Every non-available
section includes a limitation.

Git metadata cannot determine a semantic change kind, so PR136 receives `unknown`
unless the caller explicitly selects a kind. Missing canonical calls or test
coverage never means that there is no impact or that no tests are required. PR132
risk values remain current-snapshot context; the diff is not claimed to have
introduced them. PR137 advice is limited to dependency-cycle seams already proven
by its own compatibility and evidence checks. No general migration plan is
generated.

PR138 Security Intelligence is intentionally not projected in PR140 v1. A secure
diff cannot be inferred from current-state findings, and a before/after security
producer does not yet exist. Adding compatible security change context is deferred;
PR140 does not add a placeholder security section or a second scanner.

## Deterministic global bounds

All downstream work is bounded before invocation:

| Request field | Default | Maximum | Scope |
| --- | ---: | ---: | --- |
| `maximum_files` | 256 | 1,000 | Files retained for review |
| `maximum_subjects_per_file` | 32 | 128 | Resolver candidates retained for one file |
| `maximum_subjects` | 64 | 128 | Global subjects retained across all files |
| `impact_depth` | 4 | 64 | PR136 traversal depth |
| `impact_limit` | 100 | 1,000 | Global PR136 findings |
| `architecture_subject_limit` | 8 | 32 | Changed scopes evaluated by PR137 |
| `architecture_advice_limit` | 8 | 100 | Global retained advice across all evaluated scopes |

The global subject limit is allocated by deterministic round-robin over sorted
files, preventing the first many-declaration file from consuming the whole budget.
The architecture advice limit is a single request-wide budget, not a per-subject
limit. Total, returned, and omitted counts remain visible. Reversing equivalent
input order produces identical output.

These response bounds do not cap the size of output produced by the external Git
process before parsing. That collection boundary remains a documented performance
limitation rather than an invented streaming implementation.

## Exact projection and serialization validation

The response is not accepted merely because its evidence IDs are internally
self-consistent. `ChangeReviewResponse` performs exact projection validation:

1. reconstruct each expected PR140 Git, mapping, and association evidence record
   from the serialized facts;
2. require resolver provenance to cover every retained candidate exactly;
3. reject dangling, unused, foreign-owned, duplicate, malformed, or wrong-lineage
   evidence;
4. recalculate each file's confidence from the expected roles, coverage, and
   ambiguity;
5. recompute every section's state, item IDs, and evidence IDs from nested impact
   and refactoring responses;
6. verify graph digest, snapshot lineage, alignment restrictions, global counts, and
   the canonical input fingerprint;
7. reject unknown schema fields, absolute paths, unsafe content, and source-shaped
   payloads.

For valid output:

```python
response.to_dict() == ChangeReviewResponse.from_dict(
    response.to_dict()
).to_dict()
```

Canonical JSON uses sorted keys and compact separators. Human rendering follows the
same stable section and item order and escapes control bytes. Timing, process IDs,
temporary paths, provider behavior, dictionary insertion order, set iteration, and
filesystem enumeration do not participate in semantic output identity.

## Persistence and compatibility

Change reviews are ephemeral and reconstructible. PR140 does not add a snapshot
field, mutate or republish snapshots, persist a review index, write conversation
turns, add a recovery record, or introduce a cache. Ordinary snapshot identity and
content therefore remain outside the request result.

Compatibility is additive:

- old valid snapshots remain readable and degrade explicitly when PR129 data is
  absent;
- PR129 graph, PR130 evidence/confidence, PR134 resolution, PR136 impact, PR137
  advice, and PR139 chat contracts remain authoritative;
- the frozen public facade and its constructor signatures are unchanged;
- `atlas ai review` retains its provider-backed PR115 meaning;
- `atlas change-review` is a distinct provider-free command;
- no PR140 result is automatically inserted into PR139 context or memory.

## Known limitations and deferred work

- no commit-bound base/head semantic snapshots;
- no symbol-span or hunk-level declaration attribution;
- no deleted-symbol recovery or semantic rename tracking;
- no API, ABI, or binary compatibility delta;
- incomplete call, runtime dispatch, external-consumer, and test coverage;
- no intended layer policy or diff-attributed architectural drift;
- no general migration planning;
- no PR138 before/after security review;
- no provider narrative, chat integration, durable result cache, collaboration,
  patch generation, command execution, or repository modification.

These limitations are observable response states, not prompts for heuristic or LLM
substitution.
