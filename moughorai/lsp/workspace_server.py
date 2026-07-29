from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from moughorai.workspace import Project, ResolvedConfiguration, WorkspaceService

from .models import TextDocument
from .server import AtlasLanguageServer, LspProtocolError


WorkspaceAnalyzer = Callable[[TextDocument, Project, ResolvedConfiguration], Iterable[Any]]


class WorkspaceLanguageServer(AtlasLanguageServer):
    """LSP facade that routes documents through an Atlas workspace."""

    def __init__(self, root: str | Path, analyzer: WorkspaceAnalyzer) -> None:
        self.service = WorkspaceService(Path(root))
        self.workspace_analyzer = analyzer
        self._folders: tuple[str, ...] = (self.service.workspace.root.as_uri(),)
        super().__init__(self._analyze)

    @property
    def workspace_folders(self) -> tuple[str, ...]:
        return self._folders

    def project_for_uri(self, uri: str) -> Project | None:
        path = uri_to_path(uri)
        matches: list[tuple[int, str, Project]] = []
        for project in self.service.workspace.projects:
            try:
                path.relative_to(project.path.resolve())
            except ValueError:
                continue
            matches.append((len(project.path.resolve().parts), project.name, project))
        return max(matches, default=(0, "", None))[2]

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        request_id = message.get("id")
        try:
            if method == "initialize":
                params = message.get("params", {})
                folders = params.get("workspaceFolders") if isinstance(params, Mapping) else None
                if folders is not None:
                    self._folders = _folder_uris(folders)
                return self._response(request_id, {
                    "capabilities": {
                        "textDocumentSync": 1,
                        "codeActionProvider": True,
                        "diagnosticProvider": {
                            "identifier": "atlas",
                            "interFileDependencies": True,
                            "workspaceDiagnostics": True,
                        },
                        "workspace": {"workspaceFolders": {"supported": True, "changeNotifications": True}},
                    },
                    "serverInfo": {"name": "Atlas", "version": "1.0.0"},
                })
            if method == "workspace/didChangeWorkspaceFolders":
                self._change_folders(message.get("params", {}))
                return None
            if method == "workspace/diagnostic":
                return self._response(request_id, {"items": [self._workspace_item(document) for document in self.documents]})
            return super().handle(message)
        except (KeyError, TypeError, ValueError) as exc:
            if request_id is None:
                raise LspProtocolError(str(exc)) from exc
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": str(exc)}}

    def _analyze(self, document: TextDocument) -> Iterable[Any]:
        project = self.project_for_uri(document.uri)
        if project is None:
            return ()
        configuration = self.service.resolved_configuration(project.name)
        return self.workspace_analyzer(document, project, configuration)

    def _workspace_item(self, document: TextDocument) -> dict[str, Any]:
        payload = self.publisher.analyze(document)
        return {
            "uri": payload.uri,
            "version": payload.version,
            "kind": "full",
            "items": [item.to_dict() for item in payload.diagnostics],
        }

    def _change_folders(self, params: Any) -> None:
        event = params.get("event", {}) if isinstance(params, Mapping) else {}
        removed = set(_folder_uris(event.get("removed", ())))
        added = set(_folder_uris(event.get("added", ())))
        self._folders = tuple(sorted((set(self._folders) - removed) | added))


def uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in ("", "file"):
        raise ValueError(f"unsupported document URI scheme: {parsed.scheme}")
    raw = unquote(parsed.path) if parsed.scheme else uri
    if parsed.netloc:
        raw = f"//{parsed.netloc}{raw}"
    if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]
    return Path(raw).resolve()


def _folder_uris(values: Any) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, Mapping)) or not isinstance(values, Iterable):
        raise ValueError("workspace folders must be a list")
    result = []
    for value in values:
        if not isinstance(value, Mapping) or not isinstance(value.get("uri"), str):
            raise ValueError("workspace folder requires a URI")
        result.append(value["uri"])
    return tuple(sorted(set(result)))
