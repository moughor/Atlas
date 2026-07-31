from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from moughorai.semantic_evidence import (
    ConfidenceResult,
    ConfidenceTier,
    EvidenceIndex,
)


class PatternKind(str, Enum):
    STRATEGY = "strategy"
    FACTORY = "factory"
    BUILDER = "builder"
    ADAPTER = "adapter"
    OBSERVER = "observer"
    DECORATOR = "decorator"
    COMPOSITE = "composite"
    COMMAND = "command"
    CHAIN_OF_RESPONSIBILITY = "chain-of-responsibility"
    STATE = "state"
    TEMPLATE_METHOD = "template-method"


class PatternAvailability(str, Enum):
    AVAILABLE = "available"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, order=True, slots=True)
class PatternParticipant:
    role: str
    symbol_id: str
    qualified_name: str

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "symbol_id": self.symbol_id,
            "qualified_name": self.qualified_name,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PatternParticipant:
        return cls(
            str(value["role"]),
            str(value["symbol_id"]),
            str(value["qualified_name"]),
        )


@dataclass(frozen=True, order=True, slots=True)
class PatternCapability:
    pattern: PatternKind
    availability: PatternAvailability
    required_evidence: tuple[str, ...]
    available_evidence: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "required_evidence", tuple(sorted(set(self.required_evidence))),
        )
        object.__setattr__(
            self, "available_evidence", tuple(sorted(set(self.available_evidence))),
        )
        object.__setattr__(
            self, "limitations", tuple(sorted(set(self.limitations))),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "pattern": self.pattern.value,
            "availability": self.availability.value,
            "required_evidence": list(self.required_evidence),
            "available_evidence": list(self.available_evidence),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PatternCapability:
        return cls(
            PatternKind(str(value["pattern"])),
            PatternAvailability(str(value["availability"])),
            tuple(map(str, value.get("required_evidence", ()))),
            tuple(map(str, value.get("available_evidence", ()))),
            tuple(map(str, value.get("limitations", ()))),
        )


@dataclass(frozen=True, order=True, slots=True)
class PatternFinding:
    pattern: PatternKind
    participants: tuple[PatternParticipant, ...]
    confidence: float
    confidence_tier: ConfidenceTier
    evidence_ids: tuple[str, ...]
    explanation: str
    limitations: tuple[str, ...] = ()
    scope: str = "repository"
    language: str = "unknown"
    detector_version: str = "atlas-pr130/1"

    def __post_init__(self) -> None:
        if not self.participants:
            raise ValueError("pattern findings require participating symbols")
        if not self.evidence_ids:
            raise ValueError("pattern findings require evidence IDs")
        if self.confidence_tier is ConfidenceTier.INSUFFICIENT:
            raise ValueError("insufficient candidates are capabilities, not findings")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("pattern confidence must be between 0 and 1")
        object.__setattr__(self, "participants", tuple(sorted(self.participants)))
        object.__setattr__(
            self, "evidence_ids", tuple(sorted(set(self.evidence_ids))),
        )
        object.__setattr__(
            self, "limitations", tuple(sorted(set(self.limitations))),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "pattern": self.pattern.value,
            "participants": [item.to_dict() for item in self.participants],
            "confidence": self.confidence,
            "confidence_tier": self.confidence_tier.value,
            "evidence_ids": list(self.evidence_ids),
            "explanation": self.explanation,
            "limitations": list(self.limitations),
            "scope": self.scope,
            "language": self.language,
            "detector_version": self.detector_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PatternFinding:
        return cls(
            PatternKind(str(value["pattern"])),
            tuple(
                PatternParticipant.from_dict(item)
                for item in value.get("participants", ())
                if isinstance(item, Mapping)
            ),
            float(value["confidence"]),
            ConfidenceTier(str(value["confidence_tier"])),
            tuple(map(str, value.get("evidence_ids", ()))),
            str(value["explanation"]),
            tuple(map(str, value.get("limitations", ()))),
            str(value.get("scope", "repository")),
            str(value.get("language", "unknown")),
            str(value.get("detector_version", "atlas-pr130/1")),
        )


@dataclass(frozen=True, slots=True)
class PatternDetectionReport:
    findings: tuple[PatternFinding, ...]
    capabilities: tuple[PatternCapability, ...]
    evidence_index: EvidenceIndex
    input_fingerprint: str
    producer_version: str = "atlas-pr130/1"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if not self.input_fingerprint.strip():
            raise ValueError("pattern report input fingerprint must not be empty")
        object.__setattr__(self, "findings", tuple(sorted(self.findings)))
        object.__setattr__(self, "capabilities", tuple(sorted(self.capabilities)))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "input_fingerprint": self.input_fingerprint,
            "findings": [item.to_dict() for item in self.findings],
            "capabilities": [item.to_dict() for item in self.capabilities],
            "evidence_index": self.evidence_index.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PatternDetectionReport:
        if int(value.get("schema_version", 1)) != 1:
            raise ValueError("unsupported pattern report schema")
        raw_index = value.get("evidence_index", {})
        return cls(
            tuple(
                PatternFinding.from_dict(item)
                for item in value.get("findings", ())
                if isinstance(item, Mapping)
            ),
            tuple(
                PatternCapability.from_dict(item)
                for item in value.get("capabilities", ())
                if isinstance(item, Mapping)
            ),
            EvidenceIndex.from_dict(raw_index if isinstance(raw_index, Mapping) else {}),
            str(value["input_fingerprint"]),
            str(value.get("producer_version", "atlas-pr130/1")),
            int(value.get("schema_version", 1)),
        )


def finding_confidence(value: ConfidenceResult) -> tuple[float, ConfidenceTier]:
    return value.score, value.tier
