# PR150 — Provenance-Aware Architecture Dependency Topologies

Architecture Intelligence publishes build/module and source/import dependency
topologies as separate evidence classes.

## Evidence classes

- A **build dependency** is a declared module/build availability relationship
  represented by a canonical project-to-project depends_on edge. Architecture
  detection consumes that edge; it does not reparse Maven or infer dependencies
  from names.
- An **import dependency** is an observed static source relationship represented
  by a cross-project imports edge.
- **Corroboration** means that independent build and import evidence supports the
  same directed project pair. BUILD_ONLY, IMPORT_ONLY, and CORROBORATED describe
  evidence overlap, not architecture-pattern confidence.

None of these evidence classes alone proves runtime communication. Call,
runtime, and deployment relationships require their own producers and are not
introduced by PR150.

## Compatibility

The existing dependency_directions, dependency_cycles, and dependency_analysis
fields retain their PR128 import-derived semantics. Pattern findings and
confidence are unchanged. The build and import topology objects and their pair
classifications are additive fields in the existing architecture schema
version 1. Semantic-snapshot readers and downstream consumers select known keys
and tolerate this additive data.

Java-specific type relationships supplied through the optional
JavaArchitectureGraph remain available through the legacy direction field. They
are not projected into the new project topology because they do not carry
canonical source and target project identities.

## Cycle separation

Build cycles and import cycles are computed independently. Opposing directions
from different evidence classes do not manufacture a mixed-evidence cycle.
Legacy dependency_cycles remains the PR128 import-derived result.

The normal workspace production path still constructs a scheduling
DependencyGraph before Architecture Intelligence runs. That graph rejects
cyclic project dependencies, so a build cycle cannot currently reach the
architecture detector through normal analysis. PR150 does not change workspace
scheduling. A later capability may establish a pre-scheduling evidence path if
Atlas needs to report declared build cycles without accepting them for
execution.
