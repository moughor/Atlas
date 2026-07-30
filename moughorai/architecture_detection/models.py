from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True, slots=True)
class ArchitectureEvidence:
    kind: str
    reference: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "reference": self.reference,
            "detail": self.detail,
        }


@dataclass(frozen=True, order=True, slots=True)
class ArchitectureFinding:
    architecture: str
    confidence: float
    evidence: tuple[ArchitectureEvidence, ...]

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("architecture confidence must be between 0 and 1")
        if not self.evidence:
            raise ValueError("architecture findings require traceable evidence")

    def to_dict(self) -> dict[str, object]:
        return {
            "architecture": self.architecture,
            "confidence": self.confidence,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class ArchitectureReport:
    findings: tuple[ArchitectureFinding, ...]
    dependency_directions: tuple[tuple[str, str], ...]
    dependency_cycles: tuple[tuple[str, ...], ...]
    bounded_contexts: tuple[str, ...]
    ports: tuple[str, ...]
    adapters: tuple[str, ...]
    infrastructure_layers: tuple[str, ...]
    dependency_analysis_executed: bool = False
    dependency_evidence_edges: int = 0
    classification_conflicts: tuple[str, ...] = ()
    schema_version: int = 1

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "findings": [item.to_dict() for item in self.findings],
            "dependency_directions": [
                {"source": source, "target": target}
                for source, target in self.dependency_directions
            ],
            "dependency_cycles": [list(cycle) for cycle in self.dependency_cycles],
            "bounded_contexts": list(self.bounded_contexts),
            "ports": list(self.ports),
            "adapters": list(self.adapters),
            "infrastructure_layers": list(self.infrastructure_layers),
            "dependency_analysis": {
                "executed": self.dependency_analysis_executed,
                "evidence_edge_count": self.dependency_evidence_edges,
            },
            "classification_conflicts": list(self.classification_conflicts),
        }
