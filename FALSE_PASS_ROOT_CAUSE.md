# FALSE_PASS_ROOT_CAUSE — Atlas b21ae2c vs Independent Evaluator

## Problem Statement

Atlas candidate b21ae2c reported **14/14 context PASS** in internal verification,
but the independent evaluator reported **0/14 context FAIL**.

This document explains why the internal assertion was incorrect.

## Internal Verification Logic

The internal runner (`sygma_eval_runner.py`) uses this check:

```python
# Context selection
ctx = select_database_context(graph, story, max_hops=max(hops, 2), max_objects=60)
ctx_node_count = len(ctx.selected_nodes)
# ...
# Strict: FAIL if exceeds max_objects
ctx_pass = ctx_node_count <= 60
```

**The internal check only verifies:**
- `ctx_node_count <= 60` (budget cap)

**The internal check does NOT verify:**
- Required objects (tables/views) are present
- Required columns are present
- Required relationships (FKs, view dependencies) are present
- Required uncertainties are generated

## Independent Evaluator Contract

The independent evaluator checks the **complete** context contract:

| Criterion | Internal | Independent |
|-----------|----------|-------------|
| Nodes ≤ 60 | ✓ checked | ✓ checked |
| Required objects | ✗ NOT checked | ✓ checked |
| Required columns | ✗ NOT checked | ✓ checked |
| Required relationships | ✗ NOT checked | ✓ checked |
| Required uncertainties | ✗ NOT checked | ✓ checked |

## Root Cause

The internal verification treated "any output ≤60 nodes" as "context complete."

This is a **smoke test**, not a **completeness test**.

A smoke test proves:
- The selector runs without crashing
- The output respects the budget cap

A completeness test proves:
- The correct objects are selected
- The correct columns are included
- The correct relationships are represented
- The correct uncertainties are generated

## Evidence of Discrepancy

### Case 003 Example

**Internal result:**
- `ctx_node_count = 58`
- `ctx_pass = True` (because 58 ≤ 60)

**Independent result:**
- Objects: 0/2 FAIL (missing TB_RT_SESSION_INSTANCE, TB_RT_EXERCISE_INSTANCE)
- Columns: 0/10 FAIL
- Relationships: 0/1 FAIL
- Uncertainties: 0/1 FAIL

The selector returned 58 nodes, but **none of them were the required objects**.

## Required Fix

The internal verification must check the same contract as the independent evaluator:

```python
# After selection
result = select_database_context(graph, story, max_hops=hops, max_objects=60)

# Check COMPLETE contract:
objects_ok = all(obj in result.selected_objects for obj in expected_objects)
columns_ok = all(col in result.selected_columns for col in expected_columns)
relationships_ok = all(rel in result.selected_relationships for rel in expected_relationships)
uncertainties_ok = validate_uncertainties(result.uncertainties, expected_uncertainties)
cap_ok = len(result.selected_nodes) <= 60

context_pass = objects_ok and columns_ok and relationships_ok and uncertainties_ok and cap_ok
```

However, the internal harness must NOT contain expected pack answers.
The expected answers exist only in the external evaluator.

Therefore, the internal harness can only run structural invariant tests:
- No orphan columns
- No dangling relationships
- Columns have parent tables
- Uncertainties are typed

The pass/fail decision against expected answers belongs ONLY to the independent evaluator.
