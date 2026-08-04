# PR141 Repository Evolution

## Scope and status

PR141 implements the first safe slice of the official **Repository Evolution**
roadmap item:

> Track semantic evolution across commits.

The slice compares two checksum-verified Atlas Semantic Snapshots and reports
deterministic differences in their PR129 canonical graphs. The service receives an
explicit pair. The CLI requires the base path and accepts either an explicit head
path or the verified `latest.ass` pointer. It is a source-free, request-local
observation of semantic snapshot evolution.

Current snapshots do not prove clean-worktree commit binding. PR141 therefore keeps
semantic snapshot comparison and Git commit association as separate capabilities.
Optional compatible PR132 Git-head evidence produces only a **partial** association.
Without that evidence, commit association is unavailable while snapshot comparison
can remain available.

PR141 does not implement PR142 Technical Debt, PR143 Architectural Drift, or any
later roadmap item.

## Architecture

```text
  explicit base .ass                 explicit head .ass or latest.ass
        |                                         |
        +------ PR111 checksum/ID verification ---+
        |                                         |
        +--------- PR134 snapshot restore --------+
                          |
                  PR129 canonical graphs
                          |
       deterministic node and relationship merge/difference
                          |
       PR134 safe subjects + PR130 evidence/confidence
                          |
          bounded evolution response and renderer

optional PR132 Git-head evidence ----> partial commit association
```

The evolution service owns only pairwise orchestration, comparison, capability state,
and projection. It is not a graph, resolver, traversal engine, history collector,
impact predictor, architecture detector, security scanner, evidence model,
confidence model, persistence layer, or cache.

## Inputs

The request identifies:

- one base semantic snapshot path;
- one head semantic snapshot path (the CLI defaults this to `latest.ass`);
- deterministic limits on returned node and relationship changes.

Both files are loaded through `SemanticSnapshotStore`. Checksums, content-derived
snapshot IDs, schema versions, and finite deterministic JSON remain PR111 concerns.
The service never accepts raw source or patch text.

Snapshots are never selected by neighboring archive timestamps. Capture time is an
operational filename property, not a semantic ordering contract. The CLI's
`latest.ass` default is the established verified pointer, not a timestamp-based
timeline selection. Identical snapshots, same-commit captures, and same-second
captures are valid inputs and retain their actual capability states.

## Compatibility

Pairwise canonical comparison requires:

- two valid supported semantic snapshots;
- supported canonical graph schema in both snapshots;
- restorable PR129 graphs through the PR134 boundary;
- compatible repository/workspace identity;
- compatible analyzer version for normal comparison.

Analyzer-version equality is necessary but is not proof that every producer,
configuration, language capability, or coverage input is identical. PR141 therefore
reports exact snapshot observations only; it does not claim complete producer
comparability or assign a graph difference to developer action. Compatible
producer/configuration/coverage fingerprints remain deferred.

Older schema-v1 snapshots remain valid. If one lacks the canonical graph, the graph
comparison capability is unavailable rather than reconstructed by another engine.
If one lacks PR132 risk data, only commit association is unavailable.

Snapshot workspace fingerprints are expected to differ when repository content
changes and are not used as a same-repository equality requirement. Conversely,
matching fingerprints alone do not establish repository identity or commit binding.

## Canonical node comparison

Nodes are matched only by the internal PR129 canonical graph identity. For a matched
identity, canonical fields are compared exactly. Observations are:

- `added`: identity exists only in the head graph;
- `removed`: identity exists only in the base graph;
- `modified`: identity exists in both graphs but its canonical projection
  differs.

The public response carries the safe PR134 subject projection rather than the raw
internal graph ID. Absolute checkout-root material is not exposed. Changed field
names and before/after projection digests are reported, but raw changed metadata,
source text, literals, internal graph payloads, and raw edge evidence are not
included.

`removed` means absent from the compared head graph. It does not mean deleted source,
dead code, a breaking API, an intentional removal, or an unreachable runtime path.
An added/removed pair is never converted into a rename or move without a future
authoritative identity producer.

## Canonical relationship comparison

Relationship identity is:

```text
(source canonical ID, target canonical ID, relation kind)
```

Observations are:

- `added`: relationship identity exists only in the head graph;
- `removed`: relationship identity exists only in the base graph;
- `modified`: the identity exists in both graphs but canonical edge evidence
  differs.

Separating evidence changes prevents producer-detail drift from being mislabeled as a
new or removed semantic relationship. Supported relation enum values are not evidence
that a producer populated them. PR141 compares only relationships actually present in
each restored graph and preserves resolver coverage limitations.

Structural `ownership` is a canonical containment relationship; it is not developer,
team, CODEOWNERS, blame, or organizational ownership.

## Evidence and confidence

Every emitted observation has PR130 evidence referencing:

- base and head snapshot identities;
- base and head graph digests;
- safe canonical subject identities;
- the exact comparison category.

Evidence records are canonical, source-free, closed under every emitted reference,
and retain their respective base or head snapshot lineage. The response input
fingerprint binds both snapshot IDs, graph digests, analyzer identities, optional
PR132 analysis-time Git heads, and both request limits. Commit-association evidence
is a separate capability and cannot increase an observation's confidence.

Confidence is calculated by the shared PR130 calculator. Required roles distinguish:

- verified base snapshot;
- verified head snapshot;
- canonical identity;
- commit association when a commit-level conclusion is requested.

Missing commit evidence therefore cannot lower an exact snapshot observation into a
fabricated commit fact. Snapshot-delta confidence and commit-association state remain
separate.

## Commit association

PR141 may inspect a compatible PR132 risk report for a unique valid
`git-head:<object-id>` evidence reference. It validates producer/schema compatibility,
report lineage, evidence identity, and canonical graph digest before retaining the
reference.

The states are:

| State | Meaning |
| --- | --- |
| `partial` | Each required snapshot has one compatible, distinct Git-head association |
| `unavailable` | One or both snapshots contain no compatible unique Git-head evidence |
| `incompatible` | Evidence is malformed, ambiguous, or bound to a different canonical graph |

There is no `available` state in the first slice because the snapshot does not prove
worktree cleanliness or immutable analysis inputs. PR141 does not infer ancestry,
chronology, branch membership, merges, rebases, or intent. A Git commit object and a
semantic snapshot remain distinct identities.

## Capability states

The response reports capability state independently for at least:

- snapshot-pair verification;
- canonical node comparison;
- canonical relationship comparison;
- commit association;
- rename tracking;
- API compatibility;
- security evolution;
- architectural drift.

States preserve the repository conventions `available`, `partial`, `unavailable`,
`insufficient`, and `incompatible` where applicable. Empty results never imply that
an unavailable analysis found no changes. A valid comparison with zero changes is
distinguished from missing or incompatible graph evidence.

## Ordering, bounds, and determinism

Comparison work is a deterministic merge over canonical node and relationship order.
Ordering and tie-breaking use only normalized enums and canonical identities. Node
and relationship selection each has a deterministic independent bound with exact
total, retained, unchanged, and omitted counts.

For identical verified snapshots and request:

- change ordering is identical;
- evidence IDs and confidence are identical;
- input and output fingerprints are identical;
- JSON and human rendering are byte-identical;
- reordered equivalent graph inputs normalize to the same result.

Malformed, duplicate, dangling, oversized, non-finite, or path-unsafe input is
rejected or represented by an explicit degraded capability state according to the
existing snapshot and resolver boundaries. Terminal rendering escapes control
characters deterministically.

## Source-free and trust boundary

PR141 consumes persisted semantic metadata only. It does not read source files,
retain diff source lines, invoke a provider, construct a prompt, or consult an LLM.
Names, package layout, filenames, search rank, report prose, and model output cannot
create identity or conclusions.

Output excludes:

- source text and literals;
- absolute checkout paths rejected or projected by the established PR134 boundary;
- raw canonical node metadata and edge-evidence values;
- contributor identities;
- provider output;
- raw repository content outside the verified semantic snapshot.

Safe PR134 candidates still contain structured semantic display fields such as names,
qualified names, project labels, and relative paths. These values are treated as
untrusted display text. The human renderer escapes control characters
deterministically. PR141 does not claim a general secret detector for semantic
identifiers; it does not send them to a provider or persist the response.

The deterministic renderer presents existing observations and limitations. It never
adds facts, confidence, causality, or intent. Per-change limitations are rendered as
one deterministically sorted, deduplicated list to keep human output compact.

## Persistence and cache behavior

Repository-evolution responses are request-local and reconstructible. PR141 adds no
semantic snapshot key and no durable state. It does not modify:

- semantic snapshot schema or publication;
- history database schema;
- workspace persistence or recovery;
- incremental caches;
- conversation memory;
- finding baselines;
- benchmark manifests.

No new cache is justified by the first pairwise consumer. Snapshot loading and
comparison are measured before any later persistence or indexing proposal. PR145
remains the roadmap owner of broader knowledge-persistence consolidation.

## Complexity and performance

The comparison target is `O(V + E)` over the two restored canonical graphs, plus
`O(K)` retained output where `K` is bounded by the request. No recursive traversal,
centrality, impact propagation, multi-commit timeline, or concurrency is introduced.

The dominant risk is loading two large semantic snapshots and constructing their
existing resolver indexes. Measurements must separate:

- base and head snapshot loading;
- resolver/index construction;
- node comparison;
- relationship comparison;
- evidence/confidence construction;
- rendering and serialization;
- snapshot bytes and process/Python peak memory.

Pairwise behavior is intentional. Multi-snapshot history would multiply live-state,
I/O, comparison, and persistence costs and remains deferred until measured need and a
compatible storage owner exist.

## Explicit limitations

PR141 does not establish:

- clean-worktree commit binding;
- Git ancestry or chronological evolution;
- semantic rename or move identity;
- exact source declaration or hunk ownership;
- API, ABI, binary, or external-consumer compatibility;
- architecture adoption, violation, or drift;
- introduced, fixed, or unchanged security vulnerabilities;
- runtime reachability, dispatch, deployment, or behavior;
- developer, team, or organizational ownership;
- migration requirements or target architecture;
- developer intent or rationale.

Unknown remains unknown, unavailable remains unavailable, and partial remains
partial.

## Deferred work

Later roadmap-compatible work may add only when authoritative evidence exists:

- capture-time Git revision and clean/dirty/unstable provenance through the existing
  Git owner, with TOCTOU and benchmark impact reviewed;
- compatible producer/configuration/coverage fingerprints;
- stable cross-checkout repository identity;
- explicit timeline selection and retention under the established persistence owner;
- integration with PR132's existing comparable risk-trend contract;
- authoritative semantic rename/move producers;
- bounded higher-level finding comparison with stable identity and complete coverage.

PR143 remains responsible for Architectural Drift. PR141 must not anticipate it by
turning graph differences into architecture conclusions.
