# Atlas Shared Infrastructure

Status: proposed ownership decision based on the PR142 codebase. This document
does not create a platform package or authorize moving production source.

## Rule of admission

A component belongs in Atlas Core only when inspection proves that it is
domain-neutral today, or when two implemented domains need the same precise
contract. A future possibility, a common noun, or a desire for symmetry is not
enough.

The required proof is:

1. two concrete consumers with the same input/output semantics;
2. compatible identity, lifecycle, retention, safety, and versioning needs;
3. a named owner and a compatibility policy;
4. deterministic and boundary tests; and
5. a migration that preserves existing supported imports and serialized data.

## Components justified by inspection

| Component | Evidence | Core disposition | Boundary |
| --- | --- | --- | --- |
| Engineering principles and dependency rules | Existing `ENGINEERING_PRINCIPLES.md` is explicitly permanent and normative; PR142 work already relies on determinism, evidence, compatibility, and incremental reuse. | Shared immediately as governance, not code. | Applies to every future domain. |
| Measurement session, operational metrics, filesystem ledger, and measurement report machinery | `moughorai.measurement` has no Atlas-package imports and 16 package consumers. Its module documentation already excludes measurements from semantic identity and evidence. | Platform-owned operational infrastructure after a stable facade is introduced. | Generic session mechanics may be shared; repository phase identifiers remain repository vocabulary. |
| Source-free absolute-path safety checks | `repository_report.safety` has 21 consumers across AI, graph, search, impact, refactoring, evolution, debt, and security packages; its implementation depends only on Python collections, regex, and URL decoding. | Move in PR144 to the platform-safety boundary with a compatibility forwarder. | It validates source-free projections; it is not a domain report builder. |
| Determinism, serialization, compatibility, and golden-test conventions | Snapshot checksums, public API signature fixtures, deterministic JSON, plugin manifests, and AI OC's schema/replay requirements all require this discipline. | Shared architectural convention now. | A generic serialization package is deferred until a second implemented domain uses the exact same canonicalization contract. |

## Components that are valuable but not yet Atlas Core

| Component | Why it is not promoted now | Required proof before promotion |
| --- | --- | --- |
| `semantic_evidence` | It has no internal dependencies and 13 Repository Intelligence consumers, but its `EvidenceKind` values include graph, semantic, and repository metadata facts and each record uses a repository `snapshot_id`. | A second implemented domain must need the same evidence-record identity, role, reliability, specificity, and confidence semantics without losing its own authority/time requirements. |
| `ConfidenceCalculator` | Its role/coverage/agreement model is reusable in spirit, but its interpretation depends on `EvidenceRecord` and Repository Intelligence reliability constants. | Demonstrate equal input meaning and calibration requirements across domains; otherwise each domain owns its confidence policy. |
| `SemanticSnapshotStore` | It is checksum-verified and immutable, but captures a `WorkspaceSemanticContext`, workspace fingerprint, analyzer version, and repository history reference. | A second domain must need the same immutable envelope, identity components, atomic pointer behavior, and retention semantics. |
| `canonical_json` in `semantic_snapshot.models` | It is a simple useful helper, but it currently lives inside a repository snapshot module and other packages also define local canonical JSON helpers. | Agree one canonical JSON specification and cross-runtime golden vectors before making a normative common helper. |
| `plugin_sdk` | It has explicit manifest, digest, trust, and lifecycle behavior, but its extension points are repository analyzer/policy-pack/reporter concepts, and plugins are trusted in-process Python code. | A second domain must need the same extension points and security model, or a separate platform plugin contract must be designed. |
| `Workspace`, `KnowledgeGraph`, `SubjectQuery` | High fan-in proves repository reuse, not cross-domain neutrality. Their fields and relationships encode source repositories. | No promotion is expected without a separately specified general model, which is not proposed. |

## Components explicitly rejected as shared infrastructure

| Rejected abstraction | Reason it is unsupported |
| --- | --- |
| Universal entity, fact, observation, graph, or intelligence record | Repository graph entities and AI OC benchmark entities have different identity, authority, time, and retention semantics. A common name would erase needed distinctions. |
| Generic database, object store, event store, or data lake | The repository uses workspace state and `.ass`; AI OC deliberately leaves physical storage open pending workload measurement. There are not two implemented storage consumers. |
| Global cache or history timeline | Existing cache and recovery are repository operational state. AI OC requires immutable capture/dataset lineage and separately defined retention. |
| Generic analyzer/extractor framework | `LanguageAnalyzer` returns repository `SemanticDocument`; it does not describe source acquisition or benchmark extraction. |
| Generic renderer or dashboard protocol | Current renderers are feature-local, and no second domain has a stable user-facing projection contract. |
| Universal confidence score | Confidence input roles and calibration depend on domain evidence; a numeric score without domain semantics would mislead. |
| Cross-domain plugin service locator | Existing `PluginContext` exposes arbitrary in-process services and is explicitly not a security boundary. |

## Target platform kernel

The initial kernel should therefore be intentionally small:

```text
Atlas platform kernel (proposed)
  - architecture and dependency governance
  - source-free projection safety
  - operational measurement session and generic metric/report mechanics
  - compatibility, determinism, and versioning conventions
```

The kernel does not own source acquisition, source analysis, semantic graphs,
repository snapshots, benchmark data, hardware data, LLM policy, domain
renderers, or storage topology.

## Operational safeguards

- Measurements remain opt-in operational artifacts and never enter semantic
  identity, evidence, snapshot contents, or deterministic result ordering.
- Source-free safety validation is applied before a report, prompt, or exchange
  projection crosses a domain or provider boundary.
- Existing plugin trust remains admission control only. A future platform must
  use OS/process isolation before claiming containment of untrusted domain
  extensions.
- Every shared contract must reject unsupported schema versions or return an
  explicit `incompatible` state; it must not silently reinterpret data.

## Recommendation

Promote only measurement mechanics and source-free safety ownership in the
first platform refactoring. Keep all other candidates in Repository
Intelligence and use the Benchmark Foundation to validate, rather than assume,
the next shared contract.
