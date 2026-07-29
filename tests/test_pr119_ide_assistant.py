from pathlib import Path

import pytest

from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.ai_ide import (
    IdeAction,
    IdeAssistant,
    IdeAssistantError,
    IdeRequest,
    SupportedIde,
)
from moughorai.global_symbols import GlobalSymbol, GlobalSymbolKind
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.workspace import Project, Workspace


def _snapshot(tmp_path: Path):
    workspace = Workspace(tmp_path, (Project("app", tmp_path / "app"),))
    context = WorkspaceContextBuilder().build(
        workspace,
        symbols=(GlobalSymbol.create(GlobalSymbolKind.TYPE, "Service", "demo.Service"),),
    )
    return AtlasSemanticSnapshot.create(context, workspace_fingerprint="abc", analyzer_version="2")


@pytest.mark.parametrize("ide", list(SupportedIde))
def test_every_supported_ide_uses_same_snapshot_protocol(tmp_path: Path, ide: SupportedIde) -> None:
    snapshot = _snapshot(tmp_path)
    assistant = IdeAssistant(lambda identifier: snapshot, {})
    response = assistant.handle(IdeRequest(ide, IdeAction.NAVIGATE, snapshot.snapshot_id, "service"))
    assert response.payload["matches"][0]["qualified_name"] == "demo.Service"
    assert '"snapshot_id"' in response.to_json()


def test_reasoning_actions_route_without_source_code(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    assistant = IdeAssistant(
        lambda identifier: snapshot,
        {IdeAction.EXPLAIN: lambda snap, request: {"markdown": "Verified"}},
    )
    response = assistant.handle(IdeRequest(SupportedIde.VSCODE, IdeAction.EXPLAIN, snapshot.snapshot_id))
    assert response.payload == {"markdown": "Verified"}
    with pytest.raises(IdeAssistantError, match="raw source"):
        IdeRequest(
            SupportedIde.NEOVIM,
            IdeAction.ASK,
            snapshot.snapshot_id,
            parameters={"source": "secret"},
        )


def test_unknown_snapshot_and_unconfigured_action_fail(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    assistant = IdeAssistant(lambda identifier: None, {})
    with pytest.raises(IdeAssistantError, match="unknown"):
        assistant.handle(IdeRequest(SupportedIde.ECLIPSE, IdeAction.REVIEW, snapshot.snapshot_id))
