from pathlib import Path

import pytest

from moughorai.lsp import WorkspaceLanguageServer, uri_to_path


def workspace(tmp_path: Path) -> Path:
    (tmp_path / "core" / "nested").mkdir(parents=True)
    (tmp_path / "api").mkdir()
    (tmp_path / "atlas.yaml").write_text(
        "options:\n  mode: workspace\n"
        "projects:\n"
        "- name: core\n  path: core\n  options:\n    mode: core\n"
        "- name: nested\n  path: core/nested\n"
        "- name: api\n  path: api\n  dependencies: [core]\n"
    )
    return tmp_path


def open_message(path: Path, text: str = "bad", version: int = 1):
    return {
        "method": "textDocument/didOpen",
        "params": {"textDocument": {"uri": path.as_uri(), "text": text, "version": version, "languageId": "python"}},
    }


def test_initialize_advertises_workspace_diagnostics(tmp_path: Path) -> None:
    server = WorkspaceLanguageServer(workspace(tmp_path), lambda document, project, config: ())
    result = server.handle({"id": 1, "method": "initialize", "params": {}})
    capabilities = result["result"]["capabilities"]
    assert capabilities["diagnosticProvider"]["workspaceDiagnostics"] is True
    assert capabilities["diagnosticProvider"]["interFileDependencies"] is True
    assert capabilities["workspace"]["workspaceFolders"]["supported"] is True
    assert result["result"]["serverInfo"] == {"name": "Atlas", "version": "1.0.0"}


def test_routes_document_to_most_specific_project_and_configuration(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    seen = []

    def analyzer(document, project, configuration):
        seen.append((project.name, configuration.get("mode")))
        return [{"message": project.name, "line": 1}]

    result = WorkspaceLanguageServer(root, analyzer).handle(open_message(root / "core" / "nested" / "x.py"))
    assert seen == [("nested", "workspace")]
    assert result["params"]["diagnostics"][0]["message"] == "nested"


def test_project_configuration_override_is_resolved(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    seen = []
    server = WorkspaceLanguageServer(root, lambda document, project, config: seen.append(config.get("mode")) or ())
    server.handle(open_message(root / "core" / "x.py"))
    assert seen == ["core"]


def test_document_outside_workspace_has_no_diagnostics(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    result = WorkspaceLanguageServer(root, lambda document, project, config: [{"message": "unexpected"}]).handle(
        open_message(tmp_path.parent / "outside.py")
    )
    assert result["params"]["diagnostics"] == []


def test_workspace_diagnostics_are_uri_sorted_and_full(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    server = WorkspaceLanguageServer(root, lambda document, project, config: [{"message": project.name}])
    server.handle(open_message(root / "core" / "z.py"))
    server.handle(open_message(root / "api" / "a.py"))
    result = server.handle({"id": 7, "method": "workspace/diagnostic", "params": {}})
    items = result["result"]["items"]
    assert [item["uri"] for item in items] == sorted(item["uri"] for item in items)
    assert all(item["kind"] == "full" for item in items)


def test_workspace_folder_changes_are_deterministic(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    server = WorkspaceLanguageServer(root, lambda document, project, config: ())
    original = root.as_uri()
    extra = (tmp_path / "extra").as_uri()
    server.handle({
        "method": "workspace/didChangeWorkspaceFolders",
        "params": {"event": {"removed": [{"uri": original}], "added": [{"uri": extra}, {"uri": extra}]}},
    })
    assert server.workspace_folders == (extra,)


def test_documents_property_is_sorted(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    server = WorkspaceLanguageServer(root, lambda document, project, config: ())
    server.handle(open_message(root / "core" / "z.py"))
    server.handle(open_message(root / "api" / "a.py"))
    assert [item.uri for item in server.documents] == sorted(item.uri for item in server.documents)


def test_uri_conversion_handles_spaces(tmp_path: Path) -> None:
    path = tmp_path / "with space.py"
    assert uri_to_path(path.as_uri()) == path.resolve()


def test_uri_conversion_rejects_non_file_scheme() -> None:
    with pytest.raises(ValueError, match="scheme"):
        uri_to_path("https://example.test/file.py")


def test_bad_workspace_folder_request_returns_protocol_error(tmp_path: Path) -> None:
    server = WorkspaceLanguageServer(workspace(tmp_path), lambda document, project, config: ())
    result = server.handle({"id": 4, "method": "initialize", "params": {"workspaceFolders": "bad"}})
    assert result["error"]["code"] == -32602
