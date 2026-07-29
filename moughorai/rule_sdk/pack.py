from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any
import zipfile

from .metadata import RuleCatalog
from .runtime import Rule, RuleAuthoringError


RULE_PACK_SCHEMA_VERSION = 1
_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")
_ENTRY_POINT = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$")


class RulePackError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RulePackSpec:
    name: str
    version: str
    api_version: str = "1.0.0"
    description: str = ""
    entry_points: tuple[tuple[str, str], ...] = ()
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip() or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in self.name):
            raise RulePackError("rule pack name is invalid")
        for field, value in (("version", self.version), ("api_version", self.api_version)):
            if not _VERSION.fullmatch(value):
                raise RulePackError(f"rule pack {field} must be semantic version")
        if self.entry_points != tuple(sorted(self.entry_points)):
            raise RulePackError("rule pack entry points must be sorted")
        ids = [rule_id for rule_id, _ in self.entry_points]
        if len(ids) != len(set(ids)) or any(not rule_id.strip() for rule_id in ids):
            raise RulePackError("rule pack entry point rule ids must be unique and non-empty")
        if any(not _ENTRY_POINT.fullmatch(value) for _, value in self.entry_points):
            raise RulePackError("rule pack entry point is invalid")
        if self.dependencies != tuple(sorted(set(self.dependencies))):
            raise RulePackError("rule pack dependencies must be unique and sorted")


@dataclass(frozen=True, slots=True)
class RulePackBuildResult:
    path: Path
    sha256: str
    manifest: Mapping[str, Any]


class RulePackBuilder:
    def build(
        self,
        spec: RulePackSpec,
        rules: Iterable[Rule],
        files: Mapping[str | PurePosixPath, str | bytes],
        output: str | Path,
    ) -> RulePackBuildResult:
        normalized = _normalize_files(files)
        catalog = RuleCatalog(rules)
        metadata_ids = {entry.rule_id for entry in catalog.entries()}
        entry_ids = {rule_id for rule_id, _ in spec.entry_points}
        if metadata_ids != entry_ids:
            raise RulePackError(
                f"rule pack entry points do not match rules: "
                f"missing={sorted(metadata_ids - entry_ids)}, extra={sorted(entry_ids - metadata_ids)}"
            )
        for _, entry_point in spec.entry_points:
            module = entry_point.split(":", 1)[0].replace(".", "/")
            if f"{module}.py" not in normalized and f"{module}/__init__.py" not in normalized:
                raise RulePackError(f"entry point module is not included: {module}")
        file_records = [
            {"path": path, "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
            for path, content in normalized.items()
        ]
        entries = dict(spec.entry_points)
        manifest = {
            "schema_version": RULE_PACK_SCHEMA_VERSION,
            "name": spec.name,
            "version": spec.version,
            "api_version": spec.api_version,
            "description": spec.description,
            "dependencies": list(spec.dependencies),
            "rules": [
                {**metadata.to_dict(), "entry_point": entries[metadata.rule_id]}
                for metadata in catalog.entries()
            ],
            "files": file_records,
        }
        archive_entries = {
            "manifest.json": (_canonical(manifest) + "\n").encode("utf-8"),
            **normalized,
        }
        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            with zipfile.ZipFile(temporary, "w") as archive:
                for name in sorted(archive_entries):
                    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    info.create_system = 3
                    archive.writestr(info, archive_entries[name], compresslevel=9)
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        return RulePackBuildResult(target, digest, manifest)


class RulePackReader:
    def verify(self, path: str | Path) -> Mapping[str, Any]:
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise RulePackError("rule pack contains duplicate archive entries")
                for name in names:
                    _validate_path(name)
                if "manifest.json" not in names:
                    raise RulePackError("rule pack manifest is missing")
                try:
                    manifest = json.loads(archive.read("manifest.json"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise RulePackError("rule pack manifest is invalid") from exc
                if not isinstance(manifest, Mapping) or manifest.get("schema_version") != RULE_PACK_SCHEMA_VERSION:
                    raise RulePackError("unsupported rule pack schema")
                files = manifest.get("files")
                if not isinstance(files, list):
                    raise RulePackError("rule pack file manifest is invalid")
                declared = set()
                for record in files:
                    if not isinstance(record, Mapping):
                        raise RulePackError("rule pack file record is invalid")
                    name = str(record.get("path", ""))
                    _validate_path(name)
                    declared.add(name)
                    if name not in names:
                        raise RulePackError(f"rule pack file is missing: {name}")
                    content = archive.read(name)
                    if record.get("size") != len(content):
                        raise RulePackError(f"rule pack file size mismatch: {name}")
                    if record.get("sha256") != hashlib.sha256(content).hexdigest():
                        raise RulePackError(f"rule pack file checksum mismatch: {name}")
                actual = set(names) - {"manifest.json"}
                if declared != actual:
                    raise RulePackError("rule pack contains undeclared files")
                return manifest
        except zipfile.BadZipFile as exc:
            raise RulePackError("rule pack archive is invalid") from exc


def _normalize_files(files: Mapping[str | PurePosixPath, str | bytes]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for raw_path, raw_content in files.items():
        path = PurePosixPath(str(raw_path).replace("\\", "/")).as_posix()
        _validate_path(path)
        if path == "manifest.json":
            raise RulePackError("manifest.json is reserved")
        content = raw_content.encode("utf-8") if isinstance(raw_content, str) else bytes(raw_content)
        if path in result:
            raise RulePackError(f"duplicate rule pack file: {path}")
        result[path] = content
    return dict(sorted(result.items()))


def _validate_path(value: str) -> None:
    path = PurePosixPath(value)
    if not value or value == "." or path.is_absolute() or ".." in path.parts or "." in path.parts or value.endswith("/"):
        raise RulePackError(f"unsafe rule pack path: {value!r}")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
