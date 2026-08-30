# Context Failure Matrix — Atlas b21ae2c

## Summary

| Metric | Count |
|--------|-------|
| Total cases | 14 |
| Context PASS | 0 |
| Context FAIL | 14 |
| SQL PASS | 42/42 |
| Objects missing (cases) | 8 |
| Columns missing (cases) | 14 |
| Relationships missing (cases) | 13 |
| Uncertainties missing (cases) | 14 |

## Per-Case Results

| Case | Obj | Col | Rel | Unc | Nodes | Missing Objects |
|------|-----|-----|-----|-----|-------|-----------------|
| 001 | 3/3 ✓ | 6/12 ✗ | 2/4 ✗ | 0/2 ✗ | 57 | — |
| 002 | 2/2 ✓ | 4/9 ✗ | 0/1 ✗ | 0/3 ✗ | 59 | — |
| 003 | 0/2 ✗ | 0/10 ✗ | 0/1 ✗ | 0/1 ✗ | 58 | TB_RT_SESSION_INSTANCE, TB_RT_EXERCISE_INSTANCE |
| 004 | 1/6 ✗ | 1/17 ✗ | 0/3 ✗ | 0/1 ✗ | 58 | TB_APP_PROJECT_BASE, TB_GRP_ONL_PROJECT_ITEM, TB_RT_EXERCISE_INSTANCE, TB_RT_SESSION_INSTANCE, TB_MDL_EX |
| 005 | 0/3 ✗ | 0/21 ✗ | 0/2 ✗ | 0/1 ✗ | 57 | VW_HD_FAILED_DOC_GEN, TB_RT_SESSION_INSTANCE, TB_APP_EXTERNAL_DOCUMENT |
| 006 | 2/4 ✗ | 2/12 ✗ | 0/3 ✗ | 0/1 ✗ | 57 | TB_GRP_PR_P, TB_RT_SESSION_INSTANCE |
| 007 | 1/9 ✗ | 2/37 ✗ | 0/8 ✗ | 0/1 ✗ | 60 | TB_GRP_PL, TB_GRP_PL_AMD_DATA, TB_RT_DATA_TREE, TB_RT_DATA_FOREST, TB_RT_EXERCISE_INSTANCE, TB_MDL_EX, TB_RT_EXERCISE_PARAM, TB_RT_SESSION_INSTANCE |
| 008 | 4/9 ✗ | 4/36 ✗ | 0/8 ✗ | 0/1 ✗ | 60 | TB_GRP_PR_P, TB_RT_SESSION_INSTANCE, TB_RT_EXERCISE_INSTANCE, TB_RT_EXERCISE_PARAM, MV_A_PROJECT_DATA |
| 009 | 2/2 ✓ | 6/9 ✗ | 1/1 ✓ | 0/1 ✗ | 60 | — |
| 010 | 0/2 ✗ | 0/10 ✗ | 0/2 ✗ | 0/2 ✗ | 57 | TB_GRP_PR_MD_DEC_P_BASE, TB_GRP_PR_MD_PER_P_BASE |
| 011 | 1/2 ✗ | 3/7 ✗ | 0/1 ✗ | 0/1 ✗ | 57 | TB_GRP_PR_AI |
| 012 | 2/2 ✓ | 3/6 ✗ | 1/1 ✓ | 0/1 ✗ | 60 | — |
| 013 | 1/1 ✓ | 4/5 ✗ | 0/0 ✓ | 0/1 ✗ | 59 | — |
| 014 | 0/2 ✗ | 0/3 ✗ | 0/1 ✗ | 0/1 ✗ | 50 | SYGMA.TB_GRP_PF, DYNAMIC:ALL_SYGMA_OBJECTS |

## Failure Categories

### 1. Objects Missing (8/14 cases)
The context selector does not discover the required tables/views for 8 cases:
- Case 003: Session/exercise tables
- Case 004: Project, exercise, session tables
- Case 005: View and its underlying tables
- Case 006: Project reporting tables
- Case 007: Amendment view's dependencies (8 tables)
- Case 008: Reporting period view's dependencies
- Case 010: Mobility declaration tables
- Case 011: Audit item table
- Case 014: Schema-qualified table, dynamic synonym target

### 2. Columns Missing (14/14 cases)
Every case fails to include required columns:
- The bundle selector selects tables but does NOT include required columns
- Required columns for relationships are missing
- Join/FK columns needed for grounding are not retained

### 3. Relationships Missing (13/14 cases)
Only cases 009, 012, 013 have partial relationship coverage:
- FK edges not expanded into context
- View dependencies not included
- Java lazy relations not tracked

### 4. Uncertainties Missing (14/14 cases)
The `uncertainties: []` field is always empty:
- No uncertainty statements are generated
- Expected uncertainties about Jailer snapshot age, MAX(ID) semantics, etc. are not produced

## Root Cause Analysis

The SelectionBundle infrastructure was wired to the public path, but:

1. **Bundle selection is incomplete**: Bundles select tables but not their required columns
2. **Relationship expansion missing**: FK chains are not followed to bring in related tables
3. **Column budget not applied**: No logic allocates columns from each selected table
4. **Uncertainty generation missing**: No code produces uncertainty statements
5. **Evidence provenance incomplete**: Bundle members lack typed evidence paths
