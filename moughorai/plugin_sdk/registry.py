from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from moughorai.policy_packs import SemanticVersion, VersionConstraint

from .models import (
    ExtensionPoint,
    PluginCompatibilityError,
    PluginDiagnostic,
    PluginManifest,
    PluginManifestError,
)


class PluginRegistry:
    def __init__(self, *, api_version: str = "1.0.0") -> None:
        self.api_version = SemanticVersion.parse(api_version)
        self._manifests: dict[str, PluginManifest] = {}

    def register(self, manifest: PluginManifest) -> None:
        if manifest.plugin_id in self._manifests:
            raise PluginManifestError(f"plugin already registered: {manifest.plugin_id}")
        constraint = VersionConstraint(manifest.api_version)
        if not constraint.matches(self.api_version):
            raise PluginCompatibilityError(
                f"plugin {manifest.plugin_id} requires API {manifest.api_version}; running {self.api_version}"
            )
        self._manifests[manifest.plugin_id] = manifest

    def unregister(self, plugin_id: str) -> PluginManifest:
        try:
            return self._manifests.pop(plugin_id)
        except KeyError as exc:
            raise PluginManifestError(f"plugin is not registered: {plugin_id}") from exc

    def get(self, plugin_id: str) -> PluginManifest:
        try:
            return self._manifests[plugin_id]
        except KeyError as exc:
            raise PluginManifestError(f"plugin is not registered: {plugin_id}") from exc

    def manifests(self) -> tuple[PluginManifest, ...]:
        return tuple(self._manifests[key] for key in sorted(self._manifests))

    def resolve_order(self) -> tuple[PluginManifest, ...]:
        visiting: set[str] = set()
        visited: set[str] = set()
        order: list[PluginManifest] = []

        def visit(plugin_id: str, path: tuple[str, ...]) -> None:
            if plugin_id in visited:
                return
            if plugin_id in visiting:
                cycle = " -> ".join((*path, plugin_id))
                raise PluginManifestError(f"plugin dependency cycle: {cycle}")
            manifest = self.get(plugin_id)
            visiting.add(plugin_id)
            for dependency in manifest.requires:
                if dependency not in self._manifests:
                    raise PluginManifestError(f"plugin {plugin_id} requires missing plugin {dependency}")
                visit(dependency, (*path, plugin_id))
            visiting.remove(plugin_id)
            visited.add(plugin_id)
            order.append(manifest)

        for plugin_id in sorted(self._manifests):
            visit(plugin_id, ())
        return tuple(order)

    def extensions(self, point: ExtensionPoint | str | None = None):
        selected = ExtensionPoint(point) if isinstance(point, str) else point
        result = []
        for manifest in self.resolve_order():
            for extension in manifest.extensions:
                if selected is None or extension.point is selected:
                    result.append((manifest, extension))
        return tuple(result)

    def diagnostics(self) -> tuple[PluginDiagnostic, ...]:
        diagnostics: list[PluginDiagnostic] = []
        factories: dict[tuple[ExtensionPoint, str], list[str]] = defaultdict(list)
        for manifest in self.manifests():
            if not manifest.extensions:
                diagnostics.append(PluginDiagnostic("warning", "empty-plugin", "plugin exposes no extensions", manifest.plugin_id))
            for extension in manifest.extensions:
                factories[(extension.point, extension.name)].append(manifest.plugin_id)
        for (point, name), plugin_ids in sorted(factories.items(), key=lambda item: (item[0][0].value, item[0][1])):
            if len(plugin_ids) > 1:
                diagnostics.append(PluginDiagnostic(
                    "warning", "duplicate-extension-name",
                    f"{point.value} extension {name!r} is exposed by {', '.join(sorted(plugin_ids))}",
                ))
        try:
            self.resolve_order()
        except PluginManifestError as exc:
            diagnostics.append(PluginDiagnostic("error", "dependency-resolution", str(exc)))
        return tuple(diagnostics)
