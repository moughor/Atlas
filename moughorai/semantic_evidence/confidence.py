from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .index import EvidenceIndex


class ConfidenceTier(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, order=True, slots=True)
class EvidenceRole:
    name: str
    evidence_ids: tuple[str, ...] = ()
    required: bool = True

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("evidence role name must not be empty")
        object.__setattr__(
            self,
            "evidence_ids",
            tuple(sorted(set(self.evidence_ids))),
        )


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    score: float
    tier: ConfidenceTier
    support: float
    coverage: float
    agreement: float
    contradiction_penalty: float
    ambiguity_penalty: float
    missing_roles: tuple[str, ...] = ()
    model_version: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "tier": self.tier.value,
            "support": self.support,
            "coverage": self.coverage,
            "agreement": self.agreement,
            "contradiction_penalty": self.contradiction_penalty,
            "ambiguity_penalty": self.ambiguity_penalty,
            "missing_roles": list(self.missing_roles),
            "model_version": self.model_version,
        }


class ConfidenceCalculator:
    MODEL_VERSION = 1

    def calculate(
        self,
        roles: tuple[EvidenceRole, ...],
        evidence: EvidenceIndex,
        *,
        coverage: float = 1.0,
        agreement: float = 1.0,
        contradiction_penalty: float = 0.0,
        ambiguity_penalty: float = 0.0,
    ) -> ConfidenceResult:
        for name, value in (
            ("coverage", coverage),
            ("agreement", agreement),
            ("contradiction_penalty", contradiction_penalty),
            ("ambiguity_penalty", ambiguity_penalty),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")

        ordered = tuple(sorted(roles))
        missing = tuple(
            role.name
            for role in ordered
            if role.required and not self._records(role, evidence)
        )
        numerator = 0.0
        denominator = 0.0
        for role in ordered:
            records = self._records(role, evidence)
            if not records:
                continue
            weight = 2.0 if role.required else 1.0
            quality = sum(
                record.reliability * record.specificity
                for record in records
            ) / len(records)
            numerator += quality * weight
            denominator += weight
        support = numerator / denominator if denominator else 0.0
        score = max(
            0.0,
            min(
                1.0,
                support * coverage * agreement
                - contradiction_penalty
                - ambiguity_penalty,
            ),
        )
        rounded = round(score, 4)
        tier = self._tier(rounded, missing)
        return ConfidenceResult(
            rounded,
            tier,
            round(support, 4),
            round(coverage, 4),
            round(agreement, 4),
            round(contradiction_penalty, 4),
            round(ambiguity_penalty, 4),
            missing,
            self.MODEL_VERSION,
        )

    @staticmethod
    def _records(role: EvidenceRole, evidence: EvidenceIndex):
        return tuple(
            record
            for evidence_id in role.evidence_ids
            if (record := evidence.get(evidence_id)) is not None
        )

    @staticmethod
    def _tier(score: float, missing: tuple[str, ...]) -> ConfidenceTier:
        if missing or score < 0.4:
            return ConfidenceTier.INSUFFICIENT
        if score >= 0.8:
            return ConfidenceTier.HIGH
        if score >= 0.6:
            return ConfidenceTier.MEDIUM
        return ConfidenceTier.LOW
