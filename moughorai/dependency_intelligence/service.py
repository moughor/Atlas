from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib
import xml.etree.ElementTree as ET

from moughorai.measurement import MeasurementPhase, MeasurementSession

from .models import DeclaredDependency


class DependencyIntelligenceService:
    """Parse dependency manifests deterministically without executing build tools."""

    MANIFESTS = frozenset({
        "pom.xml", "build.gradle", "build.gradle.kts", "requirements.txt",
        "pyproject.toml", "package.json", "Cargo.toml",
    })

    def __init__(self, *, measurement: MeasurementSession | None = None) -> None:
        self.measurement = measurement or MeasurementSession()

    def analyze(
        self,
        root: Path,
        files: tuple[Path, ...],
        *,
        sample_key: str = "dependency-analysis",
    ) -> tuple[DeclaredDependency, ...]:
        with self.measurement.scope(
            MeasurementPhase.DEPENDENCY_INTELLIGENCE,
            consumer="dependency-intelligence",
            sample_key=sample_key,
        ) as scope:
            dependencies: set[DeclaredDependency] = set()
            manifest_count = 0
            for path in sorted(files, key=Path.as_posix):
                if path.name not in self.MANIFESTS:
                    continue
                manifest_count += 1
                try:
                    if path.name == "pom.xml":
                        dependencies.update(self._maven(path))
                    elif path.name.startswith("build.gradle"):
                        dependencies.update(self._gradle(path))
                    elif path.name == "requirements.txt":
                        dependencies.update(self._requirements(path))
                    elif path.name == "pyproject.toml":
                        dependencies.update(self._pyproject(path))
                    elif path.name == "package.json":
                        dependencies.update(self._package_json(path))
                    elif path.name == "Cargo.toml":
                        dependencies.update(self._cargo(path))
                    self.measurement.filesystem.descriptor_parsed(
                        "dependency-intelligence"
                    )
                except (OSError, UnicodeError, ValueError, ET.ParseError, json.JSONDecodeError, tomllib.TOMLDecodeError):
                    continue
            result = tuple(sorted(
                dependencies,
                key=DeclaredDependency.deterministic_sort_key,
            ))
            scope.add_units(manifest_count)
            scope.add_objects_produced(len(result))
            scope.set_objects_retained(len(result))
            return result

    def _maven(self, path: Path):
        root = ET.fromstring(self._read_text(path))
        result = []
        for node in root.findall(".//{*}dependency"):
            group = node.findtext("{*}groupId")
            artifact = node.findtext("{*}artifactId")
            if not group or not artifact:
                continue
            result.append(DeclaredDependency(
                "maven", f"{group}:{artifact}", node.findtext("{*}version"),
                node.findtext("{*}scope") or "compile", path,
                (node.findtext("{*}optional") or "").lower() == "true",
            ))
        return result

    def _gradle(self, path: Path):
        text = self._read_text(path)
        pattern = re.compile(
            r"""(?m)^\s*(implementation|api|compileOnly|runtimeOnly|testImplementation)"""
            r"""\s*(?:\(\s*)?["']([^:"']+):([^:"']+)(?::([^"']+))?["']"""
        )
        return [
            DeclaredDependency("gradle", f"{group}:{artifact}", version, scope, path)
            for scope, group, artifact, version in pattern.findall(text)
        ]

    def _requirements(self, path: Path):
        result = []
        for raw in self._read_text(path).splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith(("-", ".")):
                continue
            match = re.match(r"([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(.*)", line)
            if match:
                result.append(DeclaredDependency(
                    "pypi", match.group(1), match.group(2) or None, "runtime", path,
                ))
        return result

    def _pyproject(self, path: Path):
        data = tomllib.loads(self._read_text(path))
        poetry = data.get("tool", {}).get("poetry", {})
        result = []
        for scope, values in (
            ("runtime", poetry.get("dependencies", {})),
            ("development", poetry.get("group", {}).get("dev", {}).get("dependencies", {})),
        ):
            for name, value in values.items():
                if name.lower() == "python":
                    continue
                version = value.get("version") if isinstance(value, dict) else str(value)
                optional = bool(value.get("optional", False)) if isinstance(value, dict) else False
                result.append(DeclaredDependency("pypi", name, version, scope, path, optional))
        return result

    def _package_json(self, path: Path):
        data = json.loads(self._read_text(path))
        result = []
        for field, scope in (
            ("dependencies", "runtime"), ("devDependencies", "development"),
            ("peerDependencies", "peer"), ("optionalDependencies", "optional"),
        ):
            for name, version in data.get(field, {}).items():
                result.append(DeclaredDependency(
                    "npm", name, str(version), scope, path, field == "optionalDependencies",
                ))
        return result

    def _cargo(self, path: Path):
        data = tomllib.loads(self._read_text(path))
        result = []
        for field, scope in (
            ("dependencies", "runtime"), ("dev-dependencies", "development"),
            ("build-dependencies", "build"),
        ):
            for name, value in data.get(field, {}).items():
                version = value.get("version") if isinstance(value, dict) else str(value)
                optional = bool(value.get("optional", False)) if isinstance(value, dict) else False
                result.append(DeclaredDependency("cargo", name, version, scope, path, optional))
        return result

    def _read_text(self, path: Path) -> str:
        text = path.read_text(encoding="utf-8-sig")
        if self.measurement.filesystem.enabled:
            self.measurement.filesystem.file_content_read_unknown_size(
                "dependency-intelligence",
                path,
            )
        return text
