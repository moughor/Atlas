from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib
import xml.etree.ElementTree as ET

from .models import DeclaredDependency


class DependencyIntelligenceService:
    """Parse dependency manifests deterministically without executing build tools."""

    MANIFESTS = frozenset({
        "pom.xml", "build.gradle", "build.gradle.kts", "requirements.txt",
        "pyproject.toml", "package.json", "Cargo.toml",
    })

    def analyze(self, root: Path, files: tuple[Path, ...]) -> tuple[DeclaredDependency, ...]:
        dependencies: set[DeclaredDependency] = set()
        for path in sorted(files, key=Path.as_posix):
            if path.name not in self.MANIFESTS:
                continue
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
            except (OSError, UnicodeError, ValueError, ET.ParseError, json.JSONDecodeError, tomllib.TOMLDecodeError):
                continue
        return tuple(sorted(dependencies, key=DeclaredDependency.deterministic_sort_key))

    @staticmethod
    def _maven(path: Path):
        root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
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

    @staticmethod
    def _gradle(path: Path):
        text = path.read_text(encoding="utf-8-sig")
        pattern = re.compile(
            r"""(?m)^\s*(implementation|api|compileOnly|runtimeOnly|testImplementation)"""
            r"""\s*(?:\(\s*)?["']([^:"']+):([^:"']+)(?::([^"']+))?["']"""
        )
        return [
            DeclaredDependency("gradle", f"{group}:{artifact}", version, scope, path)
            for scope, group, artifact, version in pattern.findall(text)
        ]

    @staticmethod
    def _requirements(path: Path):
        result = []
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith(("-", ".")):
                continue
            match = re.match(r"([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(.*)", line)
            if match:
                result.append(DeclaredDependency(
                    "pypi", match.group(1), match.group(2) or None, "runtime", path,
                ))
        return result

    @staticmethod
    def _pyproject(path: Path):
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
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

    @staticmethod
    def _package_json(path: Path):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
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

    @staticmethod
    def _cargo(path: Path):
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
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
