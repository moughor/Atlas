# Atlas Semantic Pass Pipeline

## Intended execution order

1. Parse Java syntax and construct scopes.
2. Resolve local symbols.
3. Run variable type inference.
4. Run expression type inference when a reusable expression type table is required.
5. Run statement type checking.
6. Run flow-sensitive definite-assignment analysis.
7. Run specialized services as required.

## Expression and statement typing contract

Statement type checking currently invokes `infer_expression_type()` directly.
It is self-contained and **must not be scheduled** immediately after expression
inference merely to obtain statement diagnostics, because that repeats work and
may duplicate diagnostics.

## Flow analysis contract

`FlowState` is mutable. Independent branches must receive copies. Prefer the
structured branch and loop helpers, which copy and merge states correctly.
Flow errors are exposed as standard diagnostics through
`FlowState.standard_diagnostics`.
