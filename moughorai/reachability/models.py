from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import json

from moughorai.semantic_evidence import ConfidenceTier, EvidenceIndex


class ReachabilityState(str, Enum):
    REACHABLE = "reachable"
    REACHABLE_TEST_ONLY = "reachable_test_only"
    EXTERNALLY_REACHABLE = "externally_reachable"
    FRAMEWORK_MANAGED = "framework_managed"
    REFLECTION_DISCOVERED = "reflection_discovered"
    SERVICE_LOADER_DISCOVERED = "service_loader_discovered"
    GENERATED_OR_ANNOTATION_MANAGED = "generated_or_annotation_managed"
    CONDITIONALLY_REACHABLE = "conditionally_reachable"
    UNUSED = "unused"
    LIKELY_DEAD = "likely_dead"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"


class RootCategory(str, Enum):
    APPLICATION = "application"
    TEST = "test"
    BUILD = "build"
    FRAMEWORK = "framework"
    PUBLIC_API = "public_api"
    SERVICE_LOADER = "service_loader"
    REFLECTION = "reflection"
    GENERATED = "generated"
    EXPLICIT = "explicit"
    CFG = "cfg"


class SourceClassification(str, Enum):
    PRODUCTION = "production"
    TEST = "test"
    GENERATED = "generated"
    VENDORED = "vendored"
    EXTERNAL = "external"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class CoverageStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True, order=True, slots=True)
class ReachabilitySeed:
    subject_id: str
    category: RootCategory
    project: str = ""
    scope: str = "repository"
    producer: str = "explicit-reachability-root"
    source_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    reliability: float = 1.0
    specificity: float = 1.0

    def __post_init__(self) -> None:
        if not self.subject_id.strip() or not self.producer.strip():
            raise ValueError("reachability roots require subject and producer")
        for name in ("reliability", "specificity"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        object.__setattr__(self, "source_refs", tuple(sorted(set(self.source_refs))))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    def to_dict(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "category": self.category.value,
            "project": self.project,
            "scope": self.scope,
            "producer": self.producer,
            "source_refs": list(self.source_refs),
            "limitations": list(self.limitations),
            "reliability": self.reliability,
            "specificity": self.specificity,
        }


@dataclass(frozen=True, order=True, slots=True)
class ReachabilityProtection:
    subject_id: str
    state: ReachabilityState
    producer: str
    project: str = ""
    language: str = "unknown"
    mechanism: str = "structured"
    source_classification: SourceClassification = SourceClassification.UNKNOWN
    source_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    reliability: float = 0.9
    specificity: float = 1.0

    _ALLOWED = frozenset({
        ReachabilityState.EXTERNALLY_REACHABLE,
        ReachabilityState.FRAMEWORK_MANAGED,
        ReachabilityState.REFLECTION_DISCOVERED,
        ReachabilityState.SERVICE_LOADER_DISCOVERED,
        ReachabilityState.GENERATED_OR_ANNOTATION_MANAGED,
        ReachabilityState.CONDITIONALLY_REACHABLE,
        ReachabilityState.UNREACHABLE,
    })

    def __post_init__(self) -> None:
        if self.state not in self._ALLOWED:
            raise ValueError(f"unsupported reachability protection state: {self.state.value}")
        if not self.subject_id.strip() or not self.producer.strip():
            raise ValueError("reachability protections require subject and producer")
        for name in ("reliability", "specificity"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        object.__setattr__(self, "source_refs", tuple(sorted(set(self.source_refs))))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    def to_dict(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "state": self.state.value,
            "producer": self.producer,
            "project": self.project,
            "language": self.language,
            "mechanism": self.mechanism,
            "source_classification": self.source_classification.value,
            "source_refs": list(self.source_refs),
            "limitations": list(self.limitations),
            "reliability": self.reliability,
            "specificity": self.specificity,
        }


@dataclass(frozen=True, order=True, slots=True)
class ProjectEvidence:
    project: str
    languages: tuple[str, ...] = ()
    roots: CoverageStatus = CoverageStatus.UNAVAILABLE
    calls: CoverageStatus = CoverageStatus.UNAVAILABLE
    cfg: CoverageStatus = CoverageStatus.UNAVAILABLE
    frameworks: CoverageStatus = CoverageStatus.UNAVAILABLE
    reflection: CoverageStatus = CoverageStatus.UNAVAILABLE
    service_loader: CoverageStatus = CoverageStatus.UNAVAILABLE
    generated: CoverageStatus = CoverageStatus.UNAVAILABLE
    external_api: CoverageStatus = CoverageStatus.UNAVAILABLE
    closed_world: bool = False
    failed: bool = False
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.project.strip():
            raise ValueError("project evidence requires a project")
        object.__setattr__(self, "languages", tuple(sorted(set(self.languages))))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    def to_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "languages": list(self.languages),
            "roots": self.roots.value,
            "calls": self.calls.value,
            "cfg": self.cfg.value,
            "frameworks": self.frameworks.value,
            "reflection": self.reflection.value,
            "service_loader": self.service_loader.value,
            "generated": self.generated.value,
            "external_api": self.external_api.value,
            "closed_world": self.closed_world,
            "failed": self.failed,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class ReachabilityEvidenceBundle:
    roots: tuple[ReachabilitySeed, ...] = ()
    protections: tuple[ReachabilityProtection, ...] = ()
    projects: tuple[ProjectEvidence, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "roots", tuple(sorted(set(self.roots))))
        object.__setattr__(self, "protections", tuple(sorted(set(self.protections))))
        object.__setattr__(self, "projects", tuple(sorted(set(self.projects))))

    def to_dict(self) -> dict[str, object]:
        return {
            "roots": [item.to_dict() for item in self.roots],
            "protections": [item.to_dict() for item in self.protections],
            "projects": [item.to_dict() for item in self.projects],
        }


@dataclass(frozen=True, slots=True)
class ReachabilityConfiguration:
    max_path_depth: int = 64
    max_traversal_nodes: int = 1_000_000
    dead_code_threshold: float = 0.8

    def __post_init__(self) -> None:
        if self.max_path_depth < 1 or self.max_traversal_nodes < 1:
            raise ValueError("reachability bounds must be positive")
        if not 0.0 <= self.dead_code_threshold <= 1.0:
            raise ValueError("dead-code threshold must be between 0 and 1")

    def to_dict(self) -> dict[str, object]:
        return {
            "max_path_depth": self.max_path_depth,
            "max_traversal_nodes": self.max_traversal_nodes,
            "dead_code_threshold": self.dead_code_threshold,
        }


@dataclass(frozen=True, order=True, slots=True)
class ReachabilityRoot:
    subject_id: str
    category: RootCategory
    project: str
    scope: str
    confidence: float
    confidence_tier: ConfidenceTier
    evidence_ids: tuple[str, ...]
    limitations: tuple[str, ...] = ()
    producer_version: str = "atlas-pr131/1"

    def __post_init__(self) -> None:
        if not self.subject_id.strip() or not self.evidence_ids:
            raise ValueError("reachability roots require subject and evidence")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("root confidence must be between 0 and 1")
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    def to_dict(self) -> dict[str, object]:
        return {
            "subject_id": self.subject_id,
            "category": self.category.value,
            "project": self.project,
            "scope": self.scope,
            "confidence": self.confidence,
            "confidence_tier": self.confidence_tier.value,
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
            "producer_version": self.producer_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ReachabilityRoot:
        return cls(
            str(value["subject_id"]), RootCategory(str(value["category"])),
            str(value.get("project", "")), str(value.get("scope", "repository")),
            float(value["confidence"]), ConfidenceTier(str(value["confidence_tier"])),
            tuple(map(str, value.get("evidence_ids", ()))),
            tuple(map(str, value.get("limitations", ()))),
            str(value.get("producer_version", "atlas-pr131/1")),
        )


@dataclass(frozen=True, order=True, slots=True)
class ReachabilityPath:
    root_subject_id: str
    target_subject_id: str
    relationship_sequence: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    scope: str = "production"
    truncated: bool = False
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    def to_dict(self) -> dict[str, object]:
        return {
            "root_subject_id": self.root_subject_id,
            "target_subject_id": self.target_subject_id,
            "relationship_sequence": list(self.relationship_sequence),
            "evidence_ids": list(self.evidence_ids),
            "scope": self.scope,
            "truncated": self.truncated,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ReachabilityPath:
        return cls(
            str(value["root_subject_id"]), str(value["target_subject_id"]),
            tuple(map(str, value.get("relationship_sequence", ()))),
            tuple(map(str, value.get("evidence_ids", ()))),
            str(value.get("scope", "production")), bool(value.get("truncated", False)),
            tuple(map(str, value.get("limitations", ()))),
        )


@dataclass(frozen=True, order=True, slots=True)
class ReachabilityFinding:
    subject_id: str
    symbol_kind: str
    language: str
    project: str
    source_classification: SourceClassification
    state: ReachabilityState
    confidence: float
    confidence_tier: ConfidenceTier
    evidence_ids: tuple[str, ...]
    root_categories: tuple[RootCategory, ...] = ()
    production_reachable: bool = False
    test_reachable: bool = False
    limitations: tuple[str, ...] = ()
    producer_version: str = "atlas-pr131/1"

    def __post_init__(self) -> None:
        if not self.subject_id.strip() or not self.evidence_ids:
            raise ValueError("reachability findings require subject and evidence")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("finding confidence must be between 0 and 1")
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        object.__setattr__(self, "root_categories", tuple(sorted(set(self.root_categories), key=lambda item: item.value)))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    @property
    def dead_code_candidate(self) -> bool:
        return self.state in {ReachabilityState.LIKELY_DEAD, ReachabilityState.UNREACHABLE}

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "subject_id": self.subject_id,
            "symbol_kind": self.symbol_kind,
            "language": self.language,
            "project": self.project,
            "state": self.state.value,
            "confidence": self.confidence,
            "confidence_tier": self.confidence_tier.value,
            "evidence_ids": list(self.evidence_ids),
            "production_reachable": self.production_reachable,
            "test_reachable": self.test_reachable,
        }
        if self.source_classification is not SourceClassification.UNKNOWN:
            result["source_classification"] = self.source_classification.value
        if self.root_categories:
            result["root_categories"] = [item.value for item in self.root_categories]
        if self.limitations:
            result["limitations"] = list(self.limitations)
        if self.producer_version != "atlas-pr131/1":
            result["producer_version"] = self.producer_version
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ReachabilityFinding:
        return cls(
            str(value["subject_id"]), str(value["symbol_kind"]),
            str(value.get("language", "unknown")), str(value.get("project", "")),
            SourceClassification(str(value.get("source_classification", "unknown"))),
            ReachabilityState(str(value["state"])), float(value["confidence"]),
            ConfidenceTier(str(value["confidence_tier"])),
            tuple(map(str, value.get("evidence_ids", ()))),
            tuple(RootCategory(str(item)) for item in value.get("root_categories", ())),
            bool(value.get("production_reachable", False)),
            bool(value.get("test_reachable", False)),
            tuple(map(str, value.get("limitations", ()))),
            str(value.get("producer_version", "atlas-pr131/1")),
        )


@dataclass(frozen=True, order=True, slots=True)
class ProjectReachabilityCoverage:
    project: str
    languages: tuple[str, ...]
    status: CoverageStatus
    roots: CoverageStatus
    calls: CoverageStatus
    cfg: CoverageStatus
    frameworks: CoverageStatus
    reflection: CoverageStatus
    service_loader: CoverageStatus
    generated: CoverageStatus
    external_api: CoverageStatus
    closed_world: bool
    analyzed_subjects: int
    state_counts: tuple[tuple[str, int], ...] = ()
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "languages", tuple(sorted(set(self.languages))))
        object.__setattr__(self, "state_counts", tuple(sorted(self.state_counts)))
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    def to_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "languages": list(self.languages),
            "status": self.status.value,
            "roots": self.roots.value,
            "calls": self.calls.value,
            "cfg": self.cfg.value,
            "frameworks": self.frameworks.value,
            "reflection": self.reflection.value,
            "service_loader": self.service_loader.value,
            "generated": self.generated.value,
            "external_api": self.external_api.value,
            "closed_world": self.closed_world,
            "analyzed_subjects": self.analyzed_subjects,
            "state_counts": dict(self.state_counts),
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ProjectReachabilityCoverage:
        counts = value.get("state_counts", {})
        return cls(
            str(value["project"]), tuple(map(str, value.get("languages", ()))),
            CoverageStatus(str(value["status"])), CoverageStatus(str(value["roots"])),
            CoverageStatus(str(value["calls"])), CoverageStatus(str(value["cfg"])),
            CoverageStatus(str(value["frameworks"])), CoverageStatus(str(value["reflection"])),
            CoverageStatus(str(value["service_loader"])), CoverageStatus(str(value["generated"])),
            CoverageStatus(str(value["external_api"])), bool(value.get("closed_world", False)),
            int(value.get("analyzed_subjects", 0)),
            tuple(sorted((str(key), int(item)) for key, item in counts.items())) if isinstance(counts, Mapping) else (),
            tuple(map(str, value.get("evidence_ids", ()))),
            tuple(map(str, value.get("limitations", ()))),
        )


@dataclass(frozen=True, order=True, slots=True)
class ReachabilityCapability:
    name: str
    status: CoverageStatus
    scopes: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "scopes", tuple(sorted(set(self.scopes))))
        object.__setattr__(self, "evidence_ids", tuple(sorted(set(self.evidence_ids))))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status.value,
            "scopes": list(self.scopes),
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ReachabilityCapability:
        return cls(
            str(value["name"]), CoverageStatus(str(value["status"])),
            tuple(map(str, value.get("scopes", ()))),
            tuple(map(str, value.get("evidence_ids", ()))),
            tuple(map(str, value.get("limitations", ()))),
        )


@dataclass(frozen=True, slots=True)
class ReachabilityCoverage:
    projects: tuple[ProjectReachabilityCoverage, ...]
    languages_supported: tuple[str, ...]
    languages_partial: tuple[str, ...]
    subject_counts: tuple[tuple[str, int], ...]
    status: CoverageStatus
    traversal_truncated: bool = False
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "projects", tuple(sorted(self.projects)))
        object.__setattr__(self, "languages_supported", tuple(sorted(set(self.languages_supported))))
        object.__setattr__(self, "languages_partial", tuple(sorted(set(self.languages_partial))))
        object.__setattr__(self, "subject_counts", tuple(sorted(self.subject_counts)))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    def to_dict(self) -> dict[str, object]:
        return {
            "projects": [item.to_dict() for item in self.projects],
            "languages_supported": list(self.languages_supported),
            "languages_partial": list(self.languages_partial),
            "subject_counts": dict(self.subject_counts),
            "status": self.status.value,
            "traversal_truncated": self.traversal_truncated,
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ReachabilityCoverage:
        counts = value.get("subject_counts", {})
        return cls(
            tuple(ProjectReachabilityCoverage.from_dict(item) for item in value.get("projects", ()) if isinstance(item, Mapping)),
            tuple(map(str, value.get("languages_supported", ()))),
            tuple(map(str, value.get("languages_partial", ()))),
            tuple(sorted((str(key), int(item)) for key, item in counts.items())) if isinstance(counts, Mapping) else (),
            CoverageStatus(str(value["status"])),
            bool(value.get("traversal_truncated", False)),
            tuple(map(str, value.get("limitations", ()))),
        )


@dataclass(frozen=True, slots=True)
class DeadCodeReport:
    roots: tuple[ReachabilityRoot, ...]
    findings: tuple[ReachabilityFinding, ...]
    paths: tuple[ReachabilityPath, ...]
    coverage: ReachabilityCoverage
    capabilities: tuple[ReachabilityCapability, ...]
    evidence_index: EvidenceIndex
    input_fingerprint: str
    graph_digest: str
    configuration_fingerprint: str
    snapshot_lineage: str
    limitations: tuple[str, ...] = ()
    producer_version: str = "atlas-pr131/1"
    schema_version: int = 1

    def __post_init__(self) -> None:
        for name in ("input_fingerprint", "graph_digest", "configuration_fingerprint", "snapshot_lineage"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        object.__setattr__(self, "roots", tuple(sorted(self.roots)))
        object.__setattr__(self, "findings", tuple(sorted(self.findings)))
        object.__setattr__(self, "paths", tuple(sorted(self.paths)))
        object.__setattr__(self, "capabilities", tuple(sorted(self.capabilities)))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    @property
    def dead_code_candidates(self) -> tuple[ReachabilityFinding, ...]:
        return tuple(item for item in self.findings if item.dead_code_candidate)

    @property
    def statistics(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.state.value] = counts.get(finding.state.value, 0) + 1
        return {
            "analyzed_symbols": len(self.findings),
            "roots": len(self.roots),
            "paths": len(self.paths),
            "dead_code_candidates": len(self.dead_code_candidates),
            "states": dict(sorted(counts.items())),
        }

    def to_dict(self, *, grouped: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "producer_version": self.producer_version,
            "snapshot_lineage": self.snapshot_lineage,
            "input_fingerprint": self.input_fingerprint,
            "graph_digest": self.graph_digest,
            "configuration_fingerprint": self.configuration_fingerprint,
            "roots": [item.to_dict() for item in self.roots],
            "paths": [item.to_dict() for item in self.paths],
            "coverage": self.coverage.to_dict(),
            "capabilities": [item.to_dict() for item in self.capabilities],
            "evidence_index": self.evidence_index.to_dict(),
            "limitations": list(self.limitations),
            "statistics": self.statistics,
        }
        if grouped:
            result["serialization"] = "grouped-findings-v1"
            result["finding_groups"] = self._finding_groups()
        else:
            result["findings"] = [item.to_dict() for item in self.findings]
        return result

    def _finding_groups(self) -> list[dict[str, object]]:
        groups: dict[str, tuple[dict[str, object], list[str]]] = {}
        for finding in self.findings:
            shared = finding.to_dict()
            subject_id = str(shared.pop("subject_id"))
            prefix, separator, remainder = subject_id.partition(":")
            subject_prefix = f"{prefix}:" if separator else ""
            shared["subject_id_prefix"] = subject_prefix
            key = json.dumps(
                shared,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            if key not in groups:
                groups[key] = (shared, [])
            groups[key][1].append(remainder if separator else subject_id)
        return [
            {**shared, "subject_ids": sorted(subject_ids)}
            for _, (shared, subject_ids) in sorted(groups.items())
        ]

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> DeadCodeReport:
        if int(value.get("schema_version", 1)) != 1:
            raise ValueError("unsupported reachability report schema")
        raw_coverage = value.get("coverage", {})
        raw_evidence = value.get("evidence_index", {})
        if not isinstance(raw_coverage, Mapping) or not isinstance(raw_evidence, Mapping):
            raise TypeError("reachability coverage and evidence index must be mappings")
        raw_findings = list(value.get("findings", ()))
        for group in value.get("finding_groups", ()):
            if not isinstance(group, Mapping):
                continue
            shared = {
                key: item
                for key, item in group.items()
                if key not in {"subject_ids", "subject_id_prefix"}
            }
            prefix = str(group.get("subject_id_prefix", ""))
            raw_findings.extend(
                {**shared, "subject_id": f"{prefix}{subject_id}"}
                for subject_id in group.get("subject_ids", ())
            )
        return cls(
            tuple(ReachabilityRoot.from_dict(item) for item in value.get("roots", ()) if isinstance(item, Mapping)),
            tuple(ReachabilityFinding.from_dict(item) for item in raw_findings if isinstance(item, Mapping)),
            tuple(ReachabilityPath.from_dict(item) for item in value.get("paths", ()) if isinstance(item, Mapping)),
            ReachabilityCoverage.from_dict(raw_coverage),
            tuple(ReachabilityCapability.from_dict(item) for item in value.get("capabilities", ()) if isinstance(item, Mapping)),
            EvidenceIndex.from_dict(raw_evidence),
            str(value["input_fingerprint"]), str(value["graph_digest"]),
            str(value["configuration_fingerprint"]), str(value["snapshot_lineage"]),
            tuple(map(str, value.get("limitations", ()))),
            str(value.get("producer_version", "atlas-pr131/1")),
            int(value.get("schema_version", 1)),
        )
