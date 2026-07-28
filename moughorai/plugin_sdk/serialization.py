from __future__ import annotations

import json
from typing import Any

import yaml

from .models import PluginManifest


def manifest_to_dict(manifest: PluginManifest) -> dict[str, Any]:
    return {
        "id": manifest.plugin_id,
        "version": manifest.version,
        "api_version": manifest.api_version,
        "name": manifest.name,
        "description": manifest.description,
        "requires": list(manifest.requires),
        "metadata": dict(sorted(manifest.metadata.items())),
        "extensions": [
            {
                "name": extension.name,
                "point": extension.point.value,
                "factory": extension.factory,
                "capabilities": list(extension.capabilities),
                "config": dict(sorted(extension.config.items())),
            }
            for extension in manifest.extensions
        ],
    }


def manifest_to_json(manifest: PluginManifest) -> str:
    return json.dumps(manifest_to_dict(manifest), indent=2, sort_keys=True) + "\n"


def manifest_to_yaml(manifest: PluginManifest) -> str:
    return yaml.safe_dump(manifest_to_dict(manifest), sort_keys=False, allow_unicode=True)
