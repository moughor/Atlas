from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from moughorai.measurement import MeasurementPhase
from moughorai.version import __version__

from .cache import WorkspaceCache, WorkspaceSnapshot
from .event_bus import WorkspaceEventKind
from .service import WorkspaceService

STATE_SCHEMA_VERSION = 1
ANALYSIS_RESULT_PRODUCER_FINGERPRINT = (
    f"atlas/{__version__}:workspace-analysis-result-v4"
)
_LEGACY_PRODUCER_FINGERPRINT = "atlas/legacy:unversioned-analysis-result"


class WorkspaceStateError(ValueError):
    """Raised when persisted workspace state is invalid or incompatible."""


@dataclass(frozen=True, slots=True)
class WorkspacePersistentState:
    schema_version: int
    workspace_fingerprint: str
    project_fingerprints: tuple[tuple[str, str], ...]
    valid_projects: tuple[str, ...]
    results: tuple[tuple[str, Any], ...]
    saved_at: str
    producer_fingerprint: str = ANALYSIS_RESULT_PRODUCER_FINGERPRINT

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workspace_fingerprint": self.workspace_fingerprint,
            "project_fingerprints": dict(self.project_fingerprints),
            "valid_projects": list(self.valid_projects),
            "results": dict(self.results),
            "saved_at": self.saved_at,
            "producer_fingerprint": self.producer_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "WorkspacePersistentState":
        try:
            schema_version = int(data["schema_version"])
            workspace_fingerprint = str(data["workspace_fingerprint"])
            raw_fingerprints = data["project_fingerprints"]
            raw_valid = data["valid_projects"]
            raw_results = data["results"]
            saved_at = str(data["saved_at"])
            producer_fingerprint = str(
                data.get("producer_fingerprint", _LEGACY_PRODUCER_FINGERPRINT)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise WorkspaceStateError("workspace state is missing required fields") from exc
        if schema_version != STATE_SCHEMA_VERSION:
            raise WorkspaceStateError(f"unsupported workspace state schema: {schema_version}")
        if not isinstance(raw_fingerprints, Mapping) or not isinstance(raw_results, Mapping):
            raise WorkspaceStateError("project_fingerprints and results must be mappings")
        if not isinstance(raw_valid, list) or not all(isinstance(item, str) for item in raw_valid):
            raise WorkspaceStateError("valid_projects must be a list of strings")
        return cls(
            schema_version=schema_version,
            workspace_fingerprint=workspace_fingerprint,
            project_fingerprints=tuple(sorted((str(k), str(v)) for k, v in raw_fingerprints.items())),
            valid_projects=tuple(sorted(set(raw_valid))),
            results=tuple(sorted((str(k), v) for k, v in raw_results.items())),
            saved_at=saved_at,
            producer_fingerprint=producer_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class WorkspaceRestoreReport:
    restored: tuple[str, ...]
    invalidated: tuple[str, ...]
    ignored: tuple[str, ...]
    state_found: bool

    @property
    def restored_any(self) -> bool:
        return bool(self.restored)

    def to_dict(self) -> dict[str, object]:
        return {
            "state_found": self.state_found,
            "restored": list(self.restored),
            "invalidated": list(self.invalidated),
            "ignored": list(self.ignored),
        }


class WorkspaceStateStore:
    def __init__(
        self,
        service: WorkspaceService,
        path: str | Path | None = None,
        *,
        cache: WorkspaceCache | None = None,
        encoder: Callable[[Any], Any] | None = None,
        decoder: Callable[[Any], Any] | None = None,
        producer_fingerprint: str = ANALYSIS_RESULT_PRODUCER_FINGERPRINT,
    ) -> None:
        self.service = service
        self.path = Path(path) if path is not None else service.workspace.root / ".atlas" / "workspace-state.json"
        self.measurement = service.measurement
        self.cache = cache or WorkspaceCache(measurement=self.measurement)
        self.encoder = encoder or (lambda value: value)
        self.decoder = decoder or (lambda value: value)
        if not isinstance(producer_fingerprint, str) or not producer_fingerprint.strip():
            raise ValueError("producer_fingerprint must be a non-empty string")
        self.producer_fingerprint = producer_fingerprint.strip()

    def capture(self, results: Mapping[str, Any], valid_projects: tuple[str, ...]) -> WorkspacePersistentState:
        with self.measurement.scope(
            MeasurementPhase.PERSISTENCE,
            consumer="workspace-state",
            sample_key="workspace-state",
        ) as scope:
            snapshot = self.cache.snapshot(self.service.workspace)
            names = set(self.service.workspace.names())
            valid = tuple(sorted(names.intersection(valid_projects).intersection(results)))
            encoded: list[tuple[str, Any]] = []
            for name in valid:
                try:
                    encoded.append((name, self.encoder(results[name])))
                except Exception as exc:
                    raise WorkspaceStateError(f"cannot encode result for project {name!r}: {exc}") from exc
            state = WorkspacePersistentState(
                STATE_SCHEMA_VERSION,
                self._workspace_fingerprint(snapshot),
                snapshot.fingerprints,
                valid,
                tuple(encoded),
                datetime.now(timezone.utc).isoformat(),
                self.producer_fingerprint,
            )
            scope.add_units(len(valid))
            scope.add_objects_produced(1)
            return state

    def save(self, state: WorkspacePersistentState) -> Path:
        with self.measurement.scope(
            MeasurementPhase.SERIALIZATION,
            consumer="workspace-state",
            sample_key="workspace-state",
        ) as serialization:
            payload = state.to_dict()
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            envelope = {"checksum": hashlib.sha256(canonical.encode("utf-8")).hexdigest(), "state": payload}
            text = json.dumps(envelope, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
            serialization.add_units(1)
        with self.measurement.scope(
            MeasurementPhase.PERSISTENCE,
            consumer="workspace-state",
            sample_key="workspace-state",
        ) as persistence:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
            temp_path = Path(temporary)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self.path)
            finally:
                if temp_path.exists():
                    temp_path.unlink()
            persistence.add_units(1)
            if self.measurement.config.enabled:
                try:
                    persistence.add_bytes(self.path.stat().st_size)
                except OSError:
                    pass
        self.service.events.emit(
            WorkspaceEventKind.STATE_SAVED,
            source="workspace.persistence",
            payload={"path": str(self.path), "projects": list(state.valid_projects)},
        )
        return self.path

    def load(self) -> WorkspacePersistentState | None:
        if not self.path.exists():
            return None
        try:
            with self.measurement.scope(
                MeasurementPhase.PERSISTENCE,
                consumer="workspace-state",
                sample_key="workspace-state",
            ) as persistence:
                text = self.path.read_text(encoding="utf-8")
                persistence.add_units(1)
                if self.measurement.config.enabled:
                    persisted_bytes = self.measurement.filesystem.file_content_read(
                        "workspace-state",
                        self.path,
                    )
                    if persisted_bytes is not None:
                        persistence.add_bytes(persisted_bytes)
            with self.measurement.scope(
                MeasurementPhase.SERIALIZATION,
                consumer="workspace-state",
                sample_key="workspace-state",
            ) as serialization:
                envelope = json.loads(text)
                del text
                serialization.add_units(1)
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkspaceStateError(f"cannot read workspace state: {exc}") from exc
        if not isinstance(envelope, Mapping) or not isinstance(envelope.get("state"), Mapping):
            raise WorkspaceStateError("workspace state envelope is invalid")
        state_data = envelope["state"]
        canonical = json.dumps(state_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if envelope.get("checksum") != expected:
            raise WorkspaceStateError("workspace state checksum mismatch")
        return WorkspacePersistentState.from_dict(state_data)

    def restore(self, state: WorkspacePersistentState | None) -> tuple[dict[str, Any], WorkspaceRestoreReport]:
        if state is None:
            return {}, WorkspaceRestoreReport((), (), (), False)
        current = self.cache.snapshot(self.service.workspace)
        current_map = current.to_dict()
        saved_map = dict(state.project_fingerprints)
        result_map = dict(state.results)
        names = set(self.service.workspace.names())
        if state.producer_fingerprint != self.producer_fingerprint:
            report = WorkspaceRestoreReport(
                (),
                tuple(sorted(names.intersection(result_map))),
                tuple(sorted(set(result_map).difference(names))),
                True,
            )
            self.service.events.emit(
                WorkspaceEventKind.STATE_RESTORED,
                source="workspace.persistence",
                payload=report.to_dict(),
            )
            return {}, report
        restored: dict[str, Any] = {}
        invalidated: list[str] = []
        ignored = sorted(set(result_map).difference(names))
        for name in sorted(names):
            if name not in result_map:
                continue
            if saved_map.get(name) != current_map.get(name):
                invalidated.append(name)
                continue
            try:
                restored[name] = self.decoder(result_map[name])
            except Exception as exc:
                raise WorkspaceStateError(f"cannot decode result for project {name!r}: {exc}") from exc
        report = WorkspaceRestoreReport(tuple(sorted(restored)), tuple(invalidated), tuple(ignored), True)
        self.service.events.emit(
            WorkspaceEventKind.STATE_RESTORED,
            source="workspace.persistence",
            payload=report.to_dict(),
        )
        return restored, report

    def delete(self) -> bool:
        if not self.path.exists():
            return False
        self.path.unlink()
        return True

    @staticmethod
    def _workspace_fingerprint(snapshot: WorkspaceSnapshot) -> str:
        payload = json.dumps(snapshot.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
