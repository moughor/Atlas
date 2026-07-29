from pathlib import Path

import pytest

from moughorai.lsp import (
    IncrementalWorkspaceLanguageServer,
    Position,
    TextDocument,
    apply_document_changes,
    position_to_offset,
)


def workspace(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "atlas.yaml").write_text("projects:\n- name: app\n  path: app\n")
    return tmp_path


def changes(uri: str, version: int, content):
    return {
        "method": "textDocument/didChange",
        "params": {"textDocument": {"uri": uri, "version": version}, "contentChanges": content},
    }


def test_position_to_offset_multiline() -> None:
    assert position_to_offset("one\ntwo\n", Position(1, 2)) == 6
    assert position_to_offset("one\n", Position(1, 0)) == 4


def test_position_outside_document_rejected() -> None:
    with pytest.raises(ValueError, match="outside"):
        position_to_offset("one", Position(1, 1))


def test_apply_single_range_change() -> None:
    previous = TextDocument("file:///x", "hello world", 1)
    result = apply_document_changes(previous, 2, [{
        "range": {"start": {"line": 0, "character": 6}, "end": {"line": 0, "character": 11}},
        "text": "Atlas",
    }])
    assert result.current.text == "hello Atlas"
    assert result.previous is previous


def test_apply_ordered_multiple_changes() -> None:
    previous = TextDocument("file:///x", "a\nb\n", 1)
    result = apply_document_changes(previous, 2, [
        {"range": {"start": {"line": 0, "character": 1}, "end": {"line": 0, "character": 1}}, "text": "1"},
        {"range": {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 1}}, "text": "B"},
    ])
    assert result.current.text == "a1\nB\n"


def test_full_change_replaces_document() -> None:
    result = apply_document_changes(TextDocument("u", "old", 1), 2, [{"text": "new"}])
    assert result.current.text == "new"
    assert result.changes[0].range is None


def test_versions_must_increase() -> None:
    with pytest.raises(ValueError, match="increase"):
        apply_document_changes(TextDocument("u", "x", 2), 2, [{"text": "y"}])


def test_incremental_callback_receives_change_set(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    uri = (root / "app" / "main.py").as_uri()
    seen = []
    server = IncrementalWorkspaceLanguageServer(
        root,
        lambda document, project, config: (),
        incremental_analyzer=lambda document, project, config, change_set: seen.append(change_set) or [
            {"message": document.text, "line": 1}
        ],
    )
    server.handle({"method": "textDocument/didOpen", "params": {"textDocument": {"uri": uri, "text": "bad", "version": 1}}})
    result = server.handle(changes(uri, 2, [{
        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 3}},
        "text": "good",
    }]))
    assert len(seen) == 1
    assert seen[0].previous.text == "bad"
    assert seen[0].current.text == "good"
    assert result["params"]["diagnostics"][0]["message"] == "good"


def test_fallback_full_analyzer_runs_on_change(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    uri = (root / "app" / "main.py").as_uri()
    seen = []
    server = IncrementalWorkspaceLanguageServer(
        root,
        lambda document, project, config: seen.append(document.text) or (),
    )
    server.handle({"method": "textDocument/didOpen", "params": {"textDocument": {"uri": uri, "text": "a", "version": 1}}})
    server.handle(changes(uri, 2, [{"text": "b"}]))
    assert seen == ["a", "b"]


def test_change_requires_open_document(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    uri = (root / "app" / "main.py").as_uri()
    with pytest.raises(Exception, match="not open"):
        IncrementalWorkspaceLanguageServer(root, lambda document, project, config: ()).handle(
            changes(uri, 1, [{"text": "x"}])
        )


def test_request_error_is_returned_for_stale_change(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    uri = (root / "app" / "main.py").as_uri()
    server = IncrementalWorkspaceLanguageServer(root, lambda document, project, config: ())
    server.handle({"method": "textDocument/didOpen", "params": {"textDocument": {"uri": uri, "text": "a", "version": 2}}})
    message = changes(uri, 2, [{"text": "b"}])
    message["id"] = 9
    result = server.handle(message)
    assert result["error"]["code"] == -32602


def test_last_changes_is_recorded(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    uri = (root / "app" / "main.py").as_uri()
    server = IncrementalWorkspaceLanguageServer(root, lambda document, project, config: ())
    server.handle({"method": "textDocument/didOpen", "params": {"textDocument": {"uri": uri, "text": "a", "version": 1}}})
    server.handle(changes(uri, 2, [{"text": "b"}]))
    assert server.last_changes(uri).current.text == "b"
