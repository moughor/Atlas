# PR130 Design Pattern Detection

## Architecture

`PatternDetectionService` consumes a PR129 `KnowledgeGraph` and optional mappings of
existing `JavaArchitectureGraph` and `CallGraph` instances. It builds adjacency and
identity indexes only; it does not build or publish another graph.

The service fingerprints canonical and specialized structured inputs. The fingerprint
is the input lineage used for cache invalidation and evidence provenance. A small
bounded in-memory cache reuses identical immutable reports.

## Result model

Each `PatternFinding` contains:

- pattern kind;
- role-labeled canonical participating symbols;
- deterministic confidence score and tier;
- evidence IDs referencing the report evidence index;
- source-free explanation;
- explicit limitations;
- project/repository scope and language;
- detector version.

`PatternCapability` distinguishes evidence availability from a positive finding. If a
required semantic producer is missing, availability is `insufficient`. An absent
finding is therefore never presented as proof that a pattern does not exist.

Reports store schema version, producer version, input fingerprint, findings,
capabilities, and a deduplicated evidence index. `to_dict()` and `from_dict()` are
exactly idempotent.

## Confidence

PR130 uses the single `ConfidenceCalculator` implementation from
`moughorai.semantic_evidence`.

For each required role:

`support = Σ(reliability × specificity × role_weight) / Σ(role_weight)`

`confidence = clamp(support × coverage × agreement - contradiction - ambiguity, 0, 1)`

Required roles weigh `2`; corroborating roles weigh `1`. A missing required role
produces `insufficient` regardless of numeric support. Scores are rounded to four
decimal places and use the approved high/medium/low/insufficient thresholds. LLMs do
not participate.

## Evidence

Canonical graph edges use reliability `1.00`. Structured Java architecture and call
analysis results use reliability `0.90`. Specificity records how uniquely each
relationship supports the role. Evidence IDs are SHA-256 digests of normalized
producer, lineage, subject, source references, scope, language, detail, limitations,
reliability, and specificity.

Evidence contains canonical IDs, normalized relationship metadata, and producer
references. It contains no raw source. Only evidence referenced by findings is
persisted.

## Detection rules

| Pattern | Minimum implemented evidence | Current availability |
|---|---|---|
| Strategy | 2+ resolved implementations and typed client use | Normal Java pipeline |
| Factory | abstract return, 2+ compatible products, resolved constructor calls | Optional Java architecture + call graph |
| Builder | 2+ self-returning stages and distinct product return | Normal Java pipeline |
| Adapter | target inheritance, distinct composed adaptee, resolved delegation | Optional call evidence |
| Observer | subscription registration and notification call | Insufficient: registration producer absent |
| Decorator | shared contract, composed same contract, resolved delegation | Optional call evidence |
| Composite | component collection and recursive delegation | Insufficient: collection producer absent |
| Command | implementations, invoker relationship, receiver delegation | Optional call evidence |
| Chain of Responsibility | successor plus conditional forwarding | Insufficient: CFG forwarding producer absent |
| State | state implementations, delegation, resolved transition | Insufficient: transition producer absent |
| Template Method | base-to-hook call, override, subclass relationship | Optional call evidence |

Names, packages, directories, and LLM output are never evidence.

## Pipeline integration

The Java analyzer already creates `java_architecture_graph`. PR130 preserves that
artifact in recovered `SemanticDocument` values and collects it by project. After the
canonical graph is built, the collector runs `PatternDetectionService` and adds a
`design_patterns` object to the semantic context before snapshot capture.

Older persisted documents and snapshots remain readable because all new fields are
optional and additive.

The saved snapshot key is `semantic_context.design_patterns`. Its schema version is
`1`; the initial producer version is `atlas-pr130/1`. Repository-level explanations
consume a compact projection containing pattern name, status, confidence, participant
count, evidence count, and limitations. Participant identities and evidence details
remain outside the default repository prompt. Targeted subject explanations continue
to use the existing detailed context path.

## Complexity

Input indexing and the implemented detectors are bounded by graph nodes/edges and
specialized facts: `O(V + E)` construction with indexed joins over candidate
relationships. No all-pairs graph query is used. Cache space is bounded by the
configured report count, and snapshot evidence is restricted to emitted findings.

## Deferred work

PR130 intentionally does not add call, control-flow, data-flow, subscription,
collection-semantic, or transition passes. Languages without equivalent typed
producers remain explicit `insufficient`. PR131 and later functionality are not
implemented.
