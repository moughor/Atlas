## PR67 — Workspace & Project Model

- Added deterministic multi-project workspace loading, discovery, dependency planning, impact analysis, and content snapshots.

# Changelog

## Atlas Sprint 3 - PR #7

### Added
- Deterministic method and constructor overload resolution.
- Exact matching, primitive widening, boxing/unboxing, Object fallback, and varargs ranking.
- Static-versus-instance context validation.
- Diagnostics for missing, incompatible, ambiguous, and context-invalid invocations.
- Immutable `MethodSignature` and `MethodResolutionResult` APIs.

### Validation
- Focused method-resolution tests.
- Complete regression suite required before commit and tag.
## Atlas Sprint 3 - PR #6

### Added
- Statement and control-flow type checking for blocks, local declarations, returns, throws, `if`, and `while`.
- Boolean-condition validation and full-expression declaration compatibility checks.
- Return-type checking using an explicit pass option or `expected_return_type` document metadata.
- Loop-context validation for `break` and `continue`.
- Basic unreachable-statement warnings after non-completing statements.
- `StatementTypeCheckingPass` and reusable `check_statement_types` API.

### Validation
- Focused statement-type-checking tests.
- Complete regression suite required before commit and tag.
## Atlas Sprint 3 - PR #5

### Added
- Expression type inference for literals, names, unary, binary, assignment, cast, object creation, array access, and conditional expressions.
- Java numeric promotion, boolean-result operators, and String concatenation.
- Expression diagnostics and immutable `TypeTable` integration.
- `ExpressionTypeInferencePass` using variable symbols produced by PR #4.

### Validation
- Focused expression-inference tests.
- Complete regression suite required before commit and tag.
## Atlas Sprint 3 - PR #4

### Added
- Immutable `VariableSymbol` and `SymbolTable` semantic models.
- Explicit and `var` local-variable type inference.
- Java primitive widening compatibility.
- Variable initializer mismatch diagnostics.
- `VariableTypeInferencePass` integration with `SemanticDocument`.

### Validation
- Focused variable-inference tests.
- Complete regression suite required before commit and tag.

## Atlas PR8 - Generic Type Inference

- Added explicit generic method type-parameter inference.
- Added nested generic and array constraint collection.
- Added explicit type-argument validation and generic substitution.
- Added conflict, unresolved-variable, and arity diagnostics.

## Atlas PR9 - Lambda and Method Reference Typing

- Added functional-interface target descriptors.
- Added implicit and explicit lambda parameter validation.
- Added lambda return compatibility and primitive widening.
- Added static, bound, unbound, and constructor method-reference resolution.
- Added diagnostics for arity, parameter, return, ambiguity, and context mismatches.

## Atlas PR10 - Constant Folding and Compile-Time Evaluation

- Added a reusable compile-time constant value model and expression evaluator.
- Added Java-style integer promotion, overflow, division, remainder, shifts, and unsigned shifts.
- Added unary, arithmetic, bitwise, boolean, comparison, and string-concatenation folding.
- Added primitive constant casts and named constant propagation.
- Added explicit errors for non-constant expressions and integral division by zero.

## Atlas PR11 - Flow-Sensitive Analysis and Definite Assignment

- Added a reusable variable-state lattice for definite and possible assignment.
- Added branch joins that ignore terminated paths.
- Added conservative while-loop and mandatory do/while-loop transfer rules.
- Added final-variable single-assignment validation.
- Added unassigned-read, duplicate-declaration and unreachable-statement diagnostics.
- Added a semantic-pass facade and focused regression coverage.

## Atlas PR11.5 - Architecture Cleanup

- Consolidated primitive widening conversions into `semantic.types.relations`.
- Added stable `ATLAS-FLOW-*` codes and a standard diagnostic adapter.
- Documented semantic pass ordering and the mutable flow-state contract.
- Added focused architectural regression tests.

## Atlas PR12 - Java Pattern Matching Foundations

- Added an AST-independent Java type-pattern semantic model.
- Added true-edge and false-edge scopes for pattern variables.
- Added guarded `&&`, conservative `||`, and negation flow composition.
- Added duplicate, invalid-name, primitive-pattern, and compatibility diagnostics.
- Added standard `Diagnostic` conversion for pattern errors.
- Added optional class-hierarchy compatibility checks and a facade API.

## Atlas PR13 - Sealed Hierarchies and Exhaustive Switches

- Added parser-independent sealed, final, and non-sealed type declarations.
- Added a validated hierarchy graph with permits checks and cycle detection.
- Added recursive finite-leaf discovery for nested sealed hierarchies.
- Added switch exhaustiveness analysis for type patterns and default cases.
- Added duplicate-case and type-pattern dominance diagnostics.
- Added standard Diagnostic conversion for hierarchy and switch errors.
- Added 24 focused regression tests for hierarchy and switch semantics.

## Atlas PR14 - Java Record Patterns

- Added parser-independent record declarations and recursive record-pattern nodes.
- Added typed, var, unnamed, and nested component patterns.
- Added recursive decomposition validation and binding extraction.
- Added generic record component substitution.
- Added component-count, type-compatibility, duplicate-binding, nested-pattern,
  and unsupported-decomposition diagnostics.
- Added standard Diagnostic conversion for record-pattern errors.
- Added 28 focused regression tests for Java record-pattern semantics.

## Atlas PR15 - Control Flow Graph Infrastructure

- Added parser-independent basic blocks, typed flow edges, and CFG diagnostics.
- Added structured CFG construction for sequences, branches, loops, break, continue, return, and throw.
- Added reachability, predecessor/successor queries, reverse post-order, and dominator computation.
- Added 41 focused regression tests.

## Atlas PR16 - Flow-Sensitive Nullability Analysis

- Added a null-state lattice and environment merging over Atlas CFGs.
- Added null-check branch refinement, loop fixpoint propagation, assignment transfer functions, and dereference diagnostics.
- Added 40 focused regression tests.

## Atlas PR17 - Reachability and Dead-Code Analysis

- Added conservative CFG reachability with constant-condition pruning.
- Added dead-block and dead-statement diagnostics.
- Added guaranteed-return and missing-return analysis.
- Added invalid break/continue validation and infinite-loop detection.
- Added 52 focused regression tests.