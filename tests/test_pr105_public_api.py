from __future__ import annotations

import json
from pathlib import Path

from moughorai import public_api
from moughorai.api import AnalysisRequest
from moughorai.workspace import Project


def test_public_facade_preserves_existing_type_identity() -> None:
    assert public_api.AnalysisRequest is AnalysisRequest
    assert public_api.Project is Project


def test_public_manifest_matches_frozen_signatures() -> None:
    assert public_api.PUBLIC_API_VERSION == "1.0"
    assert public_api.public_api_manifest() == dict(public_api.PUBLIC_API_SIGNATURES)
    assert public_api.public_api_compatibility_issues() == ()


def test_public_manifest_matches_independent_v1_release_fixture() -> None:
    fixture = Path(__file__).parent / "fixtures" / "public_api_v1.json"
    expected = json.loads(fixture.read_text(encoding="utf-8"))

    assert expected["public_api_version"] == public_api.PUBLIC_API_VERSION
    assert expected["signatures"] == public_api.public_api_manifest()


def test_compatibility_check_reports_removal_and_signature_change() -> None:
    expected = dict(public_api.PUBLIC_API_SIGNATURES)
    expected["Project"] = "(broken)"
    expected["RemovedType"] = "()"

    assert public_api.public_api_compatibility_issues(expected) == (
        f"changed public signature: Project: (broken) -> {public_api.PUBLIC_API_SIGNATURES['Project']}",
        "removed public export: RemovedType",
    )


def test_compatibility_check_reports_a_missing_runtime_export(monkeypatch) -> None:
    monkeypatch.delattr(public_api, "Project")

    assert "removed public export: Project" in (
        public_api.public_api_compatibility_issues()
    )


def test_all_exports_resolve_and_are_deliberately_bounded() -> None:
    assert all(hasattr(public_api, name) for name in public_api.__all__)
    assert "WorkspaceRecoveryManager" not in public_api.__all__
    assert "PluginTrustStore" not in public_api.__all__
