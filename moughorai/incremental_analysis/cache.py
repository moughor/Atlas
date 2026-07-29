"""Thread-safe persistent incremental result cache."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Iterable


class CacheFormatError(ValueError):
    """Raised when a cache file cannot be trusted."""


@dataclass(frozen=True, order=True)
class CacheEntry:
    key: str
    fingerprint: str
    result: Any
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("cache key must not be empty")
        if len(self.fingerprint) != 64:
            raise ValueError("cache fingerprint must be a SHA-256 digest")
        object.__setattr__(self, "dependencies", tuple(sorted(set(self.dependencies))))


@dataclass(frozen=True)
class CacheStatistics:
    hits: int = 0
    misses: int = 0
    writes: int = 0
    removals: int = 0
    invalidations: int = 0

    @property
    def requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.requests if self.requests else 0.0


class IncrementalCache:
    SCHEMA_VERSION = 1

    def __init__(self, entries: Iterable[CacheEntry] = ()) -> None:
        self._entries = {entry.key: entry for entry in entries}
        self._lock = RLock()
        self._statistics = CacheStatistics()

    @property
    def entries(self) -> tuple[CacheEntry, ...]:
        with self._lock:
            return tuple(sorted(self._entries.values(), key=lambda item: item.key))

    @property
    def statistics(self) -> CacheStatistics:
        with self._lock:
            return self._statistics

    def get(self, key: str, fingerprint: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.fingerprint != fingerprint:
                self._bump(misses=1)
                return None
            self._bump(hits=1)
            return entry.result

    def put(self, key: str, fingerprint: str, result: Any, dependencies: Iterable[str] = ()) -> CacheEntry:
        entry = CacheEntry(key, fingerprint, result, tuple(dependencies))
        with self._lock:
            self._entries[key] = entry
            self._bump(writes=1)
        return entry

    def remove(self, key: str) -> bool:
        with self._lock:
            existed = self._entries.pop(key, None) is not None
            if existed:
                self._bump(removals=1)
            return existed

    def invalidate(self, keys: Iterable[str], *, transitive: bool = True) -> tuple[str, ...]:
        with self._lock:
            dirty = set(keys)
            if transitive:
                changed = True
                while changed:
                    changed = False
                    for entry in self._entries.values():
                        if entry.key not in dirty and dirty.intersection(entry.dependencies):
                            dirty.add(entry.key)
                            changed = True
            removed = tuple(sorted(key for key in dirty if key in self._entries))
            for key in removed:
                del self._entries[key]
            if removed:
                self._bump(invalidations=len(removed))
            return removed

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            if count:
                self._bump(removals=count)
            return count

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "entries": [
                {
                    "key": entry.key,
                    "fingerprint": entry.fingerprint,
                    "dependencies": list(entry.dependencies),
                    "result": entry.result,
                }
                for entry in self.entries
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(self.to_json(), encoding="utf-8")
        os.replace(temporary, path)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "IncrementalCache":
        if value.get("schema_version") != cls.SCHEMA_VERSION:
            raise CacheFormatError("unsupported incremental cache schema version")
        raw_entries = value.get("entries")
        if not isinstance(raw_entries, list):
            raise CacheFormatError("cache entries must be a list")
        try:
            entries = [
                CacheEntry(
                    str(item["key"]),
                    str(item["fingerprint"]),
                    item.get("result"),
                    tuple(str(dep) for dep in item.get("dependencies", ())),
                )
                for item in raw_entries
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise CacheFormatError(f"invalid cache entry: {exc}") from exc
        if len({entry.key for entry in entries}) != len(entries):
            raise CacheFormatError("duplicate cache key")
        return cls(entries)

    @classmethod
    def load(cls, path: Path, *, recover: bool = False) -> "IncrementalCache":
        if not path.exists():
            return cls()
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise CacheFormatError("cache root must be an object")
            return cls.from_dict(value)
        except (OSError, json.JSONDecodeError, CacheFormatError) as exc:
            if recover:
                return cls()
            if isinstance(exc, CacheFormatError):
                raise
            raise CacheFormatError(f"unable to load incremental cache: {exc}") from exc

    def _bump(self, **changes: int) -> None:
        values = self._statistics.__dict__.copy()
        for name, amount in changes.items():
            values[name] += amount
        self._statistics = CacheStatistics(**values)
