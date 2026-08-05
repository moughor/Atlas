from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any

from .context import WorkspaceSemanticContext


SEMANTIC_SNAPSHOT_SCHEMA_VERSION = 1
SEMANTIC_SNAPSHOT_FORMAT = "atlas-semantic-snapshot"


class SemanticSnapshotError(ValueError):
    """Raised when a semantic snapshot is invalid or incompatible."""


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@dataclass(frozen=True, slots=True)
class AtlasSemanticSnapshot:
    """Immutable deterministic semantic knowledge produced by Atlas."""

    schema_version: int
    workspace_fingerprint: str
    analyzer_version: str
    history_reference: int | str | None
    semantic_context: Mapping[str, Any]
    snapshot_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "semantic_context", MappingProxyType(dict(self.semantic_context)))

    @classmethod
    def create(
        cls,
        context: WorkspaceSemanticContext,
        *,
        workspace_fingerprint: str,
        analyzer_version: str,
        history_reference: int | str | None = None,
    ) -> AtlasSemanticSnapshot:
        _validate_non_empty_string(workspace_fingerprint, "workspace fingerprint")
        _validate_non_empty_string(analyzer_version, "analyzer version")
        _validate_history_reference(history_reference)
        payload = {
            "schema_version": SEMANTIC_SNAPSHOT_SCHEMA_VERSION,
            "workspace_fingerprint": workspace_fingerprint,
            "analyzer_version": analyzer_version,
            "history_reference": history_reference,
            "semantic_context": context.to_dict(),
        }
        try:
            snapshot_id = hashlib.sha256(
                canonical_json(payload).encode("utf-8")
            ).hexdigest()
        except (TypeError, ValueError) as exc:
            raise SemanticSnapshotError(
                "semantic snapshot must contain deterministic JSON data"
            ) from exc
        return cls(snapshot_id=snapshot_id, **payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "workspace_fingerprint": self.workspace_fingerprint,
            "analyzer_version": self.analyzer_version,
            "history_reference": self.history_reference,
            "semantic_context": dict(self.semantic_context),
        }

    def to_context(self) -> WorkspaceSemanticContext:
        return WorkspaceSemanticContext(dict(self.semantic_context))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> AtlasSemanticSnapshot:
        try:
            raw_schema = data["schema_version"]
            snapshot_id = data["snapshot_id"]
            workspace_fingerprint = data["workspace_fingerprint"]
            analyzer_version = data["analyzer_version"]
            history_reference = data.get("history_reference")
            semantic_context = data["semantic_context"]
        except (KeyError, TypeError, ValueError) as exc:
            raise SemanticSnapshotError("semantic snapshot is missing required fields") from exc
        if isinstance(raw_schema, bool) or not isinstance(raw_schema, int):
            raise SemanticSnapshotError("semantic snapshot schema must be an integer")
        _validate_non_empty_string(snapshot_id, "snapshot identifier")
        _validate_non_empty_string(workspace_fingerprint, "workspace fingerprint")
        _validate_non_empty_string(analyzer_version, "analyzer version")
        schema = raw_schema
        if schema != SEMANTIC_SNAPSHOT_SCHEMA_VERSION:
            raise SemanticSnapshotError(f"unsupported semantic snapshot schema: {schema}")
        if not isinstance(semantic_context, Mapping):
            raise SemanticSnapshotError("semantic_context must be an object")
        _validate_history_reference(history_reference)
        candidate = cls(
            schema,
            workspace_fingerprint,
            analyzer_version,
            history_reference,
            semantic_context,
            snapshot_id,
        )
        deterministic = dict(candidate.to_dict())
        deterministic.pop("snapshot_id")
        try:
            expected = hashlib.sha256(
                canonical_json(deterministic).encode("utf-8")
            ).hexdigest()
        except (TypeError, ValueError) as exc:
            raise SemanticSnapshotError(
                "semantic snapshot must contain deterministic JSON data"
            ) from exc
        if snapshot_id != expected:
            raise SemanticSnapshotError("semantic snapshot identifier mismatch")
        return candidate


def _validate_history_reference(value: object) -> None:
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, (int, str))
    ):
        raise SemanticSnapshotError(
            "history_reference must be an integer, string, or null"
        )


def _validate_non_empty_string(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SemanticSnapshotError(f"semantic snapshot {name} must not be empty")
