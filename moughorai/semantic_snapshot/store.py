from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Callable

from moughorai.measurement import MeasurementPhase, MeasurementSession
from moughorai.version import __version__
from moughorai.workspace import Workspace
from moughorai.workspace.cache import WorkspaceCache

from .context import WorkspaceSemanticContext
from .models import (
    SEMANTIC_SNAPSHOT_FORMAT,
    AtlasSemanticSnapshot,
    SemanticSnapshotError,
    canonical_json,
)


class SemanticSnapshotStore:
    """Durable immutable snapshot archive with an atomic latest pointer."""

    def __init__(
        self,
        workspace: Workspace,
        directory: str | Path | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        cache: WorkspaceCache | None = None,
        measurement: MeasurementSession | None = None,
    ) -> None:
        self.workspace = workspace
        self.directory = Path(directory or workspace.root / ".atlas" / "ass")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.measurement = measurement or MeasurementSession()
        self.cache = cache or WorkspaceCache(measurement=self.measurement)
        self._lock = RLock()

    @property
    def latest_path(self) -> Path:
        return self.directory / "latest.ass"

    def capture(
        self,
        context: WorkspaceSemanticContext,
        *,
        history_reference: int | str | None = None,
        analyzer_version: str = __version__,
    ) -> AtlasSemanticSnapshot:
        with self.measurement.scope(
            MeasurementPhase.SNAPSHOT,
            consumer="semantic-snapshot",
            sample_key="snapshot",
        ) as scope:
            fingerprints = self.cache.snapshot(self.workspace).to_dict()
            fingerprint = hashlib.sha256(canonical_json(fingerprints).encode("utf-8")).hexdigest()
            snapshot = AtlasSemanticSnapshot.create(
                context,
                workspace_fingerprint=fingerprint,
                analyzer_version=analyzer_version,
                history_reference=history_reference,
            )
            scope.add_units(len(fingerprints))
            scope.add_objects_produced(1)
            return snapshot

    def save(self, snapshot: AtlasSemanticSnapshot) -> Path:
        with self.measurement.scope(
            MeasurementPhase.SERIALIZATION,
            consumer="semantic-snapshot",
            sample_key="snapshot",
        ) as serialization:
            text = self._serialize(snapshot)
            serialization.add_units(1)
        timestamp = self._timestamp(self.clock())
        historical = self.directory / f"{timestamp}.ass"
        with self.measurement.scope(
            MeasurementPhase.PUBLICATION,
            consumer="semantic-snapshot",
            sample_key="snapshot",
        ) as publication:
            with self._lock:
                self.directory.mkdir(parents=True, exist_ok=True)
                historical, historical_written = self._write_historical(
                    historical,
                    text,
                    snapshot.snapshot_id,
                )
                self._atomic_write(self.latest_path, text, replace=True)
            publication.add_units(1 + int(historical_written))
            if self.measurement.config.enabled:
                published_bytes = 0
                try:
                    published_bytes += self.latest_path.stat().st_size
                except OSError:
                    pass
                if historical_written:
                    try:
                        published_bytes += historical.stat().st_size
                    except OSError:
                        pass
                publication.add_bytes(published_bytes)
        return historical

    def _write_historical(
        self,
        historical: Path,
        text: str,
        snapshot_id: str,
    ) -> tuple[Path, bool]:
        try:
            self._atomic_write(historical, text, replace=False)
            return historical, True
        except SemanticSnapshotError:
            existing_matches = historical.read_text(encoding="utf-8") == text
            self.measurement.filesystem.file_content_read(
                "semantic-snapshot",
                historical,
            )
            if existing_matches:
                return historical, False
        suffixed = historical.with_name(
            f"{historical.stem}-{snapshot_id[:12]}{historical.suffix}"
        )
        try:
            self._atomic_write(suffixed, text, replace=False)
        except SemanticSnapshotError:
            existing_matches = suffixed.read_text(encoding="utf-8") == text
            self.measurement.filesystem.file_content_read(
                "semantic-snapshot",
                suffixed,
            )
            if not existing_matches:
                raise SemanticSnapshotError(
                    f"semantic snapshot identifier collision: {suffixed.name}"
                )
            return suffixed, False
        return suffixed, True

    def load(self, path: str | Path | None = None) -> AtlasSemanticSnapshot | None:
        target = Path(path) if path is not None else self.latest_path
        if not target.exists():
            return None
        try:
            with self.measurement.scope(
                MeasurementPhase.PERSISTENCE,
                consumer="semantic-snapshot",
                sample_key="snapshot",
            ) as persistence:
                text = target.read_text(encoding="utf-8")
                persistence.add_units(1)
                if self.measurement.config.enabled:
                    persisted_bytes = self.measurement.filesystem.file_content_read(
                        "semantic-snapshot",
                        target,
                    )
                    if persisted_bytes is not None:
                        persistence.add_bytes(persisted_bytes)
            with self.measurement.scope(
                MeasurementPhase.SERIALIZATION,
                consumer="semantic-snapshot",
                sample_key="snapshot",
            ) as serialization:
                envelope = json.loads(
                    text,
                    parse_constant=self._reject_non_finite,
                )
                del text
                serialization.add_units(1)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise SemanticSnapshotError(f"cannot read semantic snapshot: {exc}") from exc
        if not isinstance(envelope, dict) or envelope.get("format") != SEMANTIC_SNAPSHOT_FORMAT:
            raise SemanticSnapshotError("semantic snapshot envelope is invalid")
        raw = envelope.get("snapshot")
        if not isinstance(raw, dict):
            raise SemanticSnapshotError("semantic snapshot payload is invalid")
        checksum = hashlib.sha256(canonical_json(raw).encode("utf-8")).hexdigest()
        if envelope.get("checksum") != checksum:
            raise SemanticSnapshotError("semantic snapshot checksum mismatch")
        return AtlasSemanticSnapshot.from_dict(raw)

    def list(self) -> tuple[Path, ...]:
        if not self.directory.exists():
            return ()
        return tuple(
            sorted(
                (
                    path
                    for path in self.directory.glob("*.ass")
                    if path.name != self.latest_path.name
                ),
                key=lambda path: path.name,
            )
        )

    @staticmethod
    def _serialize(snapshot: AtlasSemanticSnapshot) -> str:
        # The snapshot boundary is shallowly immutable for compatibility. Revalidate
        # its complete nested payload immediately before persistence so a caller
        # cannot save an artifact whose identifier no longer matches its content.
        payload = AtlasSemanticSnapshot.from_dict(snapshot.to_dict()).to_dict()
        envelope = {
            "format": SEMANTIC_SNAPSHOT_FORMAT,
            "checksum": hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(),
            "snapshot": payload,
        }
        try:
            return json.dumps(
                envelope,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            ) + "\n"
        except (TypeError, ValueError) as exc:
            raise SemanticSnapshotError(
                "persisted semantic snapshots must contain finite JSON data"
            ) from exc

    @staticmethod
    def _reject_non_finite(value: str) -> None:
        raise ValueError(f"non-finite JSON number is not supported: {value}")

    @staticmethod
    def _timestamp(value: datetime) -> str:
        if value.tzinfo is None:
            raise SemanticSnapshotError("snapshot clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")

    @staticmethod
    def _atomic_write(path: Path, text: str, *, replace: bool) -> None:
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            if replace:
                os.replace(temporary_path, path)
            else:
                try:
                    os.link(temporary_path, path)
                except FileExistsError as exc:
                    raise SemanticSnapshotError(
                        f"semantic snapshot already exists: {path.name}"
                    ) from exc
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
