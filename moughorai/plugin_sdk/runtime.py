from __future__ import annotations

import importlib
from collections import defaultdict
from typing import Any, Callable, Mapping

from .models import ExtensionPoint, LoadedExtension, PluginLoadError
from .registry import PluginRegistry
from .trust import PluginPermissionPolicy, PluginTrustError


class PluginContext:
    def __init__(self, services: Mapping[str, Any] | None = None) -> None:
        self._services = dict(services or {})

    def get(self, name: str, default: Any = None) -> Any:
        return self._services.get(name, default)

    def require(self, name: str) -> Any:
        try:
            return self._services[name]
        except KeyError as exc:
            raise PluginLoadError(f"required plugin service is unavailable: {name}") from exc

    def as_dict(self) -> dict[str, Any]:
        return dict(self._services)


class PluginRuntime:
    def __init__(
        self, registry: PluginRegistry, *, services: Mapping[str, Any] | None = None,
        permission_policy: PluginPermissionPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.context = PluginContext(services)
        self._loaded: dict[str, tuple[LoadedExtension, ...]] = {}
        self.permission_policy = permission_policy

    def load_all(self) -> tuple[LoadedExtension, ...]:
        loaded: list[LoadedExtension] = []
        for manifest in self.registry.resolve_order():
            loaded.extend(self.load(manifest.plugin_id))
        return tuple(loaded)

    def load(self, plugin_id: str) -> tuple[LoadedExtension, ...]:
        if plugin_id in self._loaded:
            return self._loaded[plugin_id]
        manifest = self.registry.get(plugin_id)
        if self.permission_policy is not None:
            self.permission_policy.require(manifest)
        for dependency in manifest.requires:
            self.load(dependency)
        created: list[LoadedExtension] = []
        try:
            for extension in manifest.extensions:
                factory = self._resolve_factory(extension.factory)
                instance = self._construct(factory, dict(extension.config))
                if hasattr(instance, "start"):
                    instance.start(self.context)
                created.append(LoadedExtension(manifest.plugin_id, manifest.version, extension, instance))
        except Exception as exc:
            for loaded in reversed(created):
                self._stop(loaded.instance)
            if isinstance(exc, PluginLoadError):
                raise
            raise PluginLoadError(f"failed to load plugin {plugin_id}: {exc}") from exc
        result = tuple(created)
        self._loaded[plugin_id] = result
        return result

    def unload(self, plugin_id: str) -> None:
        dependents = sorted(
            manifest.plugin_id for manifest in self.registry.manifests()
            if plugin_id in manifest.requires and manifest.plugin_id in self._loaded
        )
        if dependents:
            raise PluginLoadError(f"cannot unload {plugin_id}; loaded dependents: {', '.join(dependents)}")
        loaded = self._loaded.pop(plugin_id, ())
        for extension in reversed(loaded):
            self._stop(extension.instance)

    def unload_all(self) -> None:
        for manifest in reversed(self.registry.resolve_order()):
            if manifest.plugin_id in self._loaded:
                self.unload(manifest.plugin_id)

    def extensions(self, point: ExtensionPoint | str | None = None) -> tuple[LoadedExtension, ...]:
        selected = ExtensionPoint(point) if isinstance(point, str) else point
        result = []
        for plugin_id in sorted(self._loaded):
            for loaded in self._loaded[plugin_id]:
                if selected is None or loaded.extension.point is selected:
                    result.append(loaded)
        return tuple(sorted(result, key=lambda item: (item.extension.point.value, item.extension.name, item.plugin_id)))

    @staticmethod
    def _resolve_factory(path: str) -> Callable[..., Any]:
        module_name, attribute = path.split(":", 1)
        try:
            module = importlib.import_module(module_name)
            factory = getattr(module, attribute)
        except (ImportError, AttributeError) as exc:
            raise PluginLoadError(f"cannot resolve plugin factory {path}: {exc}") from exc
        if not callable(factory):
            raise PluginLoadError(f"plugin factory is not callable: {path}")
        return factory

    def _construct(self, factory: Callable[..., Any], config: dict[str, Any]) -> Any:
        try:
            return factory(context=self.context, config=config)
        except TypeError:
            try:
                return factory(config=config)
            except TypeError:
                return factory()

    def _stop(self, instance: Any) -> None:
        if hasattr(instance, "stop"):
            try:
                instance.stop(self.context)
            except Exception as exc:
                raise PluginLoadError(f"plugin shutdown failed: {exc}") from exc
