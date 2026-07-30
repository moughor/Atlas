# PR122 — Python Semantic Analyzer

PR122 adds deterministic Python semantic extraction to the production
`atlas analyze` pipeline.

## Extracted knowledge

Atlas parses Python with the standard-library `ast` module and records:

- modules and imports, including relative imports;
- classes, nested classes, functions, methods, and nested functions;
- decorators and asynchronous functions;
- module and class globals;
- dataclass and enum classification;
- parameter, variable, and return annotations;
- module, class, and function docstrings.

Modules use package symbols, classes use type symbols, functions use method
symbols, and globals use field symbols. Python annotations are also published
through the existing immutable `TypeTable`.

## Determinism and safety

Files, modules, diagnostics, and symbols are sorted by stable keys. Source text
is never persisted in analysis recovery data or semantic snapshots. Syntax and
decoding failures produce `ATLAS-PYTHON-PARSE` diagnostics without discarding
valid modules from the same project.

## Production integration

`SemanticProjectAnalyzer` analyzes Java and Python sources in the same project.
It reports `java`, `python`, `mixed`, or `workspace` as appropriate. The
analyzer-registry abstraction remains intentionally deferred to PR123.

The PR121 recovery codec now preserves deterministic semantic type tables, so a
reused Python project republishes the same AI context without reanalysis.
