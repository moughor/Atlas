# PR137 Design — Refactoring Advisor

PR137 creates advice, never code changes, by consuming existing architecture and
dependency analysis plus PR130–PR136.

Candidate families:

- duplicate consolidation only from an authoritative structural duplicate producer;
- extract method/class from complexity, cohesion, ownership, size, and dependency
  evidence, otherwise unavailable;
- package restructuring from dependency clusters, architecture boundaries, and impact;
- dependency cleanup only with complete authoritative usage/build evidence;
- cycle breaking by reusing existing cycle findings and ranking cut edges;
- layer violations from PR128 areas and resolved direction rules.

Each candidate stores canonical subjects, evidence, operation, preconditions, expected
gain, effort, impact, confidence, limitations, and verification. Benefit combines
risk/complexity/cohesion/cycle/dependency improvements. Effort uses subject count,
public API exposure, blast radius, language support, and test coverage. Both are
shown; missing signals reduce confidence and never imply low effort.

PR136 flags blast radius, PR131 blocks deletion of unknown code, and PR130 distinguishes
intentional patterns. Overlaps/conflicts and generated/vendor/test scope are explicit.
AI only explains deterministic advice with citations.

Tests cover every family and adversarial case, intentional patterns, false cycles,
ambiguous layers, public APIs, unknown reachability, overlap, ranking, ordering,
incrementality, source-free prompts, JUnit, and performance. Generation is linear over
findings plus `O(n log k)` ranking. Automatic patches, unowned clone engines,
behavioral proofs, and cross-repository moves are deferred.
