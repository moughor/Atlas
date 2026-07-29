from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from moughorai.global_symbols import SymbolId

from .models import IncrementalAnalysisPlan


class IncrementalStateStore:
    SCHEMA_VERSION = 1

    def save(self, plan: IncrementalAnalysisPlan, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "changed_files": [str(item) for item in plan.changed_files],
            "removed_files": [str(item) for item in plan.removed_files],
            "directly_changed_symbols": [str(item) for item in plan.directly_changed_symbols],
            "impacted_symbols": [str(item) for item in plan.impacted_symbols],
            "files_to_analyze": [str(item) for item in plan.files_to_analyze],
        }
        fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def load(self, path: Path) -> IncrementalAnalysisPlan:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read incremental state: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("incremental state must be an object")
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError(f"unsupported incremental state schema: {payload.get('schema_version')}")
        allowed = {
            "schema_version",
            "changed_files",
            "removed_files",
            "directly_changed_symbols",
            "impacted_symbols",
            "files_to_analyze",
        }
        unknown = set(payload).difference(allowed)
        if unknown:
            raise ValueError(f"unknown incremental state fields: {', '.join(sorted(unknown))}")
        return IncrementalAnalysisPlan(
            changed_files=self._paths(payload, "changed_files"),
            removed_files=self._paths(payload, "removed_files"),
            directly_changed_symbols=self._symbols(payload, "directly_changed_symbols"),
            impacted_symbols=self._symbols(payload, "impacted_symbols"),
            files_to_analyze=self._paths(payload, "files_to_analyze"),
        )

    @staticmethod
    def _items(payload: Mapping[str, Any], field: str) -> list[str]:
        value = payload.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"incremental state {field} must be a list of strings")
        return value

    @classmethod
    def _paths(cls, payload: Mapping[str, Any], field: str) -> tuple[Path, ...]:
        return tuple(Path(item) for item in cls._items(payload, field))

    @classmethod
    def _symbols(cls, payload: Mapping[str, Any], field: str) -> tuple[SymbolId, ...]:
        return tuple(SymbolId(item) for item in cls._items(payload, field))
