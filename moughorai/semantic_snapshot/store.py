from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Callable

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.version import __version__
from moughorai.workspace import Workspace
from moughorai.workspace.cache import WorkspaceCache

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
    ) -> None:
        self.workspace = workspace
        self.directory = Path(directory or workspace.root / ".atlas" / "ass")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cache = cache or WorkspaceCache()
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
        fingerprints = self.cache.snapshot(self.workspace).to_dict()
        fingerprint = hashlib.sha256(canonical_json(fingerprints).encode("utf-8")).hexdigest()
        return AtlasSemanticSnapshot.create(
            context,
            workspace_fingerprint=fingerprint,
            analyzer_version=analyzer_version,
            history_reference=history_reference,
        )

    def save(self, snapshot: AtlasSemanticSnapshot) -> Path:
        text = self._serialize(snapshot)
        timestamp = self._timestamp(self.clock())
        historical = self.directory / f"{timestamp}.ass"
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            if historical.exists():
                if historical.read_text(encoding="utf-8") != text:
                    raise SemanticSnapshotError(
                        f"immutable semantic snapshot already exists: {historical.name}"
                    )
            else:
                self._atomic_write(historical, text, replace=False)
            self._atomic_write(self.latest_path, text, replace=True)
        return historical

    def load(self, path: str | Path | None = None) -> AtlasSemanticSnapshot | None:
        target = Path(path) if path is not None else self.latest_path
        if not target.exists():
            return None
        try:
            envelope = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
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
        payload = snapshot.to_dict()
        envelope = {
            "format": SEMANTIC_SNAPSHOT_FORMAT,
            "checksum": hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(),
            "snapshot": payload,
        }
        return json.dumps(envelope, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

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
            if not replace and path.exists():
                raise SemanticSnapshotError(f"semantic snapshot already exists: {path.name}")
            os.replace(temporary_path, path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
