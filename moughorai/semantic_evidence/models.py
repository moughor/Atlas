from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import hashlib
import json


class EvidenceKind(str, Enum):
    GRAPH_EDGE = "graph_edge"
    GRAPH_NODE = "graph_node"
    SEMANTIC_FACT = "semantic_fact"
    ANALYSIS_RESULT = "analysis_result"
    REPOSITORY_METADATA = "repository_metadata"


@dataclass(frozen=True, order=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    kind: EvidenceKind
    subject_id: str
    producer: str
    snapshot_id: str
    source_refs: tuple[str, ...] = ()
    scope: str = "repository"
    language: str = "unknown"
    detail: tuple[tuple[str, str], ...] = ()
    limitations: tuple[str, ...] = ()
    reliability: float = 1.0
    specificity: float = 1.0

    def __post_init__(self) -> None:
        for name in ("evidence_id", "subject_id", "producer", "snapshot_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must not be empty")
        for name in ("reliability", "specificity"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        object.__setattr__(self, "source_refs", tuple(sorted(set(self.source_refs))))
        object.__setattr__(self, "detail", tuple(sorted(self.detail)))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))

    @classmethod
    def create(
        cls,
        kind: EvidenceKind,
        subject_id: str,
        producer: str,
        snapshot_id: str,
        *,
        source_refs: tuple[str, ...] = (),
        scope: str = "repository",
        language: str = "unknown",
        detail: Mapping[str, object] | tuple[tuple[str, str], ...] = (),
        limitations: tuple[str, ...] = (),
        reliability: float = 1.0,
        specificity: float = 1.0,
    ) -> EvidenceRecord:
        normalized_detail = (
            tuple(sorted((str(key), str(value)) for key, value in detail.items()))
            if isinstance(detail, Mapping)
            else tuple(sorted((str(key), str(value)) for key, value in detail))
        )
        identity = {
            "kind": kind.value,
            "subject_id": subject_id,
            "producer": producer,
            "snapshot_id": snapshot_id,
            "source_refs": sorted(set(source_refs)),
            "scope": scope,
            "language": language,
            "detail": dict(normalized_detail),
            "limitations": sorted(set(limitations)),
            "reliability": reliability,
            "specificity": specificity,
        }
        digest = hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return cls(
            f"evidence:{digest}",
            kind,
            subject_id,
            producer,
            snapshot_id,
            tuple(source_refs),
            scope,
            language,
            normalized_detail,
            limitations,
            reliability,
            specificity,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "kind": self.kind.value,
            "subject_id": self.subject_id,
            "producer": self.producer,
            "snapshot_id": self.snapshot_id,
            "source_refs": list(self.source_refs),
            "scope": self.scope,
            "language": self.language,
            "detail": dict(self.detail),
            "limitations": list(self.limitations),
            "reliability": self.reliability,
            "specificity": self.specificity,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> EvidenceRecord:
        raw_detail = value.get("detail", {})
        detail = (
            tuple(sorted((str(key), str(item)) for key, item in raw_detail.items()))
            if isinstance(raw_detail, Mapping)
            else ()
        )
        return cls(
            str(value["evidence_id"]),
            EvidenceKind(str(value["kind"])),
            str(value["subject_id"]),
            str(value["producer"]),
            str(value["snapshot_id"]),
            tuple(map(str, value.get("source_refs", ()))),
            str(value.get("scope", "repository")),
            str(value.get("language", "unknown")),
            detail,
            tuple(map(str, value.get("limitations", ()))),
            float(value.get("reliability", 1.0)),
            float(value.get("specificity", 1.0)),
        )
