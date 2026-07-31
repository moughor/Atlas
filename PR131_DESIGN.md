# PR131 Design — Dead Code and Reachability

PR131 extends existing Java CFG reachability and repository dependency services. It
consumes the PR129 graph and authoritative call/CFG/framework evidence without
replacing them.

Each repository, project, package, type, method, and field receives `reachable`,
`unreachable`, `externally_managed`, `unknown`, or `not_analyzed`, with roots, evidence
paths, confidence, coverage, and limitations. Dead code requires `unreachable` under a
recorded closed-world scope.

Roots include configured entrypoints, executable/build metadata, exported APIs under
policy, tests when enabled, authoritative framework callbacks, and explicit roots.
Propagation uses workspace `depends_on`, ownership, inheritance, resolved type
references/construction, calls/overrides, field reads/writes, and CFG reachability.
Package/project aggregation never marks every member live.

Reflection, DI, annotations, `ServiceLoader`, serialization, generated code, native
calls, and framework lifecycle are escape categories. Structured annotations,
configuration, and service descriptors add roots or `externally_managed`; names do
nothing. Unresolved mechanisms yield unknown.

Multi-source BFS with SCC collapse is `O(V+E)` and stores predecessors, computing paths
lazily. Path confidence cannot exceed its weakest evidence. Unreachability confidence
depends on complete relevant producers, never an empty incoming list.

Existing `ReachabilityAnalyzer` retains Java CFG diagnostics; PR131 adds an optional
snapshot section with compatible deterministic round-trip. Tests cover roots,
calls/overrides, unused methods/fields/packages/projects, DI, reflection,
`ServiceLoader`, generated/framework code, cycles, unresolved calls, partial
languages, false positives, incremental invalidation, JUnit, and large graphs.
Automatic deletion, runtime tracing, native/reflection certainty, and unsupported
language dead-code claims are deferred.
