"""Deterministic query-time semantic snapshot discovery and registration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import json
import os
from pathlib import Path
import tempfile

from moughorai.measurement import MeasurementSession
from moughorai.workspace import Workspace

from .models import AtlasSemanticSnapshot, SemanticSnapshotError
from .store import SemanticSnapshotStore


ACTIVE_SNAPSHOT_FORMAT = "atlas-active-semantic-snapshot"
ACTIVE_SNAPSHOT_SCHEMA_VERSION = 1
ACTIVE_SNAPSHOT_REGISTRATION = Path(".atlas") / "active-snapshot.json"
MAXIMUM_ACTIVE_REGISTRATION_BYTES = 64 * 1024


class SnapshotResolutionMethod(str, Enum):
    EXPLICIT = "explicit"
    CONFIGURED_ACTIVE = "configured-active"
    WORKSPACE_DEFAULT = "workspace-default"


@dataclass(frozen=True, slots=True)
class SnapshotResolution:
    snapshot: AtlasSemanticSnapshot
    snapshot_path: Path
    method: SnapshotResolutionMethod
    workspace_root: Path
    explicit: bool
    validated: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, AtlasSemanticSnapshot):
            raise TypeError("snapshot resolution requires a semantic snapshot")
        path = self.snapshot_path.expanduser().resolve()
        root = self.workspace_root.expanduser().resolve()
        if not isinstance(self.method, SnapshotResolutionMethod):
            raise TypeError("snapshot resolution method is invalid")
        if not isinstance(self.explicit, bool) or not isinstance(self.validated, bool):
            raise TypeError("snapshot resolution flags must be booleans")
        if not self.validated:
            raise ValueError("an unvalidated snapshot cannot be resolved")
        object.__setattr__(self, "snapshot_path", path)
        object.__setattr__(self, "workspace_root", root)

    def to_dict(self) -> dict[str, object]:
        return {
            "snapshot_path": self.snapshot_path.as_posix(),
            "snapshot_id": self.snapshot.snapshot_id,
            "resolution_method": self.method.value,
            "workspace_root": self.workspace_root.as_posix(),
            "explicit": self.explicit,
            "validated": self.validated,
        }


@dataclass(frozen=True, slots=True)
class _RegisteredSnapshot:
    path: Path
    snapshot_id: str


class SnapshotResolver:
    """Resolve one verified query snapshot without discovery or source scanning."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        measurement: MeasurementSession | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.workspace = Workspace(self.workspace_root, ())
        self.store = SemanticSnapshotStore(
            self.workspace,
            measurement=measurement,
        )
        self.registration_path = (
            self.workspace_root / ACTIVE_SNAPSHOT_REGISTRATION
        )

    def resolve(
        self,
        explicit_snapshot: str | Path | None = None,
    ) -> SnapshotResolution:
        if explicit_snapshot is not None:
            target = Path(explicit_snapshot).expanduser().resolve()
            return self._load(
                target,
                SnapshotResolutionMethod.EXPLICIT,
                explicit=True,
                expected_snapshot_id=None,
            )

        registered = self._read_registration()
        if registered is not None:
            return self._load(
                registered.path,
                SnapshotResolutionMethod.CONFIGURED_ACTIVE,
                explicit=False,
                expected_snapshot_id=registered.snapshot_id,
            )

        if self.store.latest_path.is_file():
            return self._load(
                self.store.latest_path,
                SnapshotResolutionMethod.WORKSPACE_DEFAULT,
                explicit=False,
                expected_snapshot_id=None,
            )
        if self.store.latest_path.exists():
            raise SemanticSnapshotError(
                "semantic snapshot invalid: canonical workspace snapshot path is "
                f"not a file: {self.store.latest_path}; workspace root considered: "
                f"{self.workspace_root}; --snapshot supplied: false"
            )
        raise SemanticSnapshotError(
            "semantic snapshot not found: no semantic snapshot is available for "
            f"workspace {self.workspace_root}; canonical expected path: "
            f"{self.store.latest_path}; --snapshot supplied: false; run analyze, "
            "provide --snapshot, or register one with 'atlas snapshot activate'"
        )

    def activate(self, snapshot_path: str | Path) -> SnapshotResolution:
        """Validate and atomically register exactly one active snapshot."""

        selected = self._load(
            Path(snapshot_path).expanduser().resolve(),
            SnapshotResolutionMethod.EXPLICIT,
            explicit=True,
            expected_snapshot_id=None,
        )
        payload = {
            "format": ACTIVE_SNAPSHOT_FORMAT,
            "schema_version": ACTIVE_SNAPSHOT_SCHEMA_VERSION,
            "workspace_root": self.workspace_root.as_posix(),
            "snapshots": [{
                "path": selected.snapshot_path.as_posix(),
                "snapshot_id": selected.snapshot.snapshot_id,
            }],
        }
        text = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ) + "\n"
        self.registration_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=self.registration_path.name + ".",
            suffix=".tmp",
            dir=self.registration_path.parent,
        )
        temporary_path = Path(temporary)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.registration_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        return SnapshotResolution(
            selected.snapshot,
            selected.snapshot_path,
            SnapshotResolutionMethod.CONFIGURED_ACTIVE,
            self.workspace_root,
            explicit=False,
        )

    def _load(
        self,
        target: Path,
        method: SnapshotResolutionMethod,
        *,
        explicit: bool,
        expected_snapshot_id: str | None,
    ) -> SnapshotResolution:
        supplied = str(explicit).lower()
        if not target.exists():
            authority = (
                "explicit --snapshot"
                if method is SnapshotResolutionMethod.EXPLICIT
                else "configured active snapshot"
            )
            raise SemanticSnapshotError(
                f"semantic snapshot not found: {authority} path does not exist: "
                f"{target}; workspace root considered: {self.workspace_root}; "
                f"canonical expected path: {self.store.latest_path}; "
                f"--snapshot supplied: {supplied}; the selected authority does not "
                "fall back"
            )
        if not target.is_file():
            raise SemanticSnapshotError(
                f"semantic snapshot invalid: expected a file at {target}; workspace "
                f"root considered: {self.workspace_root}; --snapshot supplied: "
                f"{supplied}; the selected authority does not fall back"
            )
        try:
            loaded = self.store.load(target)
        except SemanticSnapshotError as exc:
            raise SemanticSnapshotError(
                f"semantic snapshot invalid: {target} could not be verified "
                f"({exc}); workspace root considered: {self.workspace_root}; "
                f"--snapshot supplied: {supplied}; the selected authority does not "
                "fall back"
            ) from exc
        if loaded is None:
            raise SemanticSnapshotError(
                f"semantic snapshot not found: {target}; workspace root considered: "
                f"{self.workspace_root}; --snapshot supplied: {supplied}; the "
                "selected authority does not fall back"
            )
        if (
            expected_snapshot_id is not None
            and loaded.snapshot_id != expected_snapshot_id
        ):
            raise SemanticSnapshotError(
                "semantic snapshot invalid: configured active snapshot identity "
                f"mismatch at {target}; expected {expected_snapshot_id}, loaded "
                f"{loaded.snapshot_id}; reactivate the intended snapshot"
            )
        return SnapshotResolution(
            loaded,
            target,
            method,
            self.workspace_root,
            explicit=explicit,
        )

    def _read_registration(self) -> _RegisteredSnapshot | None:
        target = self.registration_path
        if not target.exists():
            return None
        if not target.is_file():
            raise SemanticSnapshotError(
                f"semantic snapshot registration invalid: expected a file at {target}"
            )
        try:
            if target.stat().st_size > MAXIMUM_ACTIVE_REGISTRATION_BYTES:
                raise SemanticSnapshotError(
                    "semantic snapshot registration invalid: active registration "
                    "is oversized"
                )
            raw = json.loads(
                target.read_text(encoding="utf-8"),
                parse_constant=self._reject_non_finite,
            )
        except SemanticSnapshotError:
            raise
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise SemanticSnapshotError(
                f"semantic snapshot registration invalid: cannot read {target} "
                f"({type(exc).__name__})"
            ) from exc
        if not isinstance(raw, Mapping):
            raise SemanticSnapshotError(
                "semantic snapshot registration invalid: root must be an object"
            )
        raw_schema = raw.get("schema_version")
        if (
            raw.get("format") != ACTIVE_SNAPSHOT_FORMAT
            or isinstance(raw_schema, bool)
            or not isinstance(raw_schema, int)
            or raw_schema != ACTIVE_SNAPSHOT_SCHEMA_VERSION
        ):
            raise SemanticSnapshotError(
                "semantic snapshot registration invalid: format or schema is unsupported"
            )
        registered_root = raw.get("workspace_root")
        if not isinstance(registered_root, str) or not registered_root.strip():
            raise SemanticSnapshotError(
                "semantic snapshot registration invalid: workspace root is missing"
            )
        registered_root_path = Path(registered_root).expanduser()
        if not registered_root_path.is_absolute():
            raise SemanticSnapshotError(
                "semantic snapshot registration invalid: workspace root must be absolute"
            )
        if not self._same_path(registered_root_path, self.workspace_root):
            raise SemanticSnapshotError(
                "semantic snapshot registration invalid: registration belongs to "
                f"workspace {registered_root}, not {self.workspace_root}"
            )
        snapshots = raw.get("snapshots")
        if (
            not isinstance(snapshots, Sequence)
            or isinstance(snapshots, (str, bytes, bytearray))
        ):
            raise SemanticSnapshotError(
                "semantic snapshot registration invalid: snapshots must be an array"
            )
        if len(snapshots) != 1:
            raise SemanticSnapshotError(
                "semantic snapshot registration ambiguous: expected exactly one "
                f"active snapshot for {self.workspace_root}, found {len(snapshots)}"
            )
        item = snapshots[0]
        if not isinstance(item, Mapping):
            raise SemanticSnapshotError(
                "semantic snapshot registration invalid: active entry must be an object"
            )
        raw_path = item.get("path")
        snapshot_id = item.get("snapshot_id")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise SemanticSnapshotError(
                "semantic snapshot registration invalid: active path is missing"
            )
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            raise SemanticSnapshotError(
                "semantic snapshot registration invalid: active path must be absolute"
            )
        if (
            not isinstance(snapshot_id, str)
            or len(snapshot_id) != 64
            or any(character not in "0123456789abcdef" for character in snapshot_id)
        ):
            raise SemanticSnapshotError(
                "semantic snapshot registration invalid: snapshot identity is malformed"
            )
        return _RegisteredSnapshot(path.resolve(), snapshot_id)

    @staticmethod
    def _same_path(left: Path, right: Path) -> bool:
        return os.path.normcase(str(left.expanduser().resolve())) == os.path.normcase(
            str(right.expanduser().resolve())
        )

    @staticmethod
    def _reject_non_finite(value: str) -> object:
        raise ValueError(f"non-finite JSON number is not allowed: {value}")
