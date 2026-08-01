# Atlas M1 Determinism Audit

## Scope and conclusion

This audit covers deterministic outputs present through PR134: semantic snapshots,
the canonical `KnowledgeGraph`, repository summaries, risk analysis, repository
reports, default repository explanations, structured explanations, and their
serialization boundaries.

Normal same-input canonical outputs are deterministic. Raw snapshot bytes and
snapshot IDs are intentionally capture- and location-sensitive and must not be used
as portable semantic goldens. M1 therefore separates artifact integrity from
comparable semantic hashes instead of weakening or rewriting snapshot identity.

## Executed audit evidence

The determinism review actually executed the following focused suite before the
final M1 hardening edits:

```text
90 passed in 3.12s
```

The focused scope covered snapshot persistence, repository summaries, the canonical
graph, risk analysis, repository reports, and structured explanation integration.

Fresh processes with `PYTHONHASHSEED=1` and `PYTHONHASHSEED=2` produced identical:

- PR133 repository-report hashes;
- PR133 selected-context hashes;
- PR133 projected-snapshot hashes;
- PR134 resolution hashes;
- PR134 selected-context hashes;
- PR134 bounded-incident hashes.

A checksum-verified legacy local snapshot loaded twice and produced byte-identical
default explanations. It was not accepted as a golden because it is ignored local
state without sufficient versioned provenance.

Additional read-only probes demonstrated:

- changing only `history_reference` changes raw snapshot identity;
- relocating an otherwise identical empty workspace from `C:/checkout-a/repo` to
  `D:/checkout-b/repo` changes snapshot identity;
- nested semantic-context mutation previously left `snapshot_id` unchanged and made
  the serialized payload fail identifier validation;
- boolean and fractional schema values were accepted by the old integer coercion.

The first complete M1 suite exposed two regressions in adversarial in-memory snapshot
tests; persistence-only finite-JSON enforcement corrected the boundary. The complete
post-fix suite then executed successfully: `3,681 passed, 1 skipped in 15.32s`.

## Output audit

| Output | Deterministic behavior | Audit result |
|---|---|---|
| `KnowledgeGraph` | Canonically sorted nodes and edges; canonical JSON digest | Stable for valid production inputs and reordered input tests |
| Repository Summary | Projects, languages, build systems, frameworks, entry points, dependencies, and hierarchy are sorted | Stable for identical workspace evidence |
| Risk Analysis | Deterministic metric normalization, evidence IDs, tie-breaking, ranking, and round trip | Stable; Git evidence remains repository-state dependent |
| Repository Report | Fixed section order, canonical item order, evidence closure, exact omitted counts, and fixed-point token selection | Stable and provider-free |
| Default Explain | Deterministic Markdown from the bounded repository report or compatible legacy context | Stable and provider-free |
| Structured Explain JSON | Canonical subject resolution, bounded facts, evidence closure, and exact omission counts | Stable and provider-free |
| Provider narrative | External model output | Intentionally excluded from golden hashes |
| ASS serialization | Sorted-key UTF-8 JSON, LF output, checksum, content-derived ID, atomic publication | Stable for the exact capture payload; not relocation invariant |

## M1 hardening status

### Fixed in M1

- `SemanticSnapshotStore` revalidates the complete snapshot immediately before
  serialization. A mutated or directly inconsistent object can no longer be
  published and discovered only on reload.
- Historical snapshot publication uses atomic no-clobber semantics across independent
  store instances, so same-second concurrent captures cannot overwrite an immutable
  archive. The replaceable `latest.ass` pointer remains intentionally last-writer-wins.
- Snapshot schema parsing requires an exact non-boolean integer. Snapshot identity,
  workspace fingerprint, and analyzer version require exact non-empty strings;
  invalid history-reference types are rejected consistently at creation and load.
- A compact, source-free schema-v1 ASS fixture provides a tracked compatibility and
  deterministic replay boundary.
- The benchmark manifest records raw snapshot SHA-256, snapshot ID, semantic payload
  hash, repository-report hash, explanation hash, project count, workspace-project
  order, and fresh-analysis order as separate values with exact semantics.
- Manifest comparison treats differing runtime implementation/minor, OS release,
  architecture, repository commit, checkout identity, repeat count, worker count,
  cache mode, or measurement scope as incomparable rather than masking environmental
  differences.
- Unpinned repository revisions and unlinked replay result counts are explicit and
  cannot become baseline-eligible.
- Raw snapshot drift with stable semantic content is reported separately from a
  semantic regression.

These items describe the current M1 working tree. Their pass status belongs to the
final M1 validation report.

### Deferred intentionally

- Deep freezing of every nested snapshot value is deferred. Pre-save validation
  closes the durable corruption path while preserving the established mapping API
  and avoiding an unmeasured memory expansion on large snapshots.
- A portable raw snapshot or graph identity is deferred. Absolute workspace roots
  participate in semantic context and canonical repository identities; deleting them
  ad hoc would be a compatibility change, not a stabilization fix.
- Strict `KnowledgeGraph.from_dict()` validation is deferred. It currently ignores
  the graph schema version, skips non-mapping records, and resolves duplicate node
  IDs by last occurrence. Normal production output is canonical, but the external
  deserialization boundary remains permissive.
- Provider-generated targeted narrative remains nondeterministic by design and is
  never a regression hash.

## Regression policy

For comparable runs, the following are failures unless an intentional semantic
change and reviewed baseline update explain them:

- project, success, or failure count drift;
- project-order drift;
- canonical semantic payload drift;
- repository-report drift;
- provider-free explanation drift;
- graph, risk, or structured-context drift in their focused tests.

Raw ASS byte or ID drift alone is an integrity observation. It becomes a correctness
failure only when the complete capture identity is controlled, including repository
commit, Atlas commit, checkout root, initial Atlas state, history reference, worker
configuration, Python minor version, and operating system.

Timing and observation timestamps are measurements, not deterministic identity.
Performance comparisons require comparable environments and independent confirmation
under the M1 performance policy.

## Limitations

- Raw snapshot hashes are not portable across checkout roots and can change between
  successful captures because `history_reference` is part of snapshot identity.
- The M1 semantic payload hash removes capture-history identity but still contains
  the persisted absolute root; cross-host comparison therefore requires a controlled
  root or explicitly narrower canonical section hashes.
- Git-backed risk output depends on repository HEAD, history depth, shallow-clone
  state, configured commit window, and available ownership evidence.
- Optional historical runs and profiling metrics can contain timestamps or durations;
  benchmarks must not treat those observations as portable semantic identity.
- Python minor version, OS path semantics, worker count, and cache mode remain
  comparability dimensions even when canonical ordering is stable.
- Maven fresh-analysis evidence and Quarkus replay evidence are different benchmark
  classes and must not be presented as equivalent validation.
- No large Maven or Quarkus snapshot is committed as a golden; only compact,
  provenance-complete manifests should be versioned.
- Strict malformed-input behavior for the canonical graph remains future hardening.
