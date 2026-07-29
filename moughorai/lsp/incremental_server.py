from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from moughorai.workspace import Project, ResolvedConfiguration

from .editor import DocumentChangeSet, apply_document_changes
from .models import TextDocument
from .server import LspProtocolError
from .workspace_server import WorkspaceAnalyzer, WorkspaceLanguageServer


IncrementalWorkspaceAnalyzer = Callable[
    [TextDocument, Project, ResolvedConfiguration, DocumentChangeSet],
    Iterable[Any],
]


class IncrementalWorkspaceLanguageServer(WorkspaceLanguageServer):
    """Workspace LSP server with ordered range-edit analysis."""

    def __init__(
        self,
        root: str | Path,
        analyzer: WorkspaceAnalyzer,
        *,
        incremental_analyzer: IncrementalWorkspaceAnalyzer | None = None,
    ) -> None:
        super().__init__(root, analyzer)
        self.incremental_analyzer = incremental_analyzer
        self._last_changes: dict[str, DocumentChangeSet] = {}

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        if message.get("method") != "textDocument/didChange":
            return super().handle(message)
        params = message.get("params", {})
        request_id = message.get("id")
        try:
            item = params["textDocument"]
            uri = item["uri"]
            previous = next((document for document in self.documents if document.uri == uri), None)
            if previous is None:
                raise ValueError(f"document is not open: {uri}")
            change_set = apply_document_changes(previous, int(item["version"]), params.get("contentChanges", ()))
            self._documents[uri] = change_set.current
            self._last_changes[uri] = change_set
            project = self.project_for_uri(uri)
            if project is None:
                findings: Iterable[Any] = ()
            elif self.incremental_analyzer is None:
                findings = self.workspace_analyzer(
                    change_set.current,
                    project,
                    self._resolved_configuration(project.name),
                )
            else:
                findings = self.incremental_analyzer(
                    change_set.current,
                    project,
                    self._resolved_configuration(project.name),
                    change_set,
                )
            payload = self.publisher.publish(change_set.current, findings)
            return self._notification("textDocument/publishDiagnostics", payload.to_dict())
        except (KeyError, TypeError, ValueError) as exc:
            if request_id is None:
                raise LspProtocolError(str(exc)) from exc
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": str(exc)}}

    def last_changes(self, uri: str) -> DocumentChangeSet | None:
        return self._last_changes.get(uri)
