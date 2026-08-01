from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from .index import EvidenceIndex


RESOLVED_SEMANTIC_FACT_RELIABILITY = 1.0
STRUCTURED_ANALYZER_RELIABILITY = 0.9
REPOSITORY_METADATA_RELIABILITY = 0.8
REPRODUCIBLE_HEURISTIC_RELIABILITY = 0.6


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

    def __post_init__(self) -> None:
        for name in (
            "score",
            "support",
            "coverage",
            "agreement",
            "contradiction_penalty",
            "ambiguity_penalty",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"confidence {name} must be between 0 and 1")
        if self.model_version <= 0:
            raise ValueError("confidence model version must be positive")
        object.__setattr__(
            self,
            "missing_roles",
            tuple(sorted(set(self.missing_roles))),
        )
        expected = _confidence_tier(self.score, self.missing_roles)
        if self.tier is not expected:
            raise ValueError(
                f"confidence tier {self.tier.value!r} does not match score and missing roles"
            )

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

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ConfidenceResult:
        """Restore the shared deterministic confidence contract."""

        return cls(
            float(value.get("score", 0.0)),
            ConfidenceTier(str(value.get("tier", ConfidenceTier.INSUFFICIENT.value))),
            float(value.get("support", 0.0)),
            float(value.get("coverage", 0.0)),
            float(value.get("agreement", 1.0)),
            float(value.get("contradiction_penalty", 0.0)),
            float(value.get("ambiguity_penalty", 0.0)),
            tuple(
                sorted(set(map(str, value.get("missing_roles", ()))))
            ),
            int(value.get("model_version", 1)),
        )


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
        return _confidence_tier(score, missing)


def _confidence_tier(score: float, missing: tuple[str, ...]) -> ConfidenceTier:
    if missing or score < 0.4:
        return ConfidenceTier.INSUFFICIENT
    if score >= 0.8:
        return ConfidenceTier.HIGH
    if score >= 0.6:
        return ConfidenceTier.MEDIUM
    return ConfidenceTier.LOW
