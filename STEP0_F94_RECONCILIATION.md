# STEP 0: F94ef81 Reconciliation Analysis

## Baseline Results

| Metric | Result |
|--------|--------|
| Context | 0/14 |
| Objects | 5/14 |
| Columns | 0/14 |
| FK Inventory | 4/7 |
| Uncertainties | 0/14 |

## Object-Level Analysis

### Cases Passing Objects (5/14)

| Case | Objects Found | Objects Expected | Category |
|------|---------------|------------------|----------|
| 001 | 3/3 | TB_GRP_PF, TB_GRP_PF_FEATURE, TB_GRP_PF_FEATURE_P | JPA entity |
| 002 | 2/2 | TB_RT_RULE_EXCEPTION_DEF, TB_RT_SESSION_INSTANCE | Denormalized ref |
| 009 | 2/2 | TB_GRP_PR_ITM_LOG, TB_APP_EXTERNAL_DOCUMENT | Java AST |
| 012 | 2/2 | TB_MDL_DOC_ITEM, TB_MDL_TPL_INFO_ITEM | Schema evolution |
| 013 | 1/1 | TB_GRP_PL_TEMPLATE_MGA | Backup rejection |

### Cases Failing Objects (9/14)

| Case | Found | Expected | Missing | Category | Failure Mode |
|------|-------|----------|---------|----------|--------------|
| 003 | 0/2 | 2 | TB_RT_SESSION_INSTANCE, TB_RT_EXERCISE_INSTANCE | FK relationship | candidate_not_generated |
| 004 | 0/6 | 6 | TB_APP_PROJECT_BASE, TB_GRP_ONL_PROJECT_ITEM, TB_RT_EXERCISE_INSTANCE, TB_RT_SESSION_INSTANCE, TB_GRP_ETH, TB_MDL_EX | Native query | artifact_not_retrieved |
| 005 | 0/3 | 3 | VW_HD_FAILED_DOC_GEN, TB_RT_SESSION_INSTANCE, TB_APP_EXTERNAL_DOCUMENT | View | view_absent_from_graph |
| 006 | 2/4 | 4 | TB_GRP_PR_P, TB_RT_SESSION_INSTANCE | View | view_dependency_not_traversed |
| 007 | 1/9 | 9 | TB_GRP_PL, TB_GRP_PL_AMD_DATA, TB_RT_DATA_TREE, TB_RT_DATA_FOREST, TB_RT_EXERCISE_INSTANCE, TB_MDL_EX, TB_RT_EXERCISE_PARAM, TB_RT_SESSION_INSTANCE | View | view_dependency_not_traversed |
| 008 | 4/9 | 9 | TB_GRP_PR_P, TB_RT_SESSION_INSTANCE, TB_RT_EXERCISE_INSTANCE, TB_RT_EXERCISE_PARAM, MV_A_PROJECT_DATA | MV | mv_dependency_not_traversed |
| 010 | 0/2 | 2 | TB_GRP_PR_MD_DEC_P_BASE, TB_GRP_PR_MD_PER_P_BASE | Java AST | candidate_ranked_below_noise |
| 011 | 1/2 | 2 | TB_GRP_PR_AI | Migration | migration_not_traversed |
| 014 | 0/2 | 2 | SYGMA.TB_GRP_PF, DYNAMIC:ALL_SYGMA_OBJECTS | Dynamic synonym | schema_resolution_failure |

## Failure Mode Classification

### 1. candidate_not_generated (Case 003)
Tables exist in graph but no candidate bundle was created.
Story: "A session is stuck. Retrieve its exercise model..."
Neither "session" nor "exercise" directly maps to TB_RT_SESSION_INSTANCE or TB_RT_EXERCISE_INSTANCE.

### 2. artifact_not_retrieved (Case 004)
Story mentions "RulesDao" native query but algorithm doesn't parse Java artifacts.
Required: Extract tables from RulesDao#getAllEthicsIssuesFlags native SQL.

### 3. view_absent_from_graph (Case 005)
VW_HD_FAILED_DOC_GEN is not in the reconciled graph.
Root cause: View SQL not ingested.

### 4. view_dependency_not_traversed (Cases 006, 007)
Views exist but their source table dependencies aren't traversed.
Required: Parse view SQL to find source tables.

### 5. mv_dependency_not_traversed (Case 008)
Materialized views exist but dependencies not traversed.
Required: Parse MV SQL to find source tables.

### 6. candidate_ranked_below_noise (Case 010)
TB_GRP_PR_MD_DEC_P_BASE and TB_GRP_PR_MD_PER_P_BASE exist in graph.
Story: "The stored duration and the duration derivable from dates may disagree"
Neither table name matches story terms.

### 7. migration_not_traversed (Case 011)
TB_GRP_PR_AI added by migration but not found.
Required: Parse migration files to find created/altered tables.

### 8. schema_resolution_failure (Case 014)
SYGMA.TB_GRP_PF should resolve to TB_GRP_PF.
Dynamic synonym generator not modeled.

## Objects in Full Graph

Of 20 unique missing objects:
- **17 exist in graph** but weren't selected
- **3 absent from graph**:
  - VW_HD_FAILED_DOC_GEN (view not ingested)
  - SYGMA.TB_GRP_PF (schema qualifier not resolved)
  - DYNAMIC:ALL_SYGMA_OBJECTS (synthetic)

## Root Cause Summary

The f94ef81 algorithm uses **table-name-to-story-term matching** instead of **artifact-first evidence retrieval**.

Required evidence artifacts NOT used:
1. Java native query parsing
2. View SQL dependency parsing
3. Materialized view dependency parsing
4. Migration file parsing
5. JPA entity-to-table mapping with column evidence
6. Schema-qualified canonical resolution
7. Dynamic synonym modeling

## Column Failure Analysis (0/14)

Even when objects are found (5 cases), columns fail because:
1. Random PK/FK columns selected instead of story-relevant columns
2. No native query projection parsing
3. No view column tracing
4. No JPA property-to-column mapping
5. No migration column evidence

## Uncertainty Failure Analysis (0/14)

All cases have BUDGET_OMISSION uncertainty but expect evidence-derived uncertainties:
- "Jailer 9.3.3 predates the inspected 23.12 branch"
- "MAX(session ID) is query-specific latest-session logic"
- "Live session/exercise state and deployment drift are not known"
- etc.

These require structured evidence analysis, not blanket insertion.

## Required Architecture Changes

1. **Remove quota-based selection** (50% table, 3 entities, 2 bridges)
2. **Add artifact resolver** for:
   - Java native queries
   - View definitions
   - Materialized view definitions
   - Migration files
   - JPA mappings
3. **Evidence-first object retrieval** - find artifacts, then materialize closure
4. **Evidence-exact column selection** - from artifact projections, not random
5. **Structured uncertainty derivation** - from evidence state, not blanket insertion

## Evidence Artifacts Already Available

Analysis reveals the required evidence artifacts ARE being extracted but NOT used:

### Native Query Relations (13 extracted)
The `RulesDao#getAllEthicsIssuesFlags` query tables are fully extracted:
- TB_APP_PROJECT_BASE -> TB_GRP_ONL_PROJECT_ITEM
- TB_APP_PROJECT_BASE -> TB_RT_EXERCISE_INSTANCE (SCOPE_ID/SCOPE_TYPE)
- TB_RT_EXERCISE_INSTANCE -> TB_MDL_EX (EXERCISE_MODEL_ID)
- TB_RT_EXERCISE_INSTANCE -> TB_RT_SESSION_INSTANCE (EXERCISE_ID)
- TB_RT_SESSION_INSTANCE -> TB_GRP_ETH (SESSION_ID)

This is exactly what Case 004 requires. **The data exists in JpaExtractionResult.native_query_relations**.

### JPA Entity Mappings (694 entities, 4225 fields)
Entity-to-table mappings exist as MAPS_TO_TABLE edges (336 edges).
Field-to-column mappings exist as MAPS_TO_COLUMN edges (2052 edges).

### Graph Relationships
- FOREIGN_KEY_TO: 741 edges
- JAVA_RELATION_TO: 316 edges
- LOGICAL_REFERENCE_TO: 11 edges

### What's Missing from Graph
- **VW_HD_FAILED_DOC_GEN** and most views (only 3 views in graph)
- View dependency edges (DERIVED_FROM, READS_FROM) are not created
- Migration lineage edges

## Architecture Fix Required

The bundle_selector.py must be modified to:

1. **Query native_query_relations by method name**
   When story mentions "RulesDao", find all native queries from that class.

2. **Traverse JPA relationships**
   When story mentions Java entity name, follow MAPS_TO_TABLE and MAPS_TO_COLUMN.

3. **Traverse view dependencies**
   When a view is matched, follow DERIVED_FROM/READS_FROM to source tables.

4. **Use FK relationships for closure**
   After primary objects selected, traverse FOREIGN_KEY_TO for closure.

The current algorithm's fatal flaw: it builds candidates from table names only,
ignoring the rich evidence artifacts already in the extraction result.

## Immediate Actions

1. Remove quota policies (50% table, 3 entities, 2 bridges)
2. Add evidence artifact index to bundle_selector
3. Match story concepts to artifact names (class names, method names)
4. Materialize complete evidence closure when artifact matched
5. Select columns from evidence (not random PK/FK)
6. Derive uncertainties from evidence state (not blanket insertion)
