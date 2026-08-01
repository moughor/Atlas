from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import PurePosixPath

from moughorai.knowledge_graph import KnowledgeKind
from moughorai.repository_report.safety import contains_absolute_path


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


class SubjectMatchBasis(str, Enum):
    CANONICAL_ID = "canonical_id"
    QUALIFIED_NAME = "qualified_name"
    NORMALIZED_NAME = "normalized_name"
    INTENT = "intent"
    NONE = "none"


_KNOWLEDGE_KIND_ORDER = {
    kind: index for index, kind in enumerate(KnowledgeKind)
}


@dataclass(frozen=True, slots=True)
class SubjectQuery:
    identifier: str
    kind: KnowledgeKind | None = None
    project: str | None = None
    language: str | None = None
    path: str | None = None

    def __post_init__(self) -> None:
        identifier = self.identifier.strip()
        if not identifier:
            raise ValueError("subject query identifier must not be empty")
        if len(identifier) > 4_096:
            raise ValueError("subject query identifier is too long")
        object.__setattr__(self, "identifier", identifier)
        if isinstance(self.kind, str):
            object.__setattr__(self, "kind", KnowledgeKind(self.kind))
        for name in ("project", "language"):
            value = getattr(self, name)
            object.__setattr__(self, name, value.strip() if value and value.strip() else None)
        if self.path is not None:
            object.__setattr__(self, "path", _relative_path(self.path))
        if contains_absolute_path(self.to_dict()):
            raise ValueError("subject queries must not contain absolute paths")

    def to_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "kind": self.kind.value if self.kind is not None else None,
            "project": self.project,
            "language": self.language,
            "path": self.path,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SubjectQuery:
        raw_kind = value.get("kind")
        return cls(
            str(value.get("identifier", "")),
            KnowledgeKind(str(raw_kind)) if raw_kind is not None else None,
            str(value["project"]) if value.get("project") is not None else None,
            str(value["language"]) if value.get("language") is not None else None,
            str(value["path"]) if value.get("path") is not None else None,
        )


@dataclass(frozen=True, slots=True)
class SubjectCandidate:
    canonical_id: str
    kind: KnowledgeKind
    name: str
    qualified_name: str
    project: str | None = None
    language: str = "unknown"
    path: str | None = None
    project_scopes: tuple[str, ...] = ()
    match_basis: SubjectMatchBasis = SubjectMatchBasis.NONE
    _graph_id: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        if isinstance(self.kind, str):
            object.__setattr__(self, "kind", KnowledgeKind(self.kind))
        if isinstance(self.match_basis, str):
            object.__setattr__(
                self, "match_basis", SubjectMatchBasis(self.match_basis),
            )
        for name in ("canonical_id", "name", "qualified_name", "language"):
            normalized = getattr(self, name).strip()
            if not normalized:
                raise ValueError(f"subject candidate {name} must not be empty")
            object.__setattr__(self, name, normalized)
        project = self.project.strip() if self.project else None
        object.__setattr__(self, "project", project or None)
        scopes = tuple(sorted({item.strip() for item in self.project_scopes if item.strip()}))
        object.__setattr__(self, "project_scopes", scopes)
        if self.path is not None:
            object.__setattr__(self, "path", _relative_path(self.path))
        if contains_absolute_path(self.to_dict()):
            raise ValueError("subject candidates must not contain absolute paths")

    @property
    def graph_id(self) -> str:
        """Internal PR129 identity; excluded from serialized AI context."""

        return self._graph_id or self.canonical_id

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_id": self.canonical_id,
            "kind": self.kind.value,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "project": self.project,
            "language": self.language,
            "path": self.path,
            "project_scopes": list(self.project_scopes),
            "match_basis": self.match_basis.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SubjectCandidate:
        canonical_id = str(value.get("canonical_id", ""))
        return cls(
            canonical_id,
            KnowledgeKind(str(value.get("kind", KnowledgeKind.SYMBOL.value))),
            str(value.get("name", "")),
            str(value.get("qualified_name", "")),
            str(value["project"]) if value.get("project") is not None else None,
            str(value.get("language", "unknown")),
            str(value["path"]) if value.get("path") is not None else None,
            _strings(value.get("project_scopes")),
            SubjectMatchBasis(str(value.get("match_basis", SubjectMatchBasis.NONE.value))),
            canonical_id,
        )


@dataclass(frozen=True, slots=True)
class SubjectResolution:
    query: SubjectQuery
    status: ResolutionStatus
    subject: SubjectCandidate | None
    candidates: tuple[SubjectCandidate, ...]
    total_candidate_count: int
    omitted_candidate_count: int
    match_basis: SubjectMatchBasis = SubjectMatchBasis.NONE
    graph_digest: str = "unavailable"
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "total_candidate_count",
            _strict_integer(self.total_candidate_count, "total candidate count"),
        )
        object.__setattr__(
            self,
            "omitted_candidate_count",
            _strict_integer(self.omitted_candidate_count, "omitted candidate count"),
        )
        if isinstance(self.status, str):
            object.__setattr__(self, "status", ResolutionStatus(self.status))
        if isinstance(self.match_basis, str):
            object.__setattr__(
                self, "match_basis", SubjectMatchBasis(self.match_basis),
            )
        candidates = tuple(sorted(
            self.candidates,
            key=lambda item: (
                item.qualified_name.casefold(),
                item.qualified_name,
                _KNOWLEDGE_KIND_ORDER[item.kind],
                item.project or "",
                item.language,
                item.name,
                item.canonical_id,
            ),
        ))
        if len({item.canonical_id for item in candidates}) != len(candidates):
            raise ValueError("subject resolution candidate IDs must be unique")
        object.__setattr__(self, "candidates", candidates)
        if self.total_candidate_count < 0 or self.omitted_candidate_count < 0:
            raise ValueError("subject resolution counts must not be negative")
        if self.total_candidate_count != len(self.candidates) + self.omitted_candidate_count:
            raise ValueError("subject resolution candidate counts are inconsistent")
        if self.status is ResolutionStatus.RESOLVED:
            if self.subject is None or self.candidates:
                raise ValueError("resolved subjects require one subject and no candidates")
            if self.match_basis is SubjectMatchBasis.NONE:
                raise ValueError("resolved subjects require a match basis")
            if self.subject.match_basis is not self.match_basis:
                raise ValueError("resolved subject match basis is inconsistent")
        elif self.subject is not None:
            raise ValueError("unresolved subjects must not contain a selected subject")
        if self.status is ResolutionStatus.AMBIGUOUS and self.total_candidate_count < 2:
            raise ValueError("ambiguous subject resolution requires multiple candidates")
        if self.status is not ResolutionStatus.AMBIGUOUS and self.candidates:
            raise ValueError("only ambiguous subject resolution may contain candidates")
        if self.status is ResolutionStatus.AMBIGUOUS:
            if self.match_basis is SubjectMatchBasis.NONE:
                raise ValueError("ambiguous subjects require a match basis")
            if any(item.match_basis is not self.match_basis for item in self.candidates):
                raise ValueError("ambiguous candidate match basis is inconsistent")
        elif self.status is not ResolutionStatus.RESOLVED and self.match_basis is not SubjectMatchBasis.NONE:
            raise ValueError("unmatched subjects must not declare a match basis")
        if not self.graph_digest.strip():
            raise ValueError("subject resolution graph digest must not be empty")
        object.__setattr__(
            self,
            "limitations",
            tuple(sorted({item.strip() for item in self.limitations if item.strip()})),
        )
        if contains_absolute_path(self.to_dict()):
            raise ValueError("subject resolutions must not contain absolute paths")

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query.to_dict(),
            "status": self.status.value,
            "subject": self.subject.to_dict() if self.subject is not None else None,
            "candidates": [item.to_dict() for item in self.candidates],
            "total_candidate_count": self.total_candidate_count,
            "included_candidate_count": len(self.candidates),
            "omitted_candidate_count": self.omitted_candidate_count,
            "match_basis": self.match_basis.value,
            "graph_digest": self.graph_digest,
            "limitations": list(self.limitations),
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> SubjectResolution:
        raw_query = value.get("query")
        raw_subject = value.get("subject")
        if not isinstance(raw_query, Mapping):
            raise TypeError("subject resolution query must be an object")
        candidates = tuple(
            SubjectCandidate.from_dict(item) for item in _mapping_items(value.get("candidates"))
        )
        raw_included = value.get("included_candidate_count")
        if raw_included is not None and (
            _strict_integer(raw_included, "included candidate count") != len(candidates)
        ):
            raise ValueError("subject resolution included candidate count is inconsistent")
        return cls(
            SubjectQuery.from_dict(raw_query),
            ResolutionStatus(str(value.get("status", ResolutionStatus.UNAVAILABLE.value))),
            SubjectCandidate.from_dict(raw_subject) if isinstance(raw_subject, Mapping) else None,
            candidates,
            _strict_integer(
                value.get("total_candidate_count", 0), "total candidate count"
            ),
            _strict_integer(
                value.get("omitted_candidate_count", 0), "omitted candidate count"
            ),
            SubjectMatchBasis(str(value.get("match_basis", SubjectMatchBasis.NONE.value))),
            str(value.get("graph_digest", "unavailable")),
            _strings(value.get("limitations")),
        )


def _relative_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or contains_absolute_path(normalized)
    ):
        raise ValueError("subject path constraints must be workspace-relative")
    return path.as_posix()


def _mapping_items(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(sorted({str(item) for item in value if str(item).strip()}))


def _strict_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"subject resolution {name} must be an integer")
    return value
