# PR122 Release Notes

PR122 adds production Python semantic analysis backed by Python's standard
library AST. Python repositories now publish modules, classes, functions,
decorators, async declarations, imports, globals, dataclasses, enums, type
annotations, and docstrings to Atlas Semantic Snapshots.

Java behavior and custom analyzer compatibility are preserved. Mixed
Java/Python projects merge their semantic facts deterministically. Recovery
persists Python symbols, diagnostics, and type tables without raw source.
