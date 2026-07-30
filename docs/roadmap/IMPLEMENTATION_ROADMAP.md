# Atlas 2.x Implementation Roadmap

## Status

This document is the official Atlas roadmap. It replaces the previous
PR122–PR151 plan and supersedes its PR127–PR151 numbering.

PR122–PR126 are complete. PR127–PR151 are Atlas 2.x consolidations and
integrations: they extend existing components, preserve public compatibility,
and must not create duplicate engines or models.

Before every future PR, the implementation record must state:

- what already exists;
- what can be reused;
- what is missing;
- what will be extended;
- the regression risks.

A component may be replaced only when a demonstrated limitation prevents a
compatible extension.

## Vision

Atlas is evolving from a semantic parser into an AI-first software engineering
intelligence platform capable of understanding repositories like a senior
software architect.

The objective is not merely to parse source code. Atlas must understand
architecture, dependencies, design decisions, quality, evolution, and
engineering intent.

## Current Status — Atlas Generation 1 Complete

- Java Semantic Analyzer
- Python Semantic Analyzer
- Analyzer Registry
- Project-Scoped Symbol Identities
- Cross-Language Workspace
- Dependency Intelligence
- Incremental Analysis
- Workspace Model
- AI Explain
- Ollama Integration
- 3400+ automated tests
- JUnit workspace validated successfully: **41 discovered projects, including
  the root `junit-team` aggregator**

## Legacy Roadmap Capability Migration

No planned capability from the superseded roadmap is discarded.

| Previous capability | Atlas 2.x location |
|---|---|
| Framework Detection v2 | PR127 repository inventory and PR128 architecture evidence; existing framework detectors are extended |
| Repository Summary | PR127 |
| Architecture Detection | PR128 |
| Knowledge Graph | PR129 |
| Design Pattern Detection | PR130 |
| Dead Code Detection | PR131 |
| Hotspot Ranking | PR132 Risk & Hotspot Analysis |
| AI Repository Report | PR133 |
| Explain Class / Explain Dependency | PR134 Explain Anything |
| Semantic Search | PR135 |
| Impact Prediction | PR136 |
| Refactoring Suggestions | PR137 |
| AI Security Review | PR138 |
| Interactive Chat | PR139 |
| Git-aware change analysis | PR140 Change Review |
| Complexity Heatmap | PR132 risk inputs and PR142 Technical Debt Engine |
| Repository Evolution | PR141 |
| Technical Debt | PR142 |
| Architectural Drift | PR143 |
| AI Quality Gates | PR144 |
| Shared Knowledge / Knowledge Persistence | PR145 and PR148 |
| Parallel Analysis | PR146 consolidation of the existing concurrent executor |
| Workspace Cache v2 | PR147 consolidation of existing persistence and cache layers |
| IDE Integration | PR149 consolidation of existing IDE assistant protocols |
| Atlas Server | PR150 |

# Milestone A — Repository Intelligence

## PR127 — Repository Summary Engine

### Goal

Produce a deterministic repository model independent of any LLM.

### Deliverables

- Repository metadata
- Project inventory
- Language distribution
- Build systems
- Framework detection
- Entry points
- Module hierarchy
- Production versus test code
- Generated source detection
- Dependency summary

### Acceptance Criteria

- Deterministic and reproducible
- Machine-readable
- AI consumes structured repository metadata instead of raw files
- Existing project inventory, framework detection, workspace, and dependency
  intelligence components are extended rather than duplicated

## PR128 — Architecture Detection

### Goal

Automatically identify repository architecture.

### Detect

- Layered Architecture
- Modular Monolith
- Microservices
- Hexagonal Architecture
- Clean Architecture
- CQRS
- Event-Driven Systems
- Plugin Architectures

### Additional Analysis

- Dependency direction
- Cyclic dependencies
- Bounded contexts
- Ports and adapters
- Infrastructure layers

### Acceptance Criteria

Every architectural conclusion includes traceable semantic evidence.

## PR129 — Knowledge Graph

### Goal

Consolidate existing graph components into a unified semantic graph.

### Nodes

- Repository
- Workspace
- Project
- Package
- Module
- Type
- Method
- Field
- Dependency
- Framework
- Build Target

### Edges

- Imports
- Inheritance
- Composition
- Calls
- Overrides
- Dependencies
- Ownership

### Acceptance Criteria

Everything becomes queryable through semantic relationships without replacing
compatible graph APIs.

## PR130 — Design Pattern Detection

Detect Strategy, Factory, Builder, Observer, Adapter, Decorator, Composite,
Command, Chain of Responsibility, State, and Template Method.

Each result includes a confidence score, semantic evidence, and participating
classes. Detection never relies solely on LLM inference.

## PR131 — Dead Code & Reachability

Differentiate unreachable, unused, reflection-discovered, framework-managed,
Service Loader, and annotation-generated code. Output confidence rather than
unsupported binary decisions.

## PR132 — Risk & Hotspot Analysis

Combine complexity, fan-in, fan-out, repository churn when Git evidence is
available, size, ownership, and test density. Produce repository risk rankings
and retain the previous hotspot and complexity-heatmap objectives.

## PR133 — AI Repository Report

Generate an executive summary, architecture overview, strengths, weaknesses,
technical debt, risks, and recommendations. Every conclusion references
semantic evidence.

# Milestone B — AI Engineering Assistant

## PR134 — Explain Anything

Explain a class, method, package, project, dependency, framework, or repository.
Consolidate the existing explain-class and explain-dependency capabilities.

## PR135 — Semantic Search

Provide intent-based repository search for concepts such as authentication,
REST endpoints, SQL queries, controllers, services, scheduling, and caching.

## PR136 — Impact Prediction

Predict affected modules, APIs, tests, dependencies, and breaking changes by
extending the existing impact-analysis graph.

## PR137 — Refactoring Advisor

Suggest extractions, simplifications, dependency cleanup, package moves, and
modularization with rationale and estimated impact.

## PR138 — Security Intelligence

Consolidate existing security analyzers and detect secrets, SQL injection, weak
cryptography, path traversal, SSRF, XSS, unsafe deserialization, and unsafe
reflection. Every finding includes semantic evidence.

## PR139 — Interactive Engineering Chat

Provide repository-aware architectural conversation grounded in persisted
semantic data.

## PR140 — Change Review

Analyze Git diffs and produce impact analysis, architectural concerns, test
recommendations, risk assessment, and migration advice.

# Milestone C — Engineering Intelligence

## PR141 — Repository Evolution

Track semantic evolution across commits.

## PR142 — Technical Debt Engine

Rank technical debt by engineering impact and reuse PR132 complexity and risk
evidence.

## PR143 — Architectural Drift

Detect divergence from intended architecture.

## PR144 — Quality Gates

Extend the existing quality-gate and CI systems with semantic validation.

## PR145 — Knowledge Persistence

Consolidate semantic snapshots, history, AI memory, and persisted repository
knowledge.

# Milestone D — Enterprise

## PR146 — Parallel Analysis

Consolidate and scale the existing concurrent workspace execution architecture.

## PR147 — Workspace Cache v2

Extend existing persistence, incremental state, and recovery for durable
cross-session reuse.

## PR148 — Distributed Knowledge Store

Provide shared semantic storage while preserving local deterministic behavior.

## PR149 — IDE Integration

Consolidate existing IDE assistant protocols for VS Code, JetBrains, and Visual
Studio.

## PR150 — Atlas Server

Provide a REST API, MCP interface, remote semantic analysis, and multi-user
operation.

## PR151 — Atlas Platform 3.0

Deliver continuous repository intelligence and autonomous engineering
assistant capabilities.

# Success Criteria

Atlas should be able to:

- analyze repositories with millions of lines of code;
- support multi-language workspaces with one semantic model;
- produce deterministic semantic snapshots;
- explain architecture using traceable evidence;
- continue after isolated failures;
- build and query repository knowledge graphs;
- predict software change impact;
- produce evidence-backed engineering reports;
- operate as an AI software architect rather than a code summarizer.
