from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.ai_ask import AskResult, CitationValidation
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.atlas_cli import app
from moughorai.llm import ScriptedLlmProvider
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


runner = CliRunner()


def _snapshot() -> AtlasSemanticSnapshot:
    return AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext({"schema_version": 1}),
        workspace_fingerprint="workspace:pr139-cli",
        analyzer_version="test",
    )


def _install_engine_stub(
    monkeypatch,
    *,
    citations: CitationValidation = CitationValidation(),
) -> list[object]:
    captured: list[object] = []
    snapshot = _snapshot()

    class CapturingAskEngine:
        def __init__(self, client, *, memory) -> None:
            captured.extend((client, memory))

        def ask(self, loaded, request):
            captured.extend((loaded, request))
            return AskResult(
                "Grounded answer",
                snapshot.snapshot_id,
                request.conversation_id,
                citations=citations,
                provider="scripted",
                model="test-model",
                limitations=("Capability coverage is partial.",),
            )

    monkeypatch.setattr(atlas_cli, "AskEngine", CapturingAskEngine)
    monkeypatch.setattr(atlas_cli, "_load_ai_snapshot", lambda root, path: snapshot)
    monkeypatch.setattr(
        atlas_cli,
        "_ai_provider_factory",
        lambda: ScriptedLlmProvider([]),
    )
    return captured


def test_ask_and_chat_help_expose_the_same_grounded_options() -> None:
    namespace = runner.invoke(app, ["ai", "--help"])

    assert namespace.exit_code == 0
    assert "ask" in namespace.stdout
    assert "chat" in namespace.stdout
    for command in ("ask", "chat"):
        result = runner.invoke(app, ["ai", command, "--help"])
        assert result.exit_code == 0
        for option in ("--conversation", "--subject", "--capability", "--json"):
            assert option in result.stdout


def test_chat_alias_options_produce_the_same_deterministic_json_envelope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured = _install_engine_stub(monkeypatch)
    arguments = [
        "Explain the impact and security evidence",
        str(tmp_path),
        "--conversation",
        "17",
        "--subject",
        "type:demo.Service",
        "--capability",
        "security",
        "--capability",
        "impact",
        "--json",
    ]

    ask = runner.invoke(app, ["ai", "ask", *arguments])
    chat = runner.invoke(app, ["ai", "chat", *arguments])

    assert ask.exit_code == 0
    assert chat.exit_code == 0
    assert ask.stdout == chat.stdout
    assert ask.stderr == chat.stderr == ""
    assert ask.stdout.startswith('{"answer":"Grounded answer","citations":')
    payload = json.loads(ask.stdout)
    assert payload == {
        "answer": "Grounded answer",
        "citations": {
            "accepted_evidence_ids": [],
            "cited_evidence_ids": [],
            "missing_required": False,
            "unknown_citation_ids": [],
            "valid": True,
        },
        "context": None,
        "conversation_id": 17,
        "limitations": ["Capability coverage is partial."],
        "model": "test-model",
        "provider": "scripted",
        "snapshot_id": _snapshot().snapshot_id,
        "grounded": False,
    }

    requests = [captured[3], captured[7]]
    for request in requests:
        assert request.conversation_id == 17
        assert request.subject == "type:demo.Service"
        assert request.capabilities == (
            "impact_prediction",
            "security_intelligence",
        )


def test_plain_chat_warns_when_provider_citations_are_not_grounded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_engine_stub(monkeypatch)

    result = runner.invoke(
        app,
        ["ai", "chat", "Explain this repository", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert result.stdout == "Grounded answer\n"
    assert result.stderr == (
        "warning: provider grounding citations were incomplete; "
        "use --json for validation details\n"
    )


def test_plain_chat_warns_when_no_atlas_evidence_was_selected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_engine_stub(monkeypatch)

    result = runner.invoke(
        app,
        ["ai", "chat", "Explain this repository", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert result.stdout == "Grounded answer\n"
    assert "grounding citations were incomplete" in result.stderr
