from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping

from .models import PluginLoadError, PluginManifest
from .serialization import manifest_to_json


class PluginTrustError(PluginLoadError):
    """Raised when a plugin fails integrity or permission validation."""


@dataclass(frozen=True, slots=True)
class PluginTrustRecord:
    plugin_id: str
    version: str
    digest: str
    signer: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.plugin_id.strip() or not self.version.strip():
            raise PluginTrustError("trust record plugin id and version are required")
        if len(self.digest) != 64 or any(ch not in "0123456789abcdef" for ch in self.digest.lower()):
            raise PluginTrustError("trust record digest must be a SHA-256 hexadecimal value")
        object.__setattr__(self, "digest", self.digest.lower())
        object.__setattr__(self, "metadata", MappingProxyType(dict(sorted(self.metadata.items()))))


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    granted: tuple[str, ...]
    denied: tuple[str, ...]
    reason: str = ""


class PluginPermissionPolicy:
    def __init__(
        self,
        *,
        allowed: Iterable[str] = (),
        denied: Iterable[str] = (),
        default_allow: bool = False,
        per_plugin: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        self.allowed = frozenset(str(item).strip() for item in allowed if str(item).strip())
        self.denied = frozenset(str(item).strip() for item in denied if str(item).strip())
        self.default_allow = bool(default_allow)
        self.per_plugin = {
            plugin_id: frozenset(str(item).strip() for item in values if str(item).strip())
            for plugin_id, values in sorted((per_plugin or {}).items())
        }

    def evaluate(self, manifest: PluginManifest) -> PermissionDecision:
        requested = tuple(sorted(set(manifest.permissions)))
        plugin_allowed = self.per_plugin.get(manifest.plugin_id, frozenset())
        denied = tuple(
            permission for permission in requested
            if permission in self.denied or not (
                self.default_allow or permission in self.allowed or permission in plugin_allowed
            )
        )
        granted = tuple(permission for permission in requested if permission not in denied)
        reason = "" if not denied else f"denied permissions: {', '.join(denied)}"
        return PermissionDecision(not denied, granted, denied, reason)

    def require(self, manifest: PluginManifest) -> PermissionDecision:
        decision = self.evaluate(manifest)
        if not decision.allowed:
            raise PluginTrustError(f"plugin {manifest.plugin_id} {decision.reason}")
        return decision


class PluginTrustStore:
    def __init__(self, records: Iterable[PluginTrustRecord] = ()) -> None:
        self._records: dict[tuple[str, str], PluginTrustRecord] = {}
        for record in records:
            self.add(record)

    def add(self, record: PluginTrustRecord) -> None:
        key = (record.plugin_id, record.version)
        if key in self._records:
            raise PluginTrustError(f"trust record already exists for {record.plugin_id} {record.version}")
        self._records[key] = record

    def replace(self, record: PluginTrustRecord) -> None:
        self._records[(record.plugin_id, record.version)] = record

    def remove(self, plugin_id: str, version: str) -> PluginTrustRecord:
        try:
            return self._records.pop((plugin_id, version))
        except KeyError as exc:
            raise PluginTrustError(f"trust record not found for {plugin_id} {version}") from exc

    def get(self, plugin_id: str, version: str) -> PluginTrustRecord:
        try:
            return self._records[(plugin_id, version)]
        except KeyError as exc:
            raise PluginTrustError(f"plugin is not trusted: {plugin_id} {version}") from exc

    def records(self) -> tuple[PluginTrustRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def verify(self, manifest: PluginManifest, digest: str) -> PluginTrustRecord:
        record = self.get(manifest.plugin_id, manifest.version)
        if not hmac.compare_digest(record.digest, digest.lower()):
            raise PluginTrustError(f"plugin integrity check failed: {manifest.plugin_id} {manifest.version}")
        return record

    def to_json(self) -> str:
        payload = {
            "schema_version": 1,
            "records": [
                {
                    "plugin_id": item.plugin_id,
                    "version": item.version,
                    "digest": item.digest,
                    "signer": item.signer,
                    "metadata": dict(item.metadata),
                }
                for item in self.records()
            ],
        }
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "PluginTrustStore":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PluginTrustError(f"invalid trust store JSON: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise PluginTrustError("unsupported trust store schema")
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise PluginTrustError("trust store records must be a list")
        records = []
        for raw in raw_records:
            if not isinstance(raw, dict):
                raise PluginTrustError("trust store record must be an object")
            unknown = set(raw) - {"plugin_id", "version", "digest", "signer", "metadata"}
            if unknown:
                raise PluginTrustError(f"unknown trust record fields: {', '.join(sorted(unknown))}")
            try:
                records.append(PluginTrustRecord(
                    plugin_id=raw["plugin_id"], version=raw["version"], digest=raw["digest"],
                    signer=raw.get("signer", ""), metadata=raw.get("metadata", {}),
                ))
            except KeyError as exc:
                raise PluginTrustError(f"missing trust record field: {exc.args[0]}") from exc
        return cls(records)


def plugin_bundle_digest(
    manifest: PluginManifest,
    root: str | Path | None = None,
    *,
    include: Iterable[str | Path] | None = None,
) -> str:
    """Return a deterministic SHA-256 digest for a manifest and selected bundle files."""
    hasher = hashlib.sha256()
    manifest_bytes = manifest_to_json(manifest).encode("utf-8")
    hasher.update(b"manifest\0")
    hasher.update(manifest_bytes)
    if root is None:
        if include:
            raise PluginTrustError("bundle root is required when include paths are supplied")
        return hasher.hexdigest()

    base = Path(root).resolve()
    paths = _resolve_bundle_paths(base, include)
    for path in paths:
        try:
            relative = path.relative_to(base).as_posix()
        except ValueError as exc:
            raise PluginTrustError(f"bundle file escapes plugin root: {path}") from exc
        if path.is_symlink():
            raise PluginTrustError(f"symbolic links are not permitted in plugin bundles: {relative}")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise PluginTrustError(f"cannot read plugin bundle file {relative}: {exc}") from exc
        hasher.update(b"file\0")
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(content)
    return hasher.hexdigest()


def _resolve_bundle_paths(base: Path, include: Iterable[str | Path] | None) -> tuple[Path, ...]:
    if not base.is_dir():
        raise PluginTrustError(f"plugin bundle root is not a directory: {base}")
    if include is None:
        candidates = [path for path in base.rglob("*") if path.is_file()]
    else:
        candidates = []
        for item in include:
            candidate = (base / item).resolve()
            try:
                candidate.relative_to(base)
            except ValueError as exc:
                raise PluginTrustError(f"bundle include escapes plugin root: {item}") from exc
            if not candidate.is_file():
                raise PluginTrustError(f"bundle include is not a file: {item}")
            candidates.append(candidate)
    return tuple(sorted(set(candidates), key=lambda item: item.relative_to(base).as_posix()))
