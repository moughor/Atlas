# PR130 Design — Design Pattern Detection

## Architecture

`PatternDetectionService` queries the PR129 canonical `KnowledgeGraph` and existing
authoritative specialized graphs. It never parses source or creates another graph.
Findings contain pattern, canonical participants/roles, scope, language, confidence,
evidence IDs, limitations, and detector version, sorted deterministically. Java is
initially supported where existing typed producers provide evidence; cross-language
findings require resolved canonical edges. Missing `calls`/`composition` means
insufficient, never inferred. Name-only hints score zero.

## Pattern contracts

### Strategy

- Purpose/nodes: abstraction, 2+ implementations, client.
- Edges/passes: inheritance, ownership, resolved client usage/calls from semantic and
  call producers.
- Minimum/confidence: two implementations plus one client; grows with distinct
  resolved usages. Inheritance alone is insufficient.
- Negative/false positives/adversarial: marker interfaces, one implementation,
  test doubles, or `*Strategy` names.
- Limits/query/tests/complexity: Java initially; intersect reverse inheritance and
  client neighborhoods in `O(V+E)`. Test runtime selection and naming traps.

### Factory

- Purpose/nodes: creator, product abstraction, concrete products.
- Edges/passes: return types, constructor/factory calls, inheritance.
- Minimum/confidence: creator produces 2+ compatible concrete products.
- Negative/adversarial: `create` names, single constructors, builders, DI containers,
  fixtures, and deserializers without resolved creation flow.
- Limits/query/tests: Java with constructor-call/return evidence; join creator calls to
  ancestry linearly. Test overloads and static factories.

### Builder

- Purpose/nodes: builder, fluent members, terminal member, product.
- Edges/passes: ownership, typed returns/calls, composition when available.
- Minimum: 2+ builder-returning configuration methods and terminal distinct product.
- Negative: setters, DSLs, collectors, generated builders, name-only classes.
- Limits/query/tests: per-type `O(m)` member scan; test fluent DSL and generated scope.

### Adapter

- Purpose/nodes: adapter, target, adaptee, client.
- Edges/passes: target inheritance plus adaptee composition and delegating calls.
- Minimum: implements target and resolved translation/delegation to adaptee.
- Negative: decorators, proxies, wrappers, inheritance bridges.
- Limits/query/tests: requires reliable call/composition producer; bounded two-hop
  query. Prove no positive when those facts are absent.

### Observer

- Purpose/nodes: subject, observer abstraction/implementations, registration and
  notification members.
- Edges/passes: inheritance, collection composition, ownership, subscription and
  notification calls.
- Minimum: resolved subscription plus notification call.
- Negative: event DTOs, single callbacks, listener names, framework metadata alone.
- Limits/query/tests: Java with dispatch evidence; `O(E)` subject scans. Test real and
  name-only listeners; label framework-local scope.

### Decorator

- Purpose/nodes: component, decorator, wrapped component.
- Edges/passes: shared inheritance contract, composition, delegating calls.
- Minimum: same contract and resolved delegation of a contract operation.
- Negative: adapters, proxies, composites, inheritance-only extensions.
- Limits/query/tests: requires field identity/calls; ancestry/delegation intersection
  in `O(E)`. Test decorator versus adapter.

### Composite

- Purpose/nodes: component, leaf, composite, child collection.
- Edges/passes: inheritance, composition, ownership, recursive calls.
- Minimum: shared contract, component collection, and child operation traversal.
- Negative: arbitrary trees, AST/container types, `children` names.
- Limits/query/tests: typed collection/call evidence, cycle-safe `O(V+E)`. Test AST
  false positives and uniform operation.

### Command

- Purpose/nodes: command abstraction/implementations, invoker, receiver.
- Edges/passes: inheritance, invoker call, receiver delegation/composition.
- Minimum: 2+ commands or one with resolved invoker and receiver.
- Negative: CLI classes, request DTOs, jobs, lambdas, `execute` names alone.
- Limits/query/tests: resolved calls; bounded three-hop roles. Test CLI naming traps.

### Chain of Responsibility

- Purpose/nodes: handler contract, handlers, successor, request.
- Edges/passes: inheritance, composition, calls and control flow.
- Minimum: 2+ handlers and conditional forwarding to successor.
- Negative: always-run pipelines, linked lists, decorators, middleware metadata.
- Limits/query/tests: needs call/CFG producer; cycle-safe `O(V+E)`. Test pipeline
  versus conditional forwarding.

### State

- Purpose/nodes: context, state abstraction, 2+ states, state field/transitions.
- Edges/passes: inheritance, composition, delegation calls, assignment/data flow.
- Minimum: two states, context delegation, one resolved transition.
- Negative: Strategy without transition, enum switches, status DTOs.
- Limits/query/tests: Java with assignment evidence. Test State/Strategy ambiguity and
  retain conflict evidence.

### Template Method

- Purpose/nodes: base, concrete template method, hooks, subclasses.
- Edges/passes: inheritance, ownership, template-to-hook calls, overrides.
- Minimum: base skeleton calls overridable hook and subclass overrides it.
- Negative: ordinary inheritance, interfaces, callbacks, unrelated overrides.
- Limits/query/tests: join override edges to base calls in `O(E)`. Test true skeleton
  and missing-call coverage.

## Common behavior

Confidence follows `COMMON_CONFIDENCE_MODEL.md`; evidence follows
`COMMON_EVIDENCE_MODEL.md`. State/Strategy, Adapter/Decorator, and
Composite/Decorator may coexist only with independent evidence and explicit conflict
limitations. Generated/test/sample findings remain scoped.

Tests use production paths, golden/adversarial cases, shuffled order, exact round-trip,
incremental invalidation, JUnit, Atlas self-analysis, and million-edge benchmarks.
Unsupported languages, unresolved dynamic dispatch, reflection, and LLM-only pattern
classification are intentionally deferred.
