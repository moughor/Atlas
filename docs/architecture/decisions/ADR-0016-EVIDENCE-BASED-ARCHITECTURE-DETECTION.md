# ADR-0016 Evidence-Based Architecture Detection

## Status

Accepted

## Decision

Architecture detection is a post-analysis intelligence layer over the
repository summary and published semantic graph. Pattern detectors are
independent strategies returning confidence and traceable evidence.

The existing `JavaArchitectureGraph` remains the Java-specific detailed graph
and may enrich the report. PR128 does not create or own a new canonical graph;
PR129 remains responsible for graph consolidation.

## Consequences

Architecture conclusions are deterministic, source-free, explainable, and
available to downstream AI consumers. Naming-based inference remains visible
as evidence rather than being presented as certainty.
