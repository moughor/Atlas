from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .loader import PluginManifestLoader
from .models import PluginDiagnostic, PluginManifest, PluginManifestError
from .trust import PluginPermissionPolicy, PluginTrustError, PluginTrustStore, plugin_bundle_digest


@dataclass(frozen=True, slots=True)
class DiscoveredPlugin:
    root: Path
    manifest_path: Path
    manifest: PluginManifest
    digest: str
    trusted: bool
    granted_permissions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PluginDiscoveryResult:
    plugins: tuple[DiscoveredPlugin, ...]
    diagnostics: tuple[PluginDiagnostic, ...]


class PluginDiscovery:
    MANIFEST_NAMES = ("plugin.yaml", "plugin.yml", "plugin.json")

    def __init__(
        self,
        *,
        loader: PluginManifestLoader | None = None,
        trust_store: PluginTrustStore | None = None,
        permission_policy: PluginPermissionPolicy | None = None,
        require_trust: bool = False,
    ) -> None:
        self.loader = loader or PluginManifestLoader()
        self.trust_store = trust_store
        self.permission_policy = permission_policy
        self.require_trust = require_trust

    def discover(self, roots: Iterable[str | Path]) -> PluginDiscoveryResult:
        found: list[DiscoveredPlugin] = []
        diagnostics: list[PluginDiagnostic] = []
        seen: dict[str, Path] = {}
        for root in sorted((Path(item) for item in roots), key=lambda item: str(item)):
            for manifest_path in self._manifest_paths(root):
                try:
                    plugin = self._load(manifest_path)
                    previous = seen.get(plugin.manifest.plugin_id)
                    if previous is not None:
                        raise PluginManifestError(
                            f"duplicate discovered plugin {plugin.manifest.plugin_id}: {previous} and {manifest_path}"
                        )
                    seen[plugin.manifest.plugin_id] = manifest_path
                    found.append(plugin)
                except (PluginManifestError, PluginTrustError) as exc:
                    diagnostics.append(PluginDiagnostic(
                        "error", "plugin-quarantined", str(exc), self._safe_plugin_id(manifest_path)
                    ))
        return PluginDiscoveryResult(
            tuple(sorted(found, key=lambda item: item.manifest.plugin_id)),
            tuple(sorted(diagnostics, key=lambda item: (item.plugin_id or "", item.message))),
        )

    def _load(self, manifest_path: Path) -> DiscoveredPlugin:
        manifest = self.loader.load_path(manifest_path)
        digest = plugin_bundle_digest(manifest, manifest_path.parent)
        trusted = False
        if self.trust_store is not None:
            try:
                self.trust_store.verify(manifest, digest)
                trusted = True
            except PluginTrustError:
                if self.require_trust:
                    raise
        elif self.require_trust:
            raise PluginTrustError(f"plugin is not trusted: {manifest.plugin_id} {manifest.version}")
        granted: tuple[str, ...] = ()
        if self.permission_policy is not None:
            granted = self.permission_policy.require(manifest).granted
        return DiscoveredPlugin(manifest_path.parent, manifest_path, manifest, digest, trusted, granted)

    def _manifest_paths(self, root: Path) -> tuple[Path, ...]:
        if root.is_file():
            return (root,)
        if not root.exists():
            return ()
        paths = []
        for name in self.MANIFEST_NAMES:
            direct = root / name
            if direct.is_file():
                paths.append(direct)
            paths.extend(path for path in root.glob(f"*/{name}") if path.is_file())
        return tuple(sorted(set(paths), key=lambda item: str(item)))

    def _safe_plugin_id(self, manifest_path: Path) -> str | None:
        try:
            return self.loader.load_path(manifest_path).plugin_id
        except Exception:
            return None
