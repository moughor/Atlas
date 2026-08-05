# Atlas Refactoring Plan

Status: proposal only. No production code, module moves, package creation,
renames, commits, or pushes are authorized by this document.

## Refactoring objective

Create an enforceable platform boundary with the smallest possible change set.
The plan corrects demonstrated dependency inversions and prevents new
cross-domain coupling. It does not reorganize 532 modules into a new directory
tree for cosmetic consistency.

## Future package hierarchy

The target is a gradual ownership model, not a one-PR physical relocation:

```text
moughorai/
  platform/                  # only proven domain-neutral contracts
    safety/                   # first extracted utility
    measurement/              # stable facade when introduced
  domains/
    repository/               # conceptual ownership; existing packages migrate only as justified
    benchmark/                # absent until Benchmark Foundation is approved
  adapters/
    atlas CLI, API, LSP, CI   # conceptual ownership; existing paths preserved
  public_api/                 # existing v1 compatibility facade
  legacy/                     # conceptual compatibility boundary; no immediate move
```

Existing paths remain authoritative through the transition. The hierarchy must
not be created wholesale in PR144; it shows dependency ownership and future
landing zones only.

## Proposed PR143: Platform Architecture

| Scope | Current package | Future package | Reason | Risk | Compatibility | Required tests |
| --- | --- | --- | --- | --- | --- | --- |
| Architecture documents and dependency inventory | N/A | `docs/architecture/ATLAS_*.md` | Establish a reviewed, evidence-supported target before source changes. | Low; documentation may overstate a future contract if not reviewed. | No runtime impact. | Markdown-link check and repository status check. |

## Proposed PR144: Minimal package refactoring

### Changes approved in principle

| Current package/module | Future package/module | Reason | Risk | Compatibility | Migration strategy | Required tests |
| --- | --- | --- | --- | --- | --- | --- |
| `moughorai.repository_report.safety` | `moughorai.platform.safety` as canonical implementation; old module remains a forwarding compatibility module | It contains generic source-free absolute-path checks, has no repository-report dependencies, and has at least 21 consumers outside repository reporting. | Medium: output safety regression or missed direct import. | Preserve old functions and type behavior at the original path. | Characterize existing helpers; add new module; forward old imports; migrate internal consumers in bounded batches. | Existing path-safety tests; AI/prompt/search/impact/refactor/evolution/debt/security rendering tests; direct old/new equivalence tests; import-rule test. |
| Direct type dependency from `semantic_snapshot` to `ai_context` | Same package locations; dependency inverted through a mapping/protocol or repository-local adapter | `AtlasSemanticSnapshot` imports `WorkspaceSemanticContext`, while snapshots are imported by context consumers, contributing to the 16-module static SCC. | High: snapshot byte identity, type behavior, and restore helpers are broadly used. | Preserve `AtlasSemanticSnapshot.create`, `.to_context`, `SemanticSnapshotStore.capture`, and existing `.ass` bytes unless an explicit schema migration is approved. | First add characterization tests; then remove only the runtime type edge; retain adapters at the repository boundary. | PR111 snapshot checksums, round-trip, atomic publication, concurrency, old-schema tests; public API fixture; clean-interpreter import test; SCC allowlist test. |
| Dependency governance | None initially, then a small test-only rule configuration | The current 1,438-edge graph and known SCC need a ratchet before a second domain arrives. | Low implementation risk; false positives if rules are too broad. | No API or format impact. | Add an AST rule test with a documented baseline allowlist; reject new platform-to-domain and domain-to-domain edges; reduce allowlist only after verified inversions. | Full suite; focused dependency-rule fixtures; imports of entry points. |

### Components that intentionally stay put in PR144

| Current package | Future ownership | Why no move is justified now |
| --- | --- | --- |
| `moughorai.measurement` | Platform-owned operational infrastructure, physical move deferred | It is domain-neutral by dependencies and highly reused, but its stable phase enum contains repository terms. First expose a carefully scoped facade only after compatibility tests establish the exact public contract. |
| `moughorai.semantic_evidence` and confidence classes | Repository Intelligence | Strong reuse within one domain does not make graph/repository `EvidenceKind` and `snapshot_id` semantics generic. |
| `semantic_snapshot`, `knowledge_graph`, `subject_resolution`, `workspace` | Repository Intelligence | Their models encode workspace and repository semantics despite high fan-in. |
| `plugin_sdk`, `rule_sdk`, `policy_packs` | Repository Intelligence extension boundary | Existing extension points and trust model are source-analysis and in-process concepts, not a platform extension system. |
| `atlas_cli.py` | Adapter/composition root | Its 34 dependencies are appropriate for an edge composition root. Splitting its roughly 90 KiB implementation needs command-behavior characterization, not an architectural rename. |
| `public_api`, `cli.py`, published console scripts | Compatibility adapters | The public v1 fixture and packaging tests make their removal or merge incompatible without a separate approved deprecation plan. |
| Large feature models/services | Their current domain packages | File size is a maintenance signal, not evidence for a safe package split. Split only around independently tested behavior. |

## Proposed PR145: Architectural Contracts and Drift

Architectural Drift remains a Repository Intelligence capability. It is gated by
an explicit, versioned architectural contract that names supported subjects,
allowed/forbidden relationships, policy provenance, scope, and limitation
states. PR128 pattern detection and PR141 repository evolution remain evidence
providers only; neither establishes intent.

| Current package | Future package | Reason | Risk | Compatibility | Required tests |
| --- | --- | --- | --- | --- |
| No current contract owner | New Repository Intelligence architectural-contract boundary, followed by drift evaluation only if approved | A deterministic policy is required before drift can be evaluated. | High: inventing intent or mislabeling graph absence. | No changes to PR128/PR141 semantics. | Policy parsing/validation; source-free graph evidence; unsupported/ambiguous states; deterministic rendering; no inferred defaults; full snapshot compatibility. |

This is not an authorization to implement PR145. The architecture contract must
be reviewed separately before any drift service is designed.

## Proposed PR146 and later: second-domain validation

Benchmark Foundation should start as a self-contained vertical slice based on
the frozen AI OC evidence spine and manually supplied, redistributable fixtures.
It must request extraction of a platform contract only when its requirement
matches a proven Repository Intelligence contract. Hardware and Log
Intelligence have no approved refactoring work at this time.

## Compatibility policy

- `moughorai.public_api` v1 type identity and signature manifest remain
  unchanged.
- Existing import paths receive forwarding modules before removal; removal is a
  separately versioned decision.
- Existing semantic snapshot schema, identifiers, checksums, archive behavior,
  and `latest.ass` semantics remain unchanged in PR144.
- CLI commands, JSON representations, plugin manifests, rule behavior, and
  deterministic text renderers remain regression-tested.
- Atlas AI OC files are not imported, copied, or edited by the migration.

## Risks and mitigations

| Risk | Evidence | Mitigation |
| --- | --- | --- |
| Snapshot/context cycle breaks imports or snapshot compatibility | 16-module static SCC; snapshot and public API tests construct contexts directly | Characterize import order and golden snapshot output before inversion; preserve adapters. |
| Source-free safety regression leaks an absolute path | Safety helper is used by 21 modules and protects prompts/reports | Preserve forwarding path; run feature rendering and adversarial path tests. |
| Premature core grows into a framework | Existing principles require a second real consumer before abstraction | Keep PR144 to two narrow corrections and a test rule. |
| Benchmark model is forced into repository abstractions | AI OC has capture/authority/time/retention semantics absent from repository graph | Build its first vertical slice separately and compare contracts explicitly. |
| Compatibility break in published CLI/public API | v1 fixture and packaging/CLI tests | Treat compatibility checks as blocking gates. |

## Explicitly rejected moves

- Do not move all repository packages below `domains/repository`.
- Do not rename `moughorai` or the `atlas`/`moughorai` console scripts.
- Do not merge `data_flow` and `dataflow` as part of platform work.
- Do not split `atlas_cli`, `impact_analysis.models`,
  `security_intelligence.models`, or other large modules without a bounded
  behavioral proposal.
- Do not move snapshots, graph, workspace, resolver, plugin SDK, rule SDK, or
  evidence record models into a generic core in PR144.

## Approval gate

Implementation begins only after approval of this plan, the dependency rules,
the exact PR144 file manifest, compatibility test matrix, and the proposed
architectural-contract scope for PR145. Until then, this is documentation-only
architecture work.
