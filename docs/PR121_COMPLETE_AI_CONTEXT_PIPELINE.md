# PR121 — Complete AI Context Pipeline Integration

PR121 makes the production `atlas analyze` path return semantic results instead
of placeholder file-count dictionaries. Each project run now carries an
immutable `SemanticDocument`.

## Analysis flow

1. Included files are resolved deterministically and exclusions are applied.
2. Java compilation units are parsed with the Atlas Java declaration parser.
3. Java symbols are promoted into the global symbol model.
4. Parse failures become `ATLAS-JAVA-PARSE` diagnostics.
5. The project result is a source-free `SemanticDocument`.
6. The semantic context collector consumes those artifacts directly.
7. A successful workspace run is recorded in history and published as the
   latest Atlas Semantic Snapshot (`.atlas/ass/latest.ass`).

The collector retains its compatibility path for custom and legacy analyzers.
When an analyzer does not provide global symbols, the collector indexes project
Java sources as before.

## Persistence and recovery

Semantic results use the versioned `atlas.semantic-document.v1` durable form.
It stores metadata, diagnostics, and global symbols, but never raw source or
runtime AST objects. Recovery reconstructs a `SemanticDocument` suitable for
context publication without rerunning completed projects.

Values produced by older or custom analyzers pass through the codec unchanged.
Workspace reports and analysis history retain the former deterministic summary
shape (`project`, `files`, and `dependencies`) for the default analyzer.

## Failure behavior

Project parse diagnostics do not turn an otherwise completed workspace run into
an infrastructure failure. A failed or blocked project run still prevents
snapshot publication. Existing snapshots therefore remain untouched when the
workspace execution itself is unsuccessful.

## Runtime discovery hardening

Automatic workspace discovery and project file enumeration skip hidden tool
trees and standard generated directories. Inaccessible directories are ignored
locally instead of failing the entire workspace. Discovery, fingerprinting,
watch mode, fallback collection, and semantic analysis share the same
deterministic file-selection rules.
