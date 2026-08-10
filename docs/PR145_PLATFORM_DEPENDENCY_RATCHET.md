# PR145 Atlas Runtime Dependency Ratchet

## Outcome

PR145 removes the remaining Atlas runtime import cycle and adds a deterministic
test-only dependency ratchet. It changes one production import and introduces
no package, runtime abstraction, public API, schema, serializer, persistence
behavior, CLI behavior, or third-party dependency.

`moughorai.prompts.semantic` now imports `WorkspaceSemanticContext` from its
canonical owner, `moughorai.semantic_snapshot.context`, rather than through the
legacy `moughorai.ai_context` package facade.

## Evidence

The post-PR144 runtime graph contained one strongly connected component:

```text
moughorai.prompts.semantic
  -> moughorai.ai_context
  -> moughorai.ai_context.collector
  -> moughorai.repository_report
  -> moughorai.repository_report.selection
  -> moughorai.prompts
  -> moughorai.prompts.semantic
```

The first edge existed only because `prompts.semantic` requested an already
compatible class through an eager package facade. PR144 had established
`semantic_snapshot.context` as the canonical class owner and retained the old
paths as identity-preserving compatibility exports.

The PR145 graph inventory reports:

| Measurement | Result |
| --- | ---: |
| Production Python modules | 535 |
| Statically resolvable runtime edges | 1,441 |
| Imports classified as typing-only | 3 |
| Runtime cyclic strongly connected components | 0 |

A clean interpreter imported 197 Atlas modules through
`moughorai.prompts.semantic` before the correction. The corrected import loads
56. It does not load `moughorai.ai_context`,
`moughorai.ai_context.collector`, or `moughorai.repository_report`. Module
counts are observations, not performance thresholds.

## Dependency ratchet

The ratchet is implemented only in the PR145 test module. It:

- inventories production modules in deterministic path order;
- parses Python using BOM-safe UTF-8 decoding;
- resolves absolute and relative imports to local Atlas modules;
- treats imports inside functions as runtime edges;
- recognizes literal `__import__` and `importlib.import_module` targets;
- classifies imports under `TYPE_CHECKING` separately; and
- applies a deterministic strongly connected component calculation to the
  runtime graph.

Variable runtime imports, including plugin module names supplied by manifests,
cannot be enumerated statically. They remain governed by their existing runtime
validation and tests. The ratchet makes no claim to analyze arbitrary computed
import targets.

The typing-only `policy_packs.models` reference to
`policy_packs.resolution` is not a runtime edge. It is reported separately and
is not changed by PR145.

## Compatibility

The established compatibility identity remains true:

```python
moughorai.ai_context.WorkspaceSemanticContext is \
    moughorai.semantic_snapshot.context.WorkspaceSemanticContext
```

The prompt module therefore receives the identical class object from the
canonical import. PR145 changes no constructor, supported import path, public
facade, prompt template, snapshot field, snapshot byte, checksum, identifier,
renderer, command, or persisted format.

## Scope exclusions

PR145 does not:

- move or create packages;
- promote context, evidence, graph, measurement, serialization, persistence,
  CLI, or plugin code into the platform kernel;
- implement an architectural contract or Architectural Drift; or
- implement Benchmark Intelligence, hardware intelligence, HWBOT, or AI OC.

## Required gates

The implementation is accepted only when the focused PR145 tests, PR144
platform-boundary tests, PR109 prompt tests, PR111 snapshot tests, PR105 public
API tests, unified CLI tests, full regression suite, compile validation, and
Git whitespace validation all pass.
