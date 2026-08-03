from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from moughorai.measurement import FilesystemOperation, MeasurementSession

from .models import Project, Workspace
from .files import project_files


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    fingerprints: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, str]:
        return dict(self.fingerprints)


class WorkspaceCache:
    def __init__(self, *, measurement: MeasurementSession | None = None) -> None:
        self.measurement = measurement

    def snapshot(self, workspace: Workspace) -> WorkspaceSnapshot:
        return WorkspaceSnapshot(tuple((name, self.fingerprint(workspace.get(name))) for name in workspace.names()))

    def changed(self, before: WorkspaceSnapshot | None, after: WorkspaceSnapshot) -> tuple[str, ...]:
        if before is None:
            return tuple(name for name, _ in after.fingerprints)
        old = before.to_dict()
        return tuple(name for name, digest in after.fingerprints if old.get(name) != digest)

    def fingerprint(self, project: Project) -> str:
        digest = hashlib.sha256()
        digest.update(project.name.encode())
        digest.update(repr(project.dependencies).encode())
        for path in self._files(project):
            relative = path.relative_to(project.path).as_posix()
            digest.update(relative.encode())
            content = path.read_bytes()
            if self.measurement is not None:
                self.measurement.filesystem.file_content_read_known_size(
                    "workspace-cache",
                    path,
                    bytes_read=len(content),
                )
                self.measurement.filesystem.record(
                    FilesystemOperation.HASH,
                    consumer="workspace-cache",
                )
            digest.update(content)
        return digest.hexdigest()

    def _files(self, project: Project) -> tuple[Path, ...]:
        return project_files(
            project.path,
            project.include,
            project.exclude,
            measurement=self.measurement,
            consumer="workspace-cache",
            sample_key=project.name,
        )
