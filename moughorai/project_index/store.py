"""Atomic JSON persistence for project index snapshots."""
from __future__ import annotations

import json
import os
from pathlib import Path

from moughorai.project_index.models import IndexedFile, ProjectIndexSnapshot


class ProjectIndexStore:
    SCHEMA_VERSION = 1

    def save(self, snapshot: ProjectIndexSnapshot, path: Path) -> None:
        path = path.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "root": str(snapshot.root),
            "files": [
                {
                    "relative_path": item.relative_path.as_posix(),
                    "size": item.size,
                    "modified_ns": item.modified_ns,
                    "sha256": item.sha256,
                }
                for item in snapshot.files
            ],
        }
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)

    def load(self, path: Path) -> ProjectIndexSnapshot:
        path = path.expanduser().resolve()
        payload = json.loads(path.read_text(encoding="utf-8"))
        version = payload.get("schema_version")
        if version != self.SCHEMA_VERSION:
            raise ValueError(f"unsupported project index schema: {version}")
        files = tuple(
            IndexedFile(
                relative_path=Path(item["relative_path"]),
                size=int(item["size"]),
                modified_ns=int(item["modified_ns"]),
                sha256=str(item["sha256"]),
            )
            for item in payload["files"]
        )
        return ProjectIndexSnapshot(root=Path(payload["root"]), files=files, schema_version=version)
