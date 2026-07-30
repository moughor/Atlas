# ADR-0015 Repository Summary Composition

## Status

Accepted

## Context

Atlas already had mature project inventory, technology detection, workspace,
framework, and dependency components. A separate repository scanner would
duplicate behavior and create inconsistent classifications.

## Decision

The repository summary is a composition layer. It reuses project file
selection, classification, statistics, technology detection, Maven framework
evidence, and dependency intelligence. Its immutable output is published in
semantic snapshots.

Nested projects own their most specific source trees. Conclusions are limited
to deterministic evidence; no LLM or build tool is executed.

## Consequences

Existing APIs remain intact, summary output is reproducible, and future
repository-intelligence PRs receive one machine-readable foundation.
