# Atlas PR Roadmap V2

Status: proposal only. This document does not renumber existing merged pull
requests, authorize implementation, or alter the historical roadmap.

## Why the roadmap changes

PR142 completed the Technical Debt first slice. The planned PR143
Architectural Drift cannot correctly proceed because Atlas has no explicit
architectural contract. PR128 detects current architecture; PR141 compares
canonical snapshot differences. Neither states what a repository is intended
to be. Treating either as intent would violate Atlas's evidence-first and
unknown-over-certainty principles.

The frozen AI OC planning work also demonstrates that Atlas's future includes
independent evidence domains. Benchmark Intelligence requires source authority,
immutable capture, benchmark/run/hardware identity, time, retention, and
external-model semantics that should not be coupled to repository semantics.

The roadmap therefore inserts platform-boundary work before either drift or a
second domain.

## Proposed sequence

| Proposed PR | Proposed name | Outcome | Preconditions and exit gate |
| --- | --- | --- | --- |
| PR143 | Platform Architecture | Review and approve the six architecture documents, platform dependency rules, domain boundary, and minimal refactoring manifest. | Documentation reviewed; no production code in scope. |
| PR144 | Minimal Package Refactoring | Correct only the demonstrated generic safety-module placement, remove the narrow snapshot/context dependency edge if characterization permits, and add dependency-rule regression tests. | Public API, CLI, snapshot, plugin, and source-free rendering compatibility gates pass. |
| PR145 | Architectural Contracts and Drift | Define an explicit Repository Intelligence architecture-policy contract; evaluate drift only against that contract and verified graph evidence. | PR144 complete; policy ownership, schema, defaults, limitations, and migration behavior approved. No inferred intent. |
| PR146 | Benchmark Foundation | Implement the AI OC evidence spine using manually supplied, redistributable fixtures: source registry, immutable capture envelope, extraction batch/observation boundary, and deterministic IDs. | Platform boundary proven; AI OC fixture provenance and terms policy approved; no automated acquisition. |
| PR147 | HWBOT Fixture Parser | Add one approved, fixture-only Benchmark Intelligence parser and preserve raw-to-observation lineage. | PR146 model and fixture contract pass; no scraping schedule or unsupported source claim. |
| PR148 | Benchmark Normalization and Identity | Implement conservative benchmark, hardware, submission, and run identity resolution; preserve ambiguous/unresolved states. | PR147 supplies representative fixtures and identity acceptance tests. |
| PR149 | Deterministic Benchmark Analytics | Build compatible cohorts, formula reconciliation, deltas, and bounded observations from versioned evidence. | PR148 supports comparability; formulas, units, and rounding have approved evidence. |
| PR150 | Benchmark Query and Explanation | Publish bounded source-free Benchmark Intelligence projections and optional explanation that cannot manufacture facts. | PR149 projections and citation/limitation contracts pass. |
| PR151+ | Future domains or platform extractions | Consider Hardware Intelligence, Log Intelligence, shared storage, or a cross-domain exchange contract only after a concrete approved domain need exists. | Two implemented consumers demonstrate identical contract and lifecycle requirements. |

## Existing roadmap items not automatically renumbered

The historical roadmap's PR144--PR151 labels are preserved as historical
planning context. This proposal does not silently relabel Quality Gates,
Knowledge Persistence, Parallel Analysis, Workspace Cache v2, Distributed
Knowledge Store, IDE Integration, Atlas Server, or Atlas Platform 3.0.

Their sequencing must be reassessed after PR144 because:

- quality gates need a clear domain policy owner;
- knowledge persistence must not merge repository snapshots with benchmark
  capture/dataset lifecycle by assumption;
- distributed storage and server work are unsupported until actual domain
  workloads, storage, and access requirements are measured; and
- IDE and editor integration remain Repository Intelligence adapters unless a
  distinct domain integration is designed.

## Roadmap principles

1. A roadmap item is enabled by evidence and an owner, not by a desirable
   feature name.
2. Architectural Drift is not a substitute for architecture policy. It is
   blocked until a deterministic policy contract exists.
3. Benchmark Intelligence begins as an isolated evidence foundation, not as a
   plugin, repository graph extension, or product-wide storage migration.
4. Shared infrastructure is extracted only after a second implemented domain
   proves the exact contract; AI OC planning supplies design pressure but not a
   code-level consumer by itself.
5. Every PR preserves source-free safety, deterministic ordering, schema
   compatibility, explicit unavailable/incompatible states, and tests
   proportionate to its boundary.
6. No PR claims a platform capability merely because folders have been moved.

## Deferred alternatives

| Alternative | Why deferred |
| --- | --- |
| Implement PR143 drift using PR128 or PR141 | Neither provides intended architecture; result would invent policy. |
| Start Benchmark Intelligence immediately in repository packages | It would couple distinct capture/authority/time/retention semantics to Repository Intelligence. |
| Create a generic evidence, graph, storage, plugin, and rendering framework first | The codebase has only one implemented intelligence domain; this would violate incremental-abstraction rules. |
| Move every package into a new `platform` or `domains` hierarchy | 532 modules, 1,438 imports, public API and CLI fixtures make a bulk move expensive without solving a demonstrated capability gap. |
| Reprioritize distributed/server work as a platform foundation | No shared domain workload or storage topology has been measured. |

## Decision points

- Approve PR143 documents before authorizing any source change.
- Approve the exact PR144 change manifest and test matrix before a refactor.
- Approve the explicit Architectural Contract before a PR145 drift design.
- Approve AI OC fixture provenance, collection permissions, and evidence schema
  freeze before a PR146 implementation.
- Reassess the historical enterprise roadmap only after the platform boundary
  and first Benchmark Foundation slice are verified.

## Recommendation

Adopt PR143 Platform Architecture as the immediate documentation-only phase,
followed by a deliberately narrow PR144. Keep PR145 gated by an explicit
architecture contract. Use Benchmark Foundation, not a speculative framework,
as the first real test of Atlas as an Evidence Intelligence Platform.
