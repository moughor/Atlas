"""PR142 deterministic, evidence-backed technical-debt observations."""

from .models import (
    DEPENDENCY_CYCLE_OBSERVATION,
    TECHNICAL_DEBT_ITEM_LIMITATIONS,
    TECHNICAL_DEBT_IMPACT_ADAPTER_PRODUCER,
    TECHNICAL_DEBT_PRODUCER,
    TECHNICAL_DEBT_SCHEMA_VERSION,
    TechnicalDebtCapability,
    TechnicalDebtCapabilityKind,
    TechnicalDebtCategory,
    TechnicalDebtImpact,
    TechnicalDebtItem,
    TechnicalDebtRequest,
    TechnicalDebtResponse,
    TechnicalDebtState,
    technical_debt_advice_set_digest,
    technical_debt_fingerprint,
    technical_debt_item_id,
    technical_debt_sort_key,
)
from .renderer import render_technical_debt
from .service import TechnicalDebtService

__all__ = [
    "DEPENDENCY_CYCLE_OBSERVATION",
    "TECHNICAL_DEBT_ITEM_LIMITATIONS",
    "TECHNICAL_DEBT_IMPACT_ADAPTER_PRODUCER",
    "TECHNICAL_DEBT_PRODUCER",
    "TECHNICAL_DEBT_SCHEMA_VERSION",
    "TechnicalDebtCapability",
    "TechnicalDebtCapabilityKind",
    "TechnicalDebtCategory",
    "TechnicalDebtImpact",
    "TechnicalDebtItem",
    "TechnicalDebtRequest",
    "TechnicalDebtResponse",
    "TechnicalDebtService",
    "TechnicalDebtState",
    "render_technical_debt",
    "technical_debt_advice_set_digest",
    "technical_debt_fingerprint",
    "technical_debt_item_id",
    "technical_debt_sort_key",
]
