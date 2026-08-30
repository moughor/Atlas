"""Atlas database semantic graph — versioned, frozen, deterministic models.

Schema version 1. Import all public contracts from this package.
"""

from .models import (
    DATABASE_GRAPH_SCHEMA_VERSION,
    ConflictRecord,
    DatabaseGraph,
    DatabaseGraphCoverage,
    DatabaseGraphEdge,
    DatabaseGraphNode,
    EdgeKind,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    NodeKind,
    canonical_json,
)

from .context_selector import (
    DatabaseContextResult,
    OmittedCounts,
    SelectionDetail,
    SelectionUncertainty,
    TruncationMetadata,
    SELECTION_STRATEGY_EVIDENCE_BUNDLES_V1,
    SELECTION_STRATEGY_LEGACY,
    render_database_context_markdown,
    render_database_context_mermaid,
    select_database_context,
)

from .sql_validator import (
    ColumnReference,
    JoinValidation,
    SqlStatementResult,
    SqlValidationIssue,
    SqlValidationResult,
    TableReference,
    validate_sql,
)

__all__ = [
    # models
    "DATABASE_GRAPH_SCHEMA_VERSION",
    "ConflictRecord",
    "DatabaseGraph",
    "DatabaseGraphCoverage",
    "DatabaseGraphEdge",
    "DatabaseGraphNode",
    "EdgeKind",
    "EvidenceRecord",
    "EvidenceSource",
    "EvidenceStatus",
    "NodeKind",
    "canonical_json",
    # context_selector
    "DatabaseContextResult",
    "OmittedCounts",
    "SelectionDetail",
    "SelectionUncertainty",
    "TruncationMetadata",
    "SELECTION_STRATEGY_EVIDENCE_BUNDLES_V1",
    "SELECTION_STRATEGY_LEGACY",
    "render_database_context_markdown",
    "render_database_context_mermaid",
    "select_database_context",
    # sql_validator
    "ColumnReference",
    "JoinValidation",
    "SqlStatementResult",
    "SqlValidationIssue",
    "SqlValidationResult",
    "TableReference",
    "validate_sql",
]
