from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ArchitectureDependencyEvidenceClass(str, Enum):
    BUILD_MODULE = "BUILD_MODULE"
    SOURCE_IMPORT = "SOURCE_IMPORT"


class ArchitectureDependencyPairClassification(str, Enum):
    CORROBORATED = "CORROBORATED"
    BUILD_ONLY = "BUILD_ONLY"
    IMPORT_ONLY = "IMPORT_ONLY"


@dataclass(frozen=True, order=True, slots=True)
class ArchitectureDependencyDirection:
    source_project: str
    target_project: str
    evidence_class: ArchitectureDependencyEvidenceClass
    evidence_count: int
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.source_project or not self.target_project:
            raise ValueError("architecture dependency projects must not be empty")
        if self.evidence_count < 1:
            raise ValueError("architecture dependency evidence count must be positive")
        object.__setattr__(self, "provenance", tuple(sorted(set(self.provenance))))

    def to_dict(self) -> dict[str, object]:
        return {
            "source_project": self.source_project,
            "target_project": self.target_project,
            "evidence_class": self.evidence_class.value,
            "evidence_count": self.evidence_count,
            "provenance": list(self.provenance),
        }


@dataclass(frozen=True, slots=True)
class ArchitectureDependencyTopology:
    evidence_class: ArchitectureDependencyEvidenceClass
    directions: tuple[ArchitectureDependencyDirection, ...] = ()
    cycles: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if any(
            direction.evidence_class is not self.evidence_class
            for direction in self.directions
        ):
            raise ValueError("architecture topology contains a different evidence class")
        object.__setattr__(self, "directions", tuple(sorted(set(self.directions))))
        object.__setattr__(self, "cycles", tuple(sorted(set(self.cycles))))

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_class": self.evidence_class.value,
            "directions": [item.to_dict() for item in self.directions],
            "cycles": [list(cycle) for cycle in self.cycles],
        }


@dataclass(frozen=True, order=True, slots=True)
class ArchitectureDependencyPair:
    source_project: str
    target_project: str
    classification: ArchitectureDependencyPairClassification

    def to_dict(self) -> dict[str, str]:
        return {
            "source_project": self.source_project,
            "target_project": self.target_project,
            "classification": self.classification.value,
        }


def _empty_build_topology() -> ArchitectureDependencyTopology:
    return ArchitectureDependencyTopology(
        ArchitectureDependencyEvidenceClass.BUILD_MODULE,
    )


def _empty_import_topology() -> ArchitectureDependencyTopology:
    return ArchitectureDependencyTopology(
        ArchitectureDependencyEvidenceClass.SOURCE_IMPORT,
    )


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
    build_dependency_topology: ArchitectureDependencyTopology = field(
        default_factory=_empty_build_topology,
    )
    import_dependency_topology: ArchitectureDependencyTopology = field(
        default_factory=_empty_import_topology,
    )
    dependency_pair_classifications: tuple[ArchitectureDependencyPair, ...] = ()

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
            "build_dependency_topology": self.build_dependency_topology.to_dict(),
            "import_dependency_topology": self.import_dependency_topology.to_dict(),
            "dependency_pair_classifications": [
                item.to_dict() for item in self.dependency_pair_classifications
            ],
        }
