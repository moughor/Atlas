## Lessons learned

- A canonical graph model is not sufficient unless the normal analysis
  pipeline supplies each advertised relation.
- Existing specialized graphs contain valuable evidence, but their presence
  does not make that evidence available in semantic snapshots automatically.
- Global-symbol metadata is an effective compatibility boundary for
  source-free relations that must survive persistence and recovery.
- Exact serialization round-trips require preserving semantic fields without
  redundantly copying them into metadata.
- Snapshot-size measurements must accompany graph enrichment. Compact optional
  fields reduced the final JUnit overhead substantially.
- Conservative omission is preferable to emitting plausible but unsupported
  relationships.

## Remaining limitations

- Canonical call edges are not populated because the normal language frontends
  do not yet provide normalized, resolved call sites.
- Composition is not populated because a typed field or dependency alone does
  not prove lifecycle ownership.
- Java override edges require `@Override`, an internally resolved ancestor, and
  an exact method name and parameter signature.
- Java imports are not currently persisted in global-symbol metadata.
- Python inheritance is limited to bases that resolve uniquely to internal
  symbols.
- Concrete build targets and tasks are not discovered; only build systems are
  represented.
- Specialized graph APIs remain separate from the repository-level canonical
  graph.
- JUnit showed a 12.69% total snapshot increase and a 21.87% semantic-graph
  increase, so larger workspaces still require monitoring.

## Future extension points

- Add language-frontend contracts for normalized semantic relations with
  resolution status and evidence.
- Adapt resolved call graphs into canonical method-to-method call edges.
- Add a lifecycle-aware composition producer rather than interpreting every
  field reference as composition.
- Persist resolved Java import relationships through the existing symbol
  boundary.
- Extend override resolution for external classpaths, generic erasure,
  covariant returns, and unannotated implementations.
- Add task-level adapters for Gradle, Maven, npm, Cargo, and other build tools.
- Introduce indexed or lazy graph serialization for very large snapshots.
- Add adapters from specialized Java, persistence, injection, REST, and
  transaction graphs without replacing their existing APIs.

## Recommendations for PR130

- Consume the canonical graph and existing specialized evidence rather than
  creating another repository graph.
- Require a confidence score, participating symbols, and traceable evidence for
  every detected design pattern.
- Distinguish patterns that can be proven with currently populated relations
  from patterns that require call or composition evidence.
- Do not infer Strategy, Observer, Command, Chain of Responsibility, State, or
  Template Method solely from class or method names.
- Use inheritance and verified override edges where structurally relevant, but
  account for their documented language and resolution limits.
- Treat missing call and composition edges as unavailable evidence, not
  negative evidence.
- Keep detectors independently testable and deterministic.
- Add adversarial tests for similarly named classes that do not participate in
  the claimed pattern.
- Measure any additional snapshot data before publication.

## Assumptions made

- `KnowledgeGraph` is canonical for repository-level semantic relationships,
  while specialized graphs remain authoritative for their detailed domains.
- A resolved internal Java extends or implements edge is reliable inheritance
  evidence.
- A Python base is reliable only when it resolves uniquely to an internal type.
- An internal Java method annotated `@Override` with a matching ancestor
  signature is sufficient conservative override evidence.
- Workspace configuration is authoritative for project dependencies.
- Declared dependency identity requires ecosystem, name, version, and scope.
- A detected build tool is a build system, not a concrete target.
- Source-free metadata may contain symbol names, dependency coordinates, paths,
  scopes, and evidence identifiers, but not raw source text.

## Intentionally deferred work

- Canonical call-edge production.
- Canonical composition-edge production.
- Concrete build-target and task discovery.
- Speculative or name-only relationship inference.
- Full convergence or removal of specialized graph representations.
- Graph-database persistence and distributed graph storage.
- Lazy loading, partitioning, and compression beyond compact JSON fields.
- External classpath resolution for inheritance and overrides.
- Cross-language override and dynamic-dispatch resolution.
- PR130 design-pattern implementation.
