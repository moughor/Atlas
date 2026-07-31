# PR136 Design — Impact Prediction

PR136 extends existing `ImpactAnalysisService` and Java impact services. Specialized
graphs remain authoritative; PR129 supplies canonical IDs. Changes may identify
symbols, files/projects, APIs, dependencies, or Git diff subjects resolved through
PR135.

Results separate direct semantic, transitive dependency, public API, build/project,
test, and security/operational impact. Each subject includes shortest evidence paths,
relations, depth, confidence, reason, scope, and truncation.

Reverse traversal follows configured resolved `depends_on`, ownership, inheritance,
overrides, calls, and authoritative specialized dependencies. SCCs avoid repeated
work; bounded multi-source BFS stores predecessors, not all paths. Path confidence
cannot exceed its weakest edge and decays with coverage. Missing call/composition
coverage means unknown behavioral impact.

API breaking analysis compares compatible semantic signatures and visibility. Test
impact requires resolved production-to-test or project evidence; otherwise recommend
broader scope without claiming exact tests. PR132 factors contextualize risk but do
not create reachability. Incremental keys include changed subjects, graph digest,
policy, and producer versions, invalidating reverse closure.

Tests cover direction, transitivity, cycles, overrides, API signatures, unknown calls,
tests, multiple roots, ordering, incremental execution, serialization, existing API
compatibility, JUnit, and million-edge graphs. Runtime reflection, deployment
topology, consumer repositories, and probabilistic failures are deferred.
