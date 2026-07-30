# Atlas Architecture Decision Records (ADR)

> **Status:** Living Document
>
> This document defines how architectural decisions are recorded within Atlas.
> Every significant technical decision that impacts the architecture, public APIs,
> persistence model, extensibility, scalability, or long-term maintainability
> must be documented as an Architecture Decision Record (ADR).

---

# Purpose

Atlas is intended to become a long-lived software engineering platform.

Over time, hundreds of architectural decisions will be made.

Without documentation, it becomes impossible to answer questions such as:

- Why was this designed this way?
- Why was another approach rejected?
- Is this decision still valid?
- When should this decision be revisited?

ADRs provide the historical reasoning behind major technical choices.

---

# Goals

Architecture decisions should be:

- Explicit
- Versioned
- Reviewable
- Traceable
- Immutable once accepted

An ADR explains **why**, not only **what**.

---

# Decision Process

Every architectural decision follows the same lifecycle.

Draft

↓

Review

↓

Accepted

↓

Implemented

↓

Deprecated (optional)

↓

Superseded (optional)

---

# ADR Status

Each ADR must contain one of the following statuses.

## Draft

Idea under discussion.

No implementation yet.

---

## Proposed

Ready for architectural review.

---

## Accepted

Approved.

Implementation may begin.

---

## Implemented

The decision has been completed.

---

## Deprecated

Still exists but should no longer be used.

---

## Superseded

Replaced by another ADR.

Reference the replacement ADR.

Example

Superseded by ADR-0017

---

# ADR Template

Every ADR should use the following format.

```markdown
# ADR-XXXX Title

Status

Draft / Proposed / Accepted / Implemented

Date

YYYY-MM-DD

---

## Context

What problem are we solving?

---

## Decision

Describe the chosen solution.

---

## Alternatives Considered

Option A

Option B

Option C

Explain why they were rejected.

---

## Consequences

Positive

Negative

Risks

Trade-offs

---

## Migration Strategy

If applicable.

---

## Related PRs

PR123

PR145

etc.

---

## Related ADRs

ADR-0002

ADR-0011

```

---

# ADR Index

## Core Architecture

| ADR | Title | Status |
|------|-------|--------|
| ADR-0001 | Java-first Semantic Engine | Implemented |
| ADR-0002 | Semantic Snapshot (.ass) Format | Implemented |
| ADR-0003 | Workspace Model | Implemented |
| ADR-0004 | AI Explain Pipeline | Implemented |
| ADR-0005 | Ollama Provider Abstraction | Implemented |
| ADR-0011 | Project-Scoped Symbol Identity | Implemented |
| ADR-0012 | Analyzer Registry | Implemented |
| ADR-0013 | Cross-Language Semantic Graph | Implemented |

---

## Planned

| ADR | Title | Status |
|------|-------|--------|
| ADR-0006 | Analyzer Registry | Planned |
| ADR-0007 | Python Semantic Analyzer | Implemented |
| ADR-0008 | Multi-Language Semantic Graph | Planned |
| ADR-0009 | Knowledge Graph Architecture | Planned |
| ADR-0010 | AI Agent Framework | Planned |

---

# Decision Categories

Architecture

Large structural decisions.

Example

Knowledge Graph

---

Persistence

Storage model.

Example

Semantic snapshot format

---

AI

LLM providers

Prompt generation

Reasoning engine

Agents

---

Performance

Caching

Parallelism

Incremental analysis

---

Developer Experience

CLI

IDE

API

Plugin SDK

---

Language Support

Java

Python

Rust

Go

TypeScript

etc.

---

# Principles

Every accepted ADR should satisfy the following principles whenever possible.

## Correctness

Semantic correctness has priority over performance.

---

## Incremental

Prefer incremental computation over full recomputation.

---

## Extensible

Support future languages without architectural rewrites.

---

## Explainable

Atlas should always be able to explain how a result was produced.

---

## Deterministic

The same repository should always produce the same semantic model.

---

## Testable

Every architectural decision should be verifiable through automated tests.

---

## AI-Assisted

LLMs consume semantic knowledge.

They do not replace semantic analysis.

---

# Review Checklist

Before accepting an ADR, verify:

- Does it solve a real problem?
- Is it compatible with the long-term vision?
- Can it scale?
- Can it be tested?
- Does it increase complexity?
- Are there simpler alternatives?
- Does it require migration?
- Can future developers understand the reasoning?

---

# Long-Term Architectural Themes

The following themes guide Atlas evolution.

- Multi-language semantic analysis
- Knowledge Graph as the source of truth
- Incremental computation
- AI-native engineering workflows
- Plugin-based architecture
- Parallel processing
- Enterprise scalability
- Explainable AI
- Engineering agents
- Repository reasoning

These themes should influence every major architectural decision.

---

# Directory Structure

Recommended location

```
docs/
└── architecture/
    ├── ARCHITECTURAL_DECISIONS.md
    └── decisions/
        ├── ADR-0001-JAVA_FIRST_SEMANTIC_ENGINE.md
        ├── ADR-0002-SEMANTIC_SNAPSHOT_FORMAT.md
        ├── ADR-0003-WORKSPACE_MODEL.md
        ├── ADR-0004-AI_EXPLAIN_PIPELINE.md
        └── ...
```

---

# Final Principle

> **Architecture is a long-term investment.**
>
> Features come and go.
>
> Good architectural decisions continue creating value for years.
>
> Every ADR should make Atlas easier to evolve, easier to understand,
> and easier to extend.
