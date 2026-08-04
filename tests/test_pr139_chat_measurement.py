from pathlib import Path

from moughorai.ai_ask import AskEngine, AskRequest
from moughorai.ai_context import WorkspaceContextBuilder
from moughorai.llm import LlmClient, ScriptedLlmProvider
from moughorai.measurement import MeasurementConfig, MeasurementSession
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.workspace import Project, Workspace


def _snapshot(tmp_path: Path) -> AtlasSemanticSnapshot:
    workspace = Workspace(tmp_path, (Project("app", tmp_path / "app"),))
    return AtlasSemanticSnapshot.create(
        WorkspaceContextBuilder().build(workspace),
        workspace_fingerprint="pr139-measurement",
        analyzer_version="test/1",
    )


def test_chat_measurement_separates_context_prompt_and_provider(tmp_path: Path) -> None:
    session = MeasurementSession(MeasurementConfig(
        enabled=True,
        capture_process_memory=True,
    ))
    result = AskEngine(
        LlmClient(ScriptedLlmProvider(("Insufficient structured evidence.",))),
        measurement=session,
    ).ask(_snapshot(tmp_path), AskRequest("Where is app?"))

    assert result.answer == "Insufficient structured evidence."
    report = session.report()
    phases = tuple(item.phase_id for item in report.samples)
    assert phases == (
        "engineering_chat.context",
        "engineering_chat.prompt",
        "engineering_chat.provider",
    )
    assert all(item.succeeded for item in report.samples)
    assert report.samples[0].consumer == "engineering-chat"
    assert report.samples[-1].consumer == "engineering-chat-provider"
