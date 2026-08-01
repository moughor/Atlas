# Atlas M1 Technical Debt Audit

## Scope

This audit covers the `b788efea901dffc980ab0bfa9d5afe1e57512a1a`
baseline before PR135. It reviews production and benchmark modules, the public API,
snapshot compatibility, architecture and roadmap documentation, historical
verification records, and tracked temporary artifacts. It does not authorize a
roadmap feature or a repository-wide refactor.

The classifications below reflect demonstrated impact. "Fixed in M1" means the
current M1 working tree contains the narrow mitigation and its focused regression
test or fixture. Final M1 validation is reported separately; this audit does not
claim that unexecuted tests passed.

## Critical

No critical technical debt was identified.

## High

### Invalid snapshot persistence after nested mutation

`WorkspaceSemanticContext` and `AtlasSemanticSnapshot` protect only the outer
mapping. A read-only audit probe changed a nested context value successfully,
left `snapshot_id` unchanged, and then received:

```text
SemanticSnapshotError: semantic snapshot identifier mismatch
```

Before M1, `SemanticSnapshotStore.save()` could serialize that inconsistent object
and defer the failure until reload.

Status: **fixed in M1**. Serialization now validates the complete snapshot through
`AtlasSemanticSnapshot.from_dict()` before writing. A focused regression test verifies
that a nested mutation is rejected and that `latest.ass` is not created. Deep freezing
the entire context remains deferred because it changes a widely consumed mapping
contract and can materially increase memory use for large snapshots.

### Raw snapshot identity is not portable

The semantic context includes the resolved absolute workspace root, and
`history_reference` participates in `snapshot_id`. An audit probe using otherwise
identical empty contexts produced different IDs for `C:/checkout-a/repo` and
`D:/checkout-b/repo`:

```text
8379db1b1d9815eab4b9e4597f7e683b5800e223a837bc569d93bae539a53b9b
5338b3632ed841f4949821e821d5d7f2dbc9aa2c96e86315964096977d445ab5
```

This is not same-input ordering nondeterminism, but it prevents treating a raw ASS
hash as a portable cross-host golden.

Status: **mitigated and documented in M1; format change deferred**. The benchmark
contract separates raw artifact integrity, snapshot identity, and semantic-section
hashes, and requires comparable checkout and environment identity. Removing or
renaming persisted root fields is deferred because it would change established
snapshot semantics and canonical graph identities.

### Concurrent stores could overwrite a same-second historical archive

The original no-replace path checked existence before `os.replace()`. Because locks
belong to individual store instances, two stores using the same timestamp could both
pass the check and overwrite one immutable archive.

Status: **fixed in M1**. Historical publication now uses atomic no-clobber linking,
falls back deterministically to a snapshot-ID suffix, and has a two-store concurrency
regression test. Only `latest.ass` retains replace semantics by design.

## Medium

### Public API compatibility was self-referential

The compatibility test compared runtime constructor signatures with a mutable
manifest defined in the same module. A constructor change accompanied by an edited
manifest therefore had no independent prior-release reference. Deleting a manifested
runtime export also caused `public_api_manifest()` to raise `KeyError` before the
compatibility helper could report the removal.

Status: **fixed in M1 for the current v1 contract**. A tracked independent v1 fixture
now anchors constructor signatures, and missing runtime exports are reported
deterministically. Method behavior, enum membership, and serialized payload contracts
are not yet covered by this constructor manifest; extending that boundary is future
work driven by real external consumers.

### Persisted snapshot compatibility lacked a tracked artifact

Existing tests created snapshots with the current implementation or assembled
legacy-shaped dictionaries at runtime. No committed `.ass` artifact represented an
earlier producer.

Status: **fixed in M1 for schema v1**. A compact, source-free v1 snapshot fixture is
tracked and replayed through checksum, snapshot-ID, and deterministic artifact
collection. Large Maven and Quarkus snapshots remain external; only their compact
manifests belong in version control.

### Snapshot schema parsing accepted ambiguous numeric values

`AtlasSemanticSnapshot.from_dict()` previously used `int(...)`, so boolean and
fractional values could be interpreted as schema 1 before later integrity checks.

Status: **fixed in M1**. The loader now requires an exact non-boolean integer, exact
non-empty identity/version strings, and a valid history-reference type. Creation and
loading use the same history-reference contract.

### Release lineage remains ambiguous

`pyproject.toml` and `moughorai/version.py` have reported `2.0.0` since the PR100-era
stabilization, while later work materially extended snapshots and repository
intelligence. Tests correctly keep the two version sources aligned, but a version
alone cannot distinguish those Atlas revisions.

Status: **deferred release decision**. M1 benchmark manifests record the exact Atlas
commit as well as the package version. A new semantic version must be chosen only as
part of an explicit release decision; M1 does not guess or silently change it.

### Architecture documentation has two competing levels of freshness

The README-linked `docs/ARCHITECTURE.md` is accurate but omits the PR127-PR134
repository-intelligence ownership chain. The orphaned
`docs/architecture/ARCHITECTURE_OVERVIEW.md` describes Python analysis and the
canonical Knowledge Graph as future work and presents an LLM-only data flow.

Status: **fixed in M1**. The concise README-linked guide now documents the current
repository-intelligence ownership chain, canonical-versus-specialized graph boundary,
and deterministic explain role. The older overview is explicitly historical and
non-normative.

### ADR index does not match the tracked decisions

`ARCHITECTURAL_DECISIONS.md` lists ADR-0001 through ADR-0005 as implemented although
their files are absent, and lists Analyzer Registry, the multi-language graph, and
the Knowledge Graph as planned despite implemented successors or roadmap work. Only
ADR-0007 and ADR-0011 through ADR-0016 are currently tracked.

Status: **fixed in M1 without manufacturing history**. The index now lists only the
tracked ADR files, directs future work to the official roadmap, and labels absent
older references as non-normative historical labels.

### Historical verification documents depend on unavailable patches

The audit found 135 reference sites in 84 tracked Markdown files naming 61 patch
files that are not tracked. `.gitignore` intentionally excludes delivery patches,
so those instructions are not reproducible from a clean checkout. The unnumbered
AI-context integration verification also names a patch absent from the local tree.

Status: **deferred archival policy**. Numbered historical records should reference an
exact commit or an external release artifact with a checksum. Large historical
patches should not be added to Git merely to satisfy stale instructions. The three
unnumbered AI-context delivery records are clear archive or removal candidates after
their PR121 replacement is confirmed.

### Normative engineering documents are difficult to discover

The engineering principles, confidence model, evidence model, testing strategy, and
roadmap dependency matrix are not collected in the README or architecture guide.

Status: **fixed in M1**. The current architecture guide links the official roadmap,
dependency matrix, engineering principles, confidence model, evidence model, testing
strategy, and stability guidance without copying their content. The stale Kiro review
request is explicitly marked as historical input.

## Low

### Obsolete alternate CLI module

`moughorai/main.py` has no inbound production, test, entry-point, or documentation
reference. It duplicates CLI concepts and states that the Ollama connection is not
implemented, contrary to the current platform.

Status: **deferred removal**. Confirm whether direct `python -m moughorai.main` usage
requires a deprecation period; the supported `moughorai` and `atlas` entry points are
unaffected.

### Unreferenced Java semantic walker

`moughorai/java_semantics/walkers.py` is not exported and has no production, test, or
documentation consumer.

Status: **deferred ownership check**. Static absence of references alone is not enough
to remove a potentially directly imported provisional module.

### Java-only package wording

The root package docstring still calls Atlas a Java semantic-analysis platform even
though Python and cross-language analysis are implemented.

Status: **fixed in M1**. The package description now reflects deterministic
multi-language static analysis without changing runtime behavior.

## Future

- Extend compatibility fixtures only when a second real public contract needs them.
- Introduce check-only formatting and linting incrementally; do not create a broad
  formatting diff during stabilization.
- Define a portable repository identity only through an explicit snapshot and graph
  compatibility decision.
- Archive historical PR delivery records under one documented retention policy.

## Confirmed clean areas

- All six tracked benchmark scripts have a current test or documentation consumer;
  none is demonstrably dead.
- No tracked temporary, debug, replay, or validation utility was found at the audited
  baseline.
- No zero-byte tracked file was found.
- All Markdown inline links resolved, and all backticked Markdown document references
  existed.
- Local pytest, build, replay, wheel, and delivery outputs are ignored rather than
  tracked.
- A static import audit of 496 production modules found only the legitimate CLI entry
  point, the obsolete alternate CLI, and the unreferenced walker without inbound
  imports.

No test suite was run while producing this document.
