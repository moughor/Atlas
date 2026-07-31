# Atlas Engineering Principles

## Status

This document defines permanent, normative engineering guidance for Atlas. It applies
to every future implementation, regardless of roadmap milestone or pull request.

The terms **MUST**, **MUST NOT**, **SHOULD**, and **SHOULD NOT** describe requirements
and strong recommendations for Atlas engineering decisions.

## 1. Evidence before inference

A production conclusion MUST be supported by structured semantic evidence.

Names, naming conventions, directory labels, unverified heuristics, prose, and LLM
output MUST NOT establish architectural, behavioral, security, dependency, or other
repository facts. Heuristics MAY identify candidates for deterministic verification,
but an unverified candidate MUST remain explicitly uncertain.

## 2. Deterministic reasoning before LLM reasoning

Atlas MUST compute repository facts through deterministic semantic analysis before
using an LLM.

LLMs MAY explain, organize, or communicate facts produced by Atlas. They MUST NOT
replace semantic analysis, manufacture missing facts, or silently convert
interpretation into repository evidence.

## 3. Unknown is preferable to unsupported certainty

Missing, incomplete, incompatible, or ambiguous evidence MUST produce `unknown`,
`insufficient`, `unavailable`, or another explicit uncertainty state.

Atlas MUST NOT fabricate certainty, infer a negative result from absent evidence, or
present an analysis as complete when its required evidence was not available.

## 4. Specialized analyzers remain authoritative

Domain-specific analyzers remain authoritative for the domains they analyze, including
language semantics, control flow, call relationships, dependencies, impact, and
security.

The canonical `KnowledgeGraph` integrates and relates their evidence through canonical
identities. It MUST NOT replace specialized analyzers, duplicate their logic, or
weaken their domain-specific semantics.

## 5. Preserve backward compatibility

Existing public APIs, semantic snapshots, serialized formats, identifiers, and
semantic contracts SHOULD be extended rather than rewritten whenever possible.

Changes MUST preserve established behavior unless a demonstrated limitation requires
an incompatible correction. Any unavoidable incompatibility MUST be explicit,
versioned, documented, and accompanied by a migration path.

## 6. Reuse before duplication

Atlas MUST NOT introduce a second engine, graph, confidence model, evidence model,
semantic pass, cache, or resolver when an existing component can be extended safely.

Before creating a component, the implementation MUST identify relevant existing
abstractions and document why extension is sufficient or why a new responsibility is
genuinely distinct.

## 7. Confidence is deterministic

Confidence MUST derive only from structured evidence, evidence coverage, agreement,
contradictions, ambiguity, and explicit limitations.

Confidence calculation MUST be reproducible for identical inputs. LLMs MUST NOT
create, raise, lower, or otherwise alter a confidence score.

## 8. Every conclusion is traceable

Every production conclusion MUST reference evidence that can be traced to the
semantic analysis that produced it.

Traceability SHOULD preserve the conclusion, evidence identity, producing analyzer
and version, relevant canonical identities, snapshot lineage, scope, and known
limitations. A conclusion without traceable evidence MUST NOT be presented as a
production fact.

## 9. Incremental evolution

Shared abstractions SHOULD be introduced only when a second real consumer demonstrates
a shared contract.

The first consumer SHOULD implement only the capability it needs. Later consumers
SHOULD extend that capability incrementally while preserving compatibility. Atlas
MUST avoid speculative frameworks, generalized infrastructure without demonstrated
consumers, and premature abstraction.

## 10. Repository intelligence over code summarization

Atlas is an evidence-based software engineering platform. Its primary goal is
deterministic understanding of software systems rather than probabilistic code
generation.

Repository structure, semantics, relationships, behavior, risks, and limitations
SHOULD be computed as structured intelligence. Natural-language summaries and
generated recommendations are presentation layers over that intelligence, not
substitutes for it.

## Application

Designs, implementations, tests, reports, and AI integrations MUST be evaluated
against these principles. When a trade-off cannot satisfy every principle, the
decision MUST preserve evidence integrity, determinism, traceability, and explicit
uncertainty, and the exception MUST be documented.
