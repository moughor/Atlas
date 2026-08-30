# Complete Context Gap Matrix

Commit: `ffe9ddd` on `correction/atlas-phase-c-retrieval-v2`

| Case | Table | Cols | Rels | Complete | Missing Objs | Missing Cols | Missing Rels |
|------|-------|------|------|----------|-------------|-------------|-------------|
| SYGMA-DB-001 | ✓ | ✗ | ✓ | ✗ | 0 | 11 | 0 |
| SYGMA-DB-002 | ✓ | ✗ | ✗ | ✗ | 0 | 8 | 1 |
| SYGMA-DB-003 | ✓ | ✗ | ✓ | ✗ | 0 | 5 | 0 |
| SYGMA-DB-004 | ✗ | ✗ | ✗ | ✗ | 5 | 17 | 3 |
| SYGMA-DB-005 | ✗ | ✗ | ✗ | ✗ | 2 | 21 | 1 |
| SYGMA-DB-006 | ✗ | ✗ | ✗ | ✗ | 2 | 7 | 1 |
| SYGMA-DB-007 | ✗ | ✗ | ✗ | ✗ | 7 | 37 | 1 |
| SYGMA-DB-008 | ✗ | ✗ | ✗ | ✗ | 4 | 36 | 1 |
| SYGMA-DB-009 | ✓ | ✗ | ✓ | ✗ | 0 | 9 | 0 |
| SYGMA-DB-010 | ✗ | ✗ | ✗ | ✗ | 4 | 10 | 2 |
| SYGMA-DB-011 | ✓ | ✗ | ✗ | ✗ | 0 | 2 | 1 |
| SYGMA-DB-012 | ✓ | ✗ | ✓ | ✗ | 0 | 6 | 0 |
| SYGMA-DB-013 | ✓ | ✓ | ✓ | ✓ | 0 | 0 | 0 |
| SYGMA-DB-014 | ✗ | ✗ | ✗ | ✗ | 1 | 3 | 1 |

## Per-Case Details

### SYGMA-DB-001 — TABLE_PASS
Budget: {'table': 18, 'column': 35, 'java_entity': 7}, remaining: 0

**Missing columns:**
- `TB_GRP_PF`: ['ID', 'PROJECT_NUMBER', 'SESSION_ID', 'VERSION'] (evicted)
- `TB_GRP_PF_FEATURE`: ['ID', 'GROUP_PF_ID', 'SEMANTIC_REF'] (evicted)
- `TB_GRP_PF_FEATURE_P`: ['ID', 'FEATURE_ID', 'SEMANTIC_REF', 'VALUE_TYPE'] (evicted)

### SYGMA-DB-002 — TABLE_PASS
Budget: {'table': 51, 'column': 9}, remaining: 0

**Missing columns:**
- `TB_RT_RULE_EXCEPTION_DEF`: ['ID', 'RULE_IDENTIFIER', 'EXERCISE_SCOPE_TYPE', 'EXERCISE_SCOPE_ID', 'EXERCISE_INSTANCES', 'SESSION_INSTANCES', 'STATE'] (evicted)
- `TB_RT_SESSION_INSTANCE`: ['ID'] (evicted)

**Missing relationships:**
- `TB_RT_RULE_EXCEPTION_DEF.SESSION_INSTANCES` → `TB_RT_SESSION_INSTANCE.ID` (logical_reference) — edge_not_in_context

### SYGMA-DB-003 — TABLE_PASS
Budget: {'table': 15, 'column': 45}, remaining: 0

**Missing columns:**
- `TB_RT_EXERCISE_INSTANCE`: ['ID', 'EXERCISE_MODEL_ID', 'STATE_INTERNAL', 'SCOPE_ID', 'SCOPE_TYPE'] (evicted, not_scored)

### SYGMA-DB-004 — FAIL
Budget: {'materialized_view': 2, 'table': 15, 'column': 34, 'view': 3, 'java_entity': 6}, remaining: 0

**Missing objects:**
- `TB_GRP_ONL_PROJECT_ITEM` (table) — in_graph, evicted
- `TB_RT_EXERCISE_INSTANCE` (table) — in_graph
- `TB_RT_SESSION_INSTANCE` (table) — in_graph
- `TB_MDL_EX` (table) — in_graph
- `eu.europa.ec.rdg.sygma.exercises.common.impl.dao.RulesDao#getAllEthicsIssuesFlags` (java_entity) — NOT_in_graph

**Missing columns:**
- `TB_APP_PROJECT_BASE`: ['PROJECT_NUMBER', 'PROJECT_TYPE'] (evicted)
- `TB_GRP_ONL_PROJECT_ITEM`: ['PROJECT_NUMBER', 'GROUP_ONL_BATCH_ID'] (parent_missing)
- `TB_RT_EXERCISE_INSTANCE`: ['ID', 'SCOPE_ID', 'SCOPE_TYPE', 'EXERCISE_MODEL_ID'] (parent_missing)
- `TB_RT_SESSION_INSTANCE`: ['ID', 'EXERCISE_ID', 'STATE_INTERNAL', 'MODIFIABLE_TREE_DTYPE'] (parent_missing)
- `TB_GRP_ETH`: ['SESSION_ID', 'PROJECT_NUMBER', 'ETHICS_ISSUES'] (evicted, not_scored)
- `TB_MDL_EX`: ['ID', 'EXERCISE_MODEL_CATEGORY'] (parent_missing)

**Missing relationships:**
- `TB_RT_EXERCISE_INSTANCE.SCOPE_ID/SCOPE_TYPE` → `TB_APP_PROJECT_BASE.PROJECT_NUMBER/PROJECT_TYPE` (logical_reference) — endpoint_missing:from
- `TB_RT_SESSION_INSTANCE.EXERCISE_ID` → `TB_RT_EXERCISE_INSTANCE.ID` (foreign_key) — endpoint_missing:from
- `TB_GRP_ETH.SESSION_ID` → `TB_RT_SESSION_INSTANCE.ID` (logical_reference) — endpoint_missing:to

**Evicted objects (scored but not selected):**
- `TB_GRP_ONL_PROJECT_ITEM`: tier=3 sub=3 score=74 reason=alias1:project

### SYGMA-DB-005 — FAIL
Budget: {'table': 13, 'column': 41, 'java_entity': 6}, remaining: 0

**Missing objects:**
- `VW_HD_FAILED_DOC_GEN` (view) — in_graph, evicted
- `TB_RT_SESSION_INSTANCE` (table) — in_graph

**Missing columns:**
- `VW_HD_FAILED_DOC_GEN`: ['PROJECT_NUMBER', 'EXERCISE_MODEL_CATEGORY', 'CALL_CCM', 'SESSION_ID', 'END_DATE', 'SESSION_TYPE', 'BATCH_ID', 'BATCH_ITEM_ID', 'DOCUMENT_MODEL_ID', 'DOC_GEN_STAGE', 'DOC_GEN_STATE', 'TEMPLATE_ID', 'EXERCISE_MODEL', 'DOCUMENT_ID'] (parent_missing)
- `TB_RT_SESSION_INSTANCE`: ['ID', 'EXERCISE_ID', 'END_DATE', 'MODIFIABLE_TREE_DTYPE', 'PAR_SESSION_TAG'] (parent_missing)
- `TB_APP_EXTERNAL_DOCUMENT`: ['ID', 'DOCUMENT_ID'] (evicted, not_scored)

**Missing relationships:**
- `VW_HD_FAILED_DOC_GEN` → `TB_APP_EXTERNAL_DOCUMENT/TB_RT_SESSION_INSTANCE` (view_dependency) — endpoint_missing:from

**Evicted objects (scored but not selected):**
- `VW_HD_FAILED_DOC_GEN`: tier=3 sub=3 score=50 reason=alias1:failed

### SYGMA-DB-006 — FAIL
Budget: {'table': 12, 'column': 43, 'view': 1, 'java_entity': 4}, remaining: 0

**Missing objects:**
- `TB_GRP_PR_P` (table) — in_graph
- `VW_NON_FP7_PROJECTS` (view) — in_graph, evicted

**Missing columns:**
- `TB_GRP_PR_P`: ['PROJECT_NUMBER', 'SESSION_ID', 'ID', 'PERIOD_IDENTIFIER'] (parent_missing)
- `VW_NON_FP7_PROJECTS`: ['PROJECT_NUMBER'] (parent_missing)
- `TB_RT_SESSION_INSTANCE`: ['ID', 'STATE_INTERNAL'] (not_scored)

**Missing relationships:**
- `VW_LATEST_CLOSED_REP_SESSIONS` → `TB_GRP_PR_P/VW_NON_FP7_PROJECTS/TB_RT_SESSION_INSTANCE` (view_dependency) — endpoint_missing:to

**Evicted objects (scored but not selected):**
- `VW_NON_FP7_PROJECTS`: tier=3 sub=3 score=50 reason=alias1:projects

### SYGMA-DB-007 — FAIL
Budget: {'table': 6, 'column': 44, 'view': 8, 'java_entity': 2}, remaining: 0

**Missing objects:**
- `TB_GRP_PL` (table) — in_graph
- `TB_GRP_PL_AMD_DATA` (table) — in_graph
- `TB_RT_DATA_TREE` (table) — in_graph
- `TB_RT_DATA_FOREST` (table) — in_graph
- `TB_RT_EXERCISE_INSTANCE` (table) — in_graph
- `TB_MDL_EX` (table) — in_graph
- `TB_RT_EXERCISE_PARAM` (table) — in_graph

**Missing columns:**
- `VW_BAM_AMENDMENTS`: ['PROJECT_NUMBER', 'AMD_REF', 'AMD_NUMBER', 'AMD_TYPE', 'AMD_VERSION', 'AMD_START_DATE', 'AMD_END_DATE', 'AMD_EXERCISE_ID', 'AMD_EXERCISE_STATE', 'AMD_SESSION_ID'] (evicted)
- `TB_GRP_PL`: ['ID', 'PROJECT_NUMBER', 'OTO_AMD_DATA_ID', 'VERSION'] (parent_missing)
- `TB_GRP_PL_AMD_DATA`: ['ID', 'AMD_TYPE', 'AMD_COMMISSION_REF'] (parent_missing)
- `TB_RT_DATA_TREE`: ['TREE_ROOT_ID', 'FOREST_ID', 'TREE_DTYPE'] (parent_missing)
- `TB_RT_DATA_FOREST`: ['ID'] (parent_missing)
- `TB_RT_EXERCISE_INSTANCE`: ['ID', 'SCOPE_ID', 'SCOPE_TYPE', 'EXERCISE_MODEL_ID', 'START_DATE', 'END_DATE', 'STATE_CODE'] (parent_missing)
- `TB_MDL_EX`: ['ID', 'EXERCISE_MODEL_CATEGORY'] (parent_missing)
- `TB_RT_EXERCISE_PARAM`: ['EXERCISE_ID', 'KEY', 'VALUE'] (parent_missing)
- `TB_RT_SESSION_INSTANCE`: ['ID', 'FOREST_ID', 'EXERCISE_ID', 'MODIFIABLE_TREE_DTYPE'] (not_scored)

**Missing relationships:**
- `VW_BAM_AMENDMENTS` → `TB_GRP_PL/TB_GRP_PL_AMD_DATA/TB_RT_DATA_TREE/TB_RT_DATA_FOREST/TB_RT_EXERCISE_INSTANCE/TB_MDL_EX/TB_RT_EXERCISE_PARAM/TB_RT_SESSION_INSTANCE` (view_dependency) — endpoint_missing:to

### SYGMA-DB-008 — FAIL
Budget: {'materialized_view': 4, 'table': 40, 'view': 2, 'java_entity': 14}, remaining: 0

**Missing objects:**
- `TB_GRP_PR_P` (table) — in_graph, evicted
- `TB_RT_EXERCISE_INSTANCE` (table) — in_graph
- `TB_RT_EXERCISE_PARAM` (table) — in_graph
- `MV_A_PROJECT_DATA` (materialized_view) — in_graph, evicted

**Missing columns:**
- `MV_A_REPORTING_PERIODS`: ['PART_TIME_EXT_DAYS', 'PROJECT_NUMBER', 'VERSION', 'PL_ID', 'PERIOD', 'PERIOD_FROM', 'PERIOD_TO', 'START_DATE', 'END_DATE', 'PREVIOUS_END_DATE', 'OPENED_PERIOD'] (not_in_graph, evicted)
- `TB_GRP_PR_P`: ['PROJECT_NUMBER', 'SESSION_ID', 'REPORT_TYPE'] (parent_missing)
- `TB_RT_SESSION_INSTANCE`: ['ID', 'EXERCISE_ID', 'MODIFIABLE_TREE_DTYPE', 'STATE_INTERNAL'] (not_scored)
- `TB_RT_EXERCISE_INSTANCE`: ['ID', 'STATE_INTERNAL'] (parent_missing)
- `TB_RT_EXERCISE_PARAM`: ['EXERCISE_ID', 'KEY', 'VALUE'] (parent_missing)
- `TB_APP_PROJECT_BASE`: ['PROJECT_NUMBER'] (evicted)
- `TB_GRP_PL`: ['ID', 'PROJECT_NUMBER', 'START_DATE'] (evicted)
- `MV_A_PROJECT_DATA`: ['PL_ID', 'VERSION'] (parent_missing)
- `TB_GRP_PL_REPORTING_PERIOD`: ['PROJECT_LEGAL_GROUP_ID', 'IDENTIFIER', 'FROM_MONTH', 'TO_MONTH', 'DTYPE', 'SCRP_ID', 'PART_TIME_EXT_DAYS'] (evicted)

**Missing relationships:**
- `MV_A_REPORTING_PERIODS` → `TB_GRP_PR_P/TB_RT_SESSION_INSTANCE/TB_RT_EXERCISE_INSTANCE/TB_RT_EXERCISE_PARAM/TB_APP_PROJECT_BASE/TB_GRP_PL/MV_A_PROJECT_DATA/TB_GRP_PL_REPORTING_PERIOD` (view_dependency) — endpoint_missing:to

**Evicted objects (scored but not selected):**
- `TB_GRP_PR_P`: tier=0 sub=3 score=70 reason=fk_neighbor_of_pinned:5d260978ccb7397560ff88980774f3fbf7cd06
- `MV_A_PROJECT_DATA`: tier=3 sub=3 score=50 reason=alias1:project

### SYGMA-DB-009 — TABLE_PASS
Budget: {'table': 40, 'java_entity': 20}, remaining: 0

**Missing columns:**
- `TB_GRP_PR_ITM_LOG`: ['ID', 'OTO_EXTERNAL_DOCUMENT_ID', 'GRP_PERIODIC_REPORT_ID', 'STATE', 'REPORT_ITEM_TYPE'] (evicted)
- `TB_APP_EXTERNAL_DOCUMENT`: ['ID', 'DOCUMENT_ID', 'REPOSITORY_ID', 'VERSION'] (evicted)

### SYGMA-DB-010 — FAIL
Budget: {'table': 6, 'column': 26, 'java_entity': 28}, remaining: 0

**Missing objects:**
- `TB_GRP_PR_MD_DEC_P_BASE` (table) — in_graph, evicted
- `TB_GRP_PR_MD_PER_P_BASE` (table) — in_graph, evicted
- `eu.europa.ec.rdg.sygma.domain.business.groups.projectreport.mobility.PrimaryMobilityDeclarationBase` (java_entity) — NOT_in_graph
- `eu.europa.ec.rdg.sygma.domain.business.groups.projectreport.mobility.PrimaryMobilityPeriodBase` (java_entity) — NOT_in_graph

**Missing columns:**
- `TB_GRP_PR_MD_DEC_P_BASE`: ['ID', 'DECLARATION_STATE', 'MOBILITY_NUMBER', 'PERSON_SEM_REF_ID', 'CONTINUOUS_REPORT_ID'] (parent_missing)
- `TB_GRP_PR_MD_PER_P_BASE`: ['ID', 'START_DATE', 'END_DATE', 'DURATION', 'MOBILITY_DECLARATION_ID'] (parent_missing)

**Missing relationships:**
- `TB_GRP_PR_MD_PER_P_BASE.MOBILITY_DECLARATION_ID` → `TB_GRP_PR_MD_DEC_P_BASE.ID` (foreign_key) — endpoint_missing:from
- `PrimaryMobilityDeclarationBase.mobilityPeriods` → `PrimaryMobilityPeriodBase.MOBILITY_DECLARATION_ID` (java_lazy_relation) — endpoint_missing:from

**Evicted objects (scored but not selected):**
- `TB_GRP_PR_MD_DEC_P_BASE`: tier=0 sub=3 score=55 reason=alias_hub:base(fk=7)
- `TB_GRP_PR_MD_PER_P_BASE`: tier=0 sub=3 score=70 reason=alias1:base

### SYGMA-DB-011 — TABLE_PASS
Budget: {'materialized_view': 2, 'column': 45, 'table': 11, 'java_entity': 2}, remaining: 0

**Missing columns:**
- `TB_GRP_PR_AI`: ['ID', 'GRANT_REDUCTIONS_APPLIC'] (not_in_graph, not_scored)

**Missing relationships:**
- `TB_GRP_PR_AI_GR.AUDIT_ID` → `TB_GRP_PR_AI.ID` (migration_lineage) — edge_not_in_context

### SYGMA-DB-012 — TABLE_PASS
Budget: {'table': 44, 'java_entity': 16}, remaining: 0

**Missing columns:**
- `TB_MDL_DOC_ITEM`: ['ID', 'TPL_INFO_ITEM_ID', 'TPL_INFO_CONDITIONAL', 'DISPLAY_NAME', 'HAS_DYNAMIC_TEMPLATES'] (evicted)
- `TB_MDL_TPL_INFO_ITEM`: ['ID'] (evicted)

### SYGMA-DB-013 — COMPLETE
Budget: {'table': 13, 'column': 45, 'view': 1, 'java_entity': 1}

### SYGMA-DB-014 — FAIL
Budget: {'synonym': 1, 'materialized_view': 2, 'column': 44, 'table': 9, 'java_entity': 4}, remaining: 0

**Missing objects:**
- `SYGMA.TB_GRP_PF` (table) — NOT_in_graph

**Missing columns:**
- `SYGMA.TB_GRP_PF`: ['ID', 'PROJECT_NUMBER', 'SESSION_ID'] (parent_missing)

**Missing relationships:**
- `consumer-schema synonym name` → `SYGMA.<runtime all_objects name>` (synonym_alias) — endpoint_missing:from
