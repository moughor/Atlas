# PR101 — Semantic Table Builders

`TypeTableBuilder` and `SymbolTableBuilder` provide mutable accumulation during
analysis and freeze results into the existing immutable tables. Legacy
`with_type()` and `with_symbol()` behavior remains unchanged.

`VariableTypeInferencePass` now creates builders from the document's existing
tables, records every declaration during one traversal, and freezes each table
once at the pass boundary. This removes repeated whole-table copies for methods
containing many local declarations.

Run the benchmark from the repository root:

```text
python -m benchmarks.benchmark_semantic_tables --entries 5000 --repeats 3
```

On 2026-07-29, the measured best samples were 1.707386 seconds for repeated
immutable updates and 0.004469 seconds for builders: a 382.01× speedup. Timing
is reported rather than enforced as a unit-test threshold.

Builders validate keys and values on insertion. `build()` always returns a
detached immutable snapshot, so later builder changes cannot mutate previously
built tables.
