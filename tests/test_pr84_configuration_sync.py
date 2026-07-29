from pathlib import Path

import pytest

from moughorai.lsp import ConfigurationSyncState, WorkspaceLanguageServer, flatten_settings


def workspace(tmp_path: Path, mode: str = "initial") -> Path:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "atlas.yaml").write_text(
        f"options:\n  mode: {mode}\nprojects:\n- name: app\n  path: app\n"
    )
    return tmp_path


def opened(server, uri):
    return server.handle({
        "method": "textDocument/didOpen",
        "params": {"textDocument": {"uri": uri, "text": "x", "version": 1}},
    })


def test_flatten_settings_strips_atlas_and_sorts() -> None:
    assert flatten_settings({"atlas": {"z": 1, "nested": {"b": 2, "a": 1}}}) == {
        "nested.a": 1, "nested.b": 2, "z": 1
    }


def test_sync_state_increments_generation() -> None:
    state = ConfigurationSyncState().update({"atlas": {"mode": "strict"}})
    assert state.generation == 1
    assert state.as_dict() == {"mode": "strict"}


def test_initialize_advertises_configuration_support(tmp_path: Path) -> None:
    result = WorkspaceLanguageServer(workspace(tmp_path), lambda document, project, config: ()).handle(
        {"id": 1, "method": "initialize", "params": {}}
    )
    assert result["result"]["capabilities"]["workspace"]["configuration"] is True


def test_client_settings_override_and_republish(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    uri = (root / "app" / "main.py").as_uri()
    modes = []
    server = WorkspaceLanguageServer(
        root,
        lambda document, project, config: modes.append(config.get("mode")) or [{"message": config.get("mode")}],
    )
    opened(server, uri)
    assert server.handle({
        "method": "workspace/didChangeConfiguration",
        "params": {"settings": {"atlas": {"mode": "client"}}},
    }) is None
    notifications = server.drain_notifications()
    assert modes == ["initial", "client"]
    assert server.configuration_generation == 1
    assert notifications[0]["params"]["diagnostics"][0]["message"] == "client"


def test_drain_notifications_is_destructive(tmp_path: Path) -> None:
    server = WorkspaceLanguageServer(workspace(tmp_path), lambda document, project, config: ())
    server.handle({"method": "workspace/didChangeConfiguration", "params": {"settings": {}}})
    assert server.drain_notifications() == ()
    assert server.drain_notifications() == ()


def test_workspace_configuration_request_is_scope_aware(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    uri = (root / "app" / "main.py").as_uri()
    server = WorkspaceLanguageServer(root, lambda document, project, config: ())
    server.handle({
        "method": "workspace/didChangeConfiguration",
        "params": {"settings": {"atlas": {"mode": "client", "nested": {"enabled": True}}}},
    })
    result = server.handle({
        "id": 4,
        "method": "workspace/configuration",
        "params": {"items": [
            {"scopeUri": uri, "section": "atlas.mode"},
            {"scopeUri": uri, "section": "atlas.nested"},
        ]},
    })
    assert result["result"] == ["client", {"enabled": True}]


def test_watched_atlas_file_reload_republishes(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    uri = (root / "app" / "main.py").as_uri()
    seen = []
    server = WorkspaceLanguageServer(root, lambda document, project, config: seen.append(config.get("mode")) or ())
    opened(server, uri)
    workspace(tmp_path, "reloaded")
    server.handle({
        "method": "workspace/didChangeWatchedFiles",
        "params": {"changes": [{"uri": (root / "atlas.yaml").as_uri(), "type": 2}]},
    })
    assert seen == ["initial", "reloaded"]
    assert server.configuration_generation == 1
    assert len(server.drain_notifications()) == 1


def test_unrelated_watched_file_does_not_reload(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    server = WorkspaceLanguageServer(root, lambda document, project, config: ())
    server.handle({
        "method": "workspace/didChangeWatchedFiles",
        "params": {"changes": [{"uri": (root / "other.txt").as_uri(), "type": 2}]},
    })
    assert server.configuration_generation == 0


def test_invalid_reload_preserves_service_and_state(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    server = WorkspaceLanguageServer(root, lambda document, project, config: ())
    original = server.service
    (root / "atlas.yaml").write_text("projects: [")
    with pytest.raises(Exception):
        server.handle({
            "method": "workspace/didChangeWatchedFiles",
            "params": {"changes": [{"uri": (root / "atlas.yaml").as_uri()}]},
        })
    assert server.service is original
    assert server.configuration_generation == 0


def test_bad_settings_request_returns_error(tmp_path: Path) -> None:
    server = WorkspaceLanguageServer(workspace(tmp_path), lambda document, project, config: ())
    result = server.handle({
        "id": 8,
        "method": "workspace/didChangeConfiguration",
        "params": {"settings": "bad"},
    })
    assert result["error"]["code"] == -32602
