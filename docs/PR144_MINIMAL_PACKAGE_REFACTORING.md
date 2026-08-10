# PR144 Minimal Package Refactoring

## Objective

Establish the first enforceable Atlas platform boundary through two demonstrated
dependency corrections, without changing any public behavior or creating a
general-purpose framework.

PR144 makes `moughorai.platform.safety` the canonical owner of the existing
domain-neutral absolute-path checks. It also makes
`moughorai.semantic_snapshot.context` the canonical owner of
`WorkspaceSemanticContext`, removing the snapshot package's reverse dependency
on `ai_context`.

## Platform boundary rule

`moughorai.platform` exists only for code that is:

1. domain-neutral;
2. free of Repository Intelligence concepts;
3. free of Benchmark Intelligence concepts;
4. free of CLI concepts;
5. free of persistence concepts; and
6. expected to remain reusable across multiple Atlas intelligence domains.

Any future addition must justify why it cannot remain inside an existing domain
package. PR144 admits only the already reused, pure safety functions. Measurement,
evidence, graph, workspace, snapshot, plugin, renderer, CLI, and persistence
abstractions remain outside the platform package.

## Production manifest

Added:

- `moughorai/platform/__init__.py`
- `moughorai/platform/safety.py`
- `moughorai/semantic_snapshot/context.py`

Compatibility forwarders:

- `moughorai/repository_report/safety.py` re-exports the exact function objects
  from `moughorai.platform.safety`.
- `moughorai/ai_context/models.py` re-exports the exact class object from
  `moughorai.semantic_snapshot.context`.

Internal imports changed:

- the 19 direct consumers of `moughorai.repository_report.safety`;
- the two relative safety consumers in `repository_report`; and
- `semantic_snapshot.models` and `semantic_snapshot.store`, which now import
  their context type from their own package.

`moughorai.semantic_snapshot.__init__` now exposes the canonical context class.
The existing `moughorai.ai_context` export is unchanged.

## Compatibility contract

- Both old safety imports resolve to the same function objects as the platform
  imports.
- Both old context imports resolve to the same class object as the snapshot
  import.
- Function signatures and behavior are unchanged.
- Context construction, immutability, dictionary conversion, and canonical JSON
  behavior are unchanged.
- Semantic snapshot schema, dictionary shape, identifiers, checksums, serialized
  bytes, archive behavior, and `latest.ass` behavior are unchanged.
- Public API, CLI commands, renderers, plugin contracts, and package discovery
  are unchanged.

The forwarding modules are compatibility boundaries, not duplicate
implementations.

## Dependency effect

Before PR144, 19 production files imported the repository-report safety module
by absolute path and two repository-report files imported it relatively. After
PR144, those 21 consumers import `moughorai.platform.safety` and only the
compatibility module points from the old path to the new owner.

Before PR144, two `semantic_snapshot` modules imported `ai_context`. After
PR144, `semantic_snapshot` has no `ai_context` import; `ai_context.models`
points to the domain-local snapshot context owner for compatibility.

No platform-to-domain dependency is introduced.

## Deliberately unchanged

- No existing package or module is renamed.
- No package is moved under a speculative `domains` hierarchy.
- `moughorai.measurement` remains in place.
- Repository evidence, graphs, snapshots, workspace services, plugin SDKs,
  renderers, persistence, and CLI composition remain with their existing owners.
- The six approved platform architecture documents remain unchanged.
- Atlas AI OC remains frozen and is neither imported nor copied.

Architectural Drift and Benchmark Intelligence remain out of scope.
