from pathlib import Path

import pytest

from moughorai.lsp import AtlasLanguageServer, CodeAction, DefaultCodeActionProvider, TextDocument


URI = "file:///Example.java"


def open_document(server: AtlasLanguageServer) -> None:
    server.handle({
        "method": "textDocument/didOpen",
        "params": {"textDocument": {"uri": URI, "text": "unsafe", "version": 1}},
    })


def request(server: AtlasLanguageServer, *, only=()):
    return server.handle({
        "id": 4,
        "method": "textDocument/codeAction",
        "params": {"textDocument": {"uri": URI}, "context": {"only": list(only)}},
    })


def analyzer(document):
    return [
        {"message": "z finding", "rule_id": "Z", "line": 1},
        {"message": "a finding", "rule_id": "A", "line": 1},
    ]


def test_initialize_advertises_code_actions() -> None:
    result = AtlasLanguageServer(analyzer).handle({"id": 1, "method": "initialize"})
    assert result["result"]["capabilities"]["codeActionProvider"] is True


def test_default_actions_are_deterministic() -> None:
    server = AtlasLanguageServer(analyzer)
    open_document(server)
    actions = request(server)["result"]
    assert [item["title"] for item in actions] == [
        "Explain A", "Explain Z", "Suppress A", "Suppress Z", "Rescan document"
    ]


def test_actions_retain_diagnostics_and_commands() -> None:
    server = AtlasLanguageServer(analyzer)
    open_document(server)
    action = request(server)["result"][0]
    assert action["diagnostics"][0]["code"] == "A"
    assert action["command"]["command"] == "atlas.explainFinding"
    assert action["command"]["arguments"] == [{"uri": URI, "code": "A"}]


def test_context_only_filters_action_kinds() -> None:
    server = AtlasLanguageServer(analyzer)
    open_document(server)
    assert [item["title"] for item in request(server, only=("source",))["result"]] == ["Rescan document"]
    assert all(item["kind"] == "quickfix" for item in request(server, only=("quickfix",))["result"])


def test_request_for_closed_document_is_protocol_error() -> None:
    with pytest.raises(Exception, match="not open"):
        AtlasLanguageServer(analyzer).handle({
            "method": "textDocument/codeAction",
            "params": {"textDocument": {"uri": URI}, "context": {}},
        })


def test_request_error_is_returned_when_id_present() -> None:
    result = request(AtlasLanguageServer(analyzer))
    assert result["error"]["code"] == -32602


def test_custom_provider_is_supported() -> None:
    class Provider:
        def actions(self, document, diagnostics):
            return (CodeAction("Custom", "refactor", "demo.custom", arguments=(document.uri,)),)

    server = AtlasLanguageServer(analyzer, code_action_provider=Provider())
    open_document(server)
    assert request(server)["result"][0]["command"]["command"] == "demo.custom"


def test_action_validation() -> None:
    with pytest.raises(ValueError, match="title"):
        CodeAction("", "quickfix", "x")
    with pytest.raises(ValueError, match="kind"):
        CodeAction("x", "", "x")
    with pytest.raises(ValueError, match="command"):
        CodeAction("x", "quickfix", "")


def test_provider_returns_rescan_when_no_diagnostics() -> None:
    actions = DefaultCodeActionProvider().actions(TextDocument(URI, "safe"), ())
    assert [item.title for item in actions] == ["Rescan document"]


def test_action_serialization_omits_empty_optional_fields() -> None:
    value = CodeAction("Custom", "source", "demo").to_dict()
    assert "diagnostics" not in value
    assert "data" not in value
