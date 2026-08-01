# Atlas Architecture Overview

> **Historical, non-normative document.** This overview predates the completed
> Python analyzer, canonical Knowledge Graph, repository-report, and deterministic
> explanation pipeline. Use `docs/ARCHITECTURE.md` for the current architecture and
> ownership boundaries. The content below is retained only as design history.

> Version: 1.0
>
> Status: Living Document
>
> This document describes the current architecture of Atlas, the responsibilities
> of each subsystem, and the long-term direction of the platform.
>
> Unlike the ADRs, this document describes **how Atlas works today**.
> Architectural decisions are documented separately in the ADR repository.

---

# 1. Introduction

Atlas is an AI-native software engineering platform.

Its objective is not simply to parse source code.

Its objective is to understand software systems.

Atlas combines

- Static Analysis
- Semantic Analysis
- Knowledge Representation
- AI Reasoning

into one coherent platform.

---

# 2. High-Level Architecture

```

```
                     Repository
                          │
                          ▼
                Workspace Discovery
                          │
                          ▼
                 Project Identification
                          │
                          ▼
                  Language Analyzer
             (Java / Python / ...)
                          │
                          ▼
                 Semantic Extraction
                          │
                          ▼
                 Semantic Document
                          │
                          ▼
                 Semantic Snapshot
                      (.ass file)
                          │
                          ▼
               AI Context Collection
                          │
                          ▼
                  Prompt Builder
                          │
                          ▼
                     LLM Provider
                          │
                          ▼
                 AI Generated Output
```

```

---

# 3. Core Layers

Atlas is composed of several logical layers.

```

```
+--------------------------------------------------------+
|                     CLI / API                          |
+--------------------------------------------------------+

+--------------------------------------------------------+
|                  AI Services                           |
| Explain • Ask • Review • Patch • Chat                 |
+--------------------------------------------------------+

+--------------------------------------------------------+
|             Context & Knowledge Layer                  |
| Semantic Snapshots • Memory • Retrieval               |
+--------------------------------------------------------+

+--------------------------------------------------------+
|               Semantic Analysis Layer                  |
| Java • Python • Kotlin • ...                          |
+--------------------------------------------------------+

+--------------------------------------------------------+
|               Parsing & AST Layer                      |
+--------------------------------------------------------+

+--------------------------------------------------------+
|                    Source Code                         |
+--------------------------------------------------------+
```

```

---

# 4. Repository Analysis Pipeline

The current analysis workflow follows this sequence.

```

```
Repository

↓

Workspace Scanner

↓

Project Discovery

↓

Language Detection

↓

AST Generation

↓

Semantic Analysis

↓

SemanticDocument

↓

Semantic Snapshot (.ass)

↓

AI Context
```

```

---

# 5. Current Components

## Workspace

Responsible for discovering repositories and projects.

Responsibilities

- locate projects
- detect build systems
- identify languages
- organize workspace

---

## Parser

Transforms source code into AST structures.

Responsibilities

- lexical analysis
- syntax analysis
- error recovery

---

## Semantic Analyzer

Converts syntax into semantic meaning.

Responsibilities

- symbol resolution
- type inference
- inheritance
- method resolution
- scopes
- semantic relationships

Current implementation

Java

Future

Python

Rust

Go

TypeScript

---

## SemanticDocument

Current central semantic model.

Contains

- symbols
- types
- diagnostics
- metadata

Current limitation

Document-oriented.

Potential future evolution

Semantic Graph.

---

## Snapshot Persistence

Responsible for storing semantic information.

Current format

.ass

Goals

Incremental

Portable

Versioned

Deterministic

---

## AI Context

Builds the information consumed by AI.

Responsibilities

- retrieve semantic snapshot
- enrich workspace information
- include memory
- generate prompt context

---

## AI Services

Current services

Explain

Ask

Review

Patch

Future

Architecture

Security

Performance

Documentation

Refactoring

---

# 6. Data Flow

```

```
Source Code

↓

Parser

↓

AST

↓

Semantic Analyzer

↓

SemanticDocument

↓

Snapshot

↓

Context Collector

↓

Prompt Builder

↓

LLM

↓

Response
```

```

---

# 7. Future Architecture

The current architecture is document-centric.

```

```
SemanticDocument

↓

LLM
```

```

Long-term evolution

```

```
Semantic Graph

↓

Reasoning Engine

↓

Knowledge Retrieval

↓

LLM

↓

Developer
```

```

The semantic graph becomes the source of truth.

The LLM consumes semantic knowledge rather than generating it.

---

# 8. Long-Term Knowledge Graph

Future architecture.

```

```
Repository

├── Projects

│

├── Modules

│

├── Packages

│

├── Classes

│

├── Methods

│

├── Variables

│

├── Types

│

├── Dependencies

│

├── Frameworks

│

├── APIs

│

└── Relationships
```

```

Relationships become first-class citizens.

Examples

CALLS

IMPLEMENTS

EXTENDS

ANNOTATED_BY

DEPENDS_ON

USES

OVERRIDES

THROWS

IMPORTS

REFERENCES

---

# 9. AI Architecture

Current

```

```
Prompt

↓

LLM

↓

Answer
```

```

Target

```

```
Question

↓

Semantic Graph

↓

Reasoning Engine

↓

Knowledge Retrieval

↓

Prompt Builder

↓

LLM

↓

Validated Answer
```

```

AI should reason from verified semantic knowledge.

---

# 10. Plugin Architecture

Future analyzers should be independent.

```

```
Analyzer Registry

├── Java

├── Python

├── Kotlin

├── Rust

├── Go

├── JavaScript

└── TypeScript
```

```

Benefits

Independent evolution

Simpler testing

Language isolation

Community extensions

---

# 11. AI Agent Architecture

Future Atlas services.

```

```
Developer

↓

Atlas

├── Explain Agent

├── Review Agent

├── Security Agent

├── Performance Agent

├── Documentation Agent

├── Migration Agent

└── Architecture Agent
```

```

All agents consume the same semantic graph.

---

# 12. Scalability Strategy

Atlas should scale through

Incremental Analysis

↓

Workspace Cache

↓

Parallel Processing

↓

Distributed Workers

↓

Knowledge Graph

↓

AI

Target

Enterprise repositories

Monorepositories

Millions of files

Hundreds of millions of LOC

---

# 13. Design Principles

Atlas follows these principles.

## Semantic First

Semantic correctness always has priority over AI.

---

## Deterministic

The same repository should always produce the same semantic model.

---

## Incremental

Avoid recomputation whenever possible.

---

## Explainable

Atlas should explain every conclusion.

---

## Extensible

Support new languages without redesign.

---

## Testable

Every subsystem must have automated tests.

---

## AI-Assisted

AI augments semantic analysis.

It never replaces it.

---

# 14. Roadmap Alignment

Current Generation

Semantic Analysis

↓

Next Generation

Multi-Language

↓

Knowledge Graph

↓

Reasoning Engine

↓

Engineering Agents

↓

Autonomous Engineering Platform

---

# 15. Related Documentation

Architecture Decisions

`docs/architecture/ARCHITECTURAL_DECISIONS.md`

Vision

`docs/vision/VISION.md`

Implementation Roadmap

`docs/roadmap/IMPLEMENTATION_ROADMAP.md`

Research

`docs/research/ATLAS_RESEARCH.md`

Kiro Architecture Review

`docs/architecture/KIRO_ARCHITECTURE_REVIEW.md`

---

# 16. Final Philosophy

> Atlas is not being built to answer questions about code.

> Atlas is being built to understand software systems.

Everything else—including AI, automation, security, documentation, and engineering assistance—is built on top of that understanding.
