from __future__ import annotations

from dataclasses import dataclass
import json
import pytest

from moughorai.lsp import (
    AtlasLanguageServer, DiagnosticPublisher, DiagnosticSeverity, Position, Range,
    TextDocument, finding_to_diagnostic, offset_to_position, offsets_to_range,
)


@dataclass
class Finding:
    message: str = "unsafe call"
    rule_id: str = "SEC-1"
    severity: str = "high"
    line: int = 2
    column: int = 3
    end_line: int = 2
    end_column: int = 8


def analyzer(document):
    if "unsafe" in document.text:
        return [Finding()]
    return []


def test_position_validation():
    with pytest.raises(ValueError): Position(-1, 0)

def test_range_validation():
    with pytest.raises(ValueError): Range(Position(1, 0), Position(0, 0))

def test_offset_to_position_first_line(): assert offset_to_position("abc", 2) == Position(0, 2)
def test_offset_to_position_multiline(): assert offset_to_position("a\nbc", 3) == Position(1, 1)
def test_offset_at_end(): assert offset_to_position("a\n", 2) == Position(1, 0)
def test_offset_negative_rejected():
    with pytest.raises(ValueError): offset_to_position("a", -1)
def test_offset_too_large_rejected():
    with pytest.raises(ValueError): offset_to_position("a", 2)
def test_offsets_to_range(): assert offsets_to_range("abc", 0, 2) == Range(Position(0,0), Position(0,2))
def test_offsets_reverse_rejected():
    with pytest.raises(ValueError): offsets_to_range("abc", 2, 1)

def test_finding_object_conversion():
    d = finding_to_diagnostic(TextDocument("file:///A.java", "x\nunsafe"), Finding())
    assert d.code == "SEC-1" and d.severity == DiagnosticSeverity.ERROR
    assert d.range.start == Position(1, 2)

def test_finding_mapping_offsets():
    d = finding_to_diagnostic(TextDocument("u", "a\nunsafe"), {"message":"m","start_offset":2,"end_offset":8})
    assert d.range == Range(Position(1,0), Position(1,6))

def test_finding_metadata_is_deterministic():
    d = finding_to_diagnostic(TextDocument("u", "x"), {"message":"m","metadata":{"b":2,"a":1}})
    assert d.data == (("a","1"),("b","2"))

def test_unknown_severity_defaults_warning():
    d = finding_to_diagnostic(TextDocument("u", "x"), {"message":"m","severity":"weird"})
    assert d.severity == DiagnosticSeverity.WARNING

def test_document_validation():
    with pytest.raises(ValueError): TextDocument("", "")

def test_publisher_analyzes():
    p = DiagnosticPublisher(analyzer)
    result = p.analyze(TextDocument("u", "unsafe", 1))
    assert len(result.diagnostics) == 1

def test_publisher_stable_sorting():
    p = DiagnosticPublisher(lambda _: [{"message":"z","code":"z","line":2},{"message":"a","code":"a","line":1}])
    result = p.analyze(TextDocument("u", "x", 1))
    assert [d.message for d in result.diagnostics] == ["a","z"]

def test_publisher_rejects_stale_versions():
    p = DiagnosticPublisher(analyzer); p.analyze(TextDocument("u", "", 2))
    with pytest.raises(ValueError): p.analyze(TextDocument("u", "", 1))

def test_publisher_clear():
    p = DiagnosticPublisher(analyzer); p.analyze(TextDocument("u", "unsafe", 1))
    assert p.clear("u", version=2).diagnostics == ()

def test_publisher_last():
    p = DiagnosticPublisher(analyzer); result=p.analyze(TextDocument("u","",1))
    assert p.last("u") is result

def test_initialize():
    result = AtlasLanguageServer(analyzer).handle({"jsonrpc":"2.0","id":1,"method":"initialize"})
    assert result["result"]["capabilities"]["textDocumentSync"] == 1

def test_open_publishes():
    result = AtlasLanguageServer(analyzer).handle({"jsonrpc":"2.0","method":"textDocument/didOpen","params":{"textDocument":{"uri":"u","text":"unsafe","version":1}}})
    assert result["method"] == "textDocument/publishDiagnostics"
    assert len(result["params"]["diagnostics"]) == 1

def test_change_replaces_text():
    server=AtlasLanguageServer(analyzer)
    server.handle({"method":"textDocument/didOpen","params":{"textDocument":{"uri":"u","text":"unsafe","version":1}}})
    result=server.handle({"method":"textDocument/didChange","params":{"textDocument":{"uri":"u","version":2},"contentChanges":[{"text":"safe"}]}})
    assert result["params"]["diagnostics"] == []

def test_change_requires_content():
    server=AtlasLanguageServer(analyzer)
    with pytest.raises(Exception): server.handle({"method":"textDocument/didChange","params":{"textDocument":{"uri":"u","version":1}}})

def test_close_clears():
    server=AtlasLanguageServer(analyzer)
    server.handle({"method":"textDocument/didOpen","params":{"textDocument":{"uri":"u","text":"unsafe","version":1}}})
    result=server.handle({"method":"textDocument/didClose","params":{"textDocument":{"uri":"u"}}})
    assert result["params"]["diagnostics"] == []

def test_shutdown_response():
    assert AtlasLanguageServer(analyzer).handle({"id":2,"method":"shutdown"})["result"] is None

def test_exit_returns_none(): assert AtlasLanguageServer(analyzer).handle({"method":"exit"}) is None

def test_unsupported_request_returns_error():
    result=AtlasLanguageServer(analyzer).handle({"id":1,"method":"wat"})
    assert result["error"]["code"] == -32602

def test_handle_json_deterministic():
    text=AtlasLanguageServer(analyzer).handle_json('{"id":1,"method":"shutdown"}')
    assert text == '{"id":1,"jsonrpc":"2.0","result":null}'

def test_handle_invalid_json():
    with pytest.raises(Exception): AtlasLanguageServer(analyzer).handle_json('{')

def test_publish_to_dict():
    p=DiagnosticPublisher(analyzer).analyze(TextDocument("u","unsafe",1)).to_dict()
    assert p["uri"] == "u" and p["version"] == 1
