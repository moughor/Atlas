# PR101 Release Notes

PR101 removes quadratic semantic-table construction from variable inference
by adding mutable bulk builders that freeze into the existing immutable
`TypeTable` and `SymbolTable` APIs.

All legacy update methods remain compatible. New bulk table and
`SemanticDocument` methods are additive.
