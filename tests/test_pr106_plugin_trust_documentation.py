from __future__ import annotations

from pathlib import Path

from moughorai.plugin_sdk import PluginDiscovery, PluginRuntime


ROOT = Path(__file__).parents[1]


def test_trust_model_states_non_sandbox_boundary() -> None:
    text = (ROOT / "docs" / "PR106_PLUGIN_TRUST_MODEL.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for required in (
        "trusted in-process Python code",
        "does **not** provide a sandbox",
        "admission gate, not capability enforcement",
        "unauthenticated operator metadata",
        "time-of-check/time-of-use",
        "OS-level sandbox",
    ):
        assert required in normalized


def test_trust_model_documents_opt_in_defaults_that_match_runtime() -> None:
    discovery = PluginDiscovery()

    assert discovery.require_trust is False
    assert discovery.permission_policy is None
    assert PluginRuntime.__init__.__kwdefaults__ == {
        "services": None,
        "permission_policy": None,
    }

    text = (ROOT / "docs" / "PR106_PLUGIN_TRUST_MODEL.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "Without `require_trust=True`, an untrusted plugin may be discovered." in normalized
    assert "Without a permission policy, requested permissions do not prevent runtime loading." in normalized


def test_pr60_documentation_links_to_complete_trust_model() -> None:
    text = (ROOT / "docs" / "PR60_PLUGIN_TRUST_AND_PERMISSIONS.md").read_text(encoding="utf-8")

    assert "admission controls, not" in text
    assert "PR106_PLUGIN_TRUST_MODEL.md" in text
