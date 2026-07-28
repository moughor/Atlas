from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Mapping

from .diagnostics import DiagnosticPublisher
from .models import TextDocument


class LspProtocolError(ValueError):
    pass


class AtlasLanguageServer:
    def __init__(self, analyzer: Callable[[TextDocument], Iterable[Any]]) -> None:
        self.publisher = DiagnosticPublisher(analyzer)
        self._documents: dict[str, TextDocument] = {}

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        params = message.get("params", {})
        request_id = message.get("id")
        try:
            if method == "initialize":
                result = {"capabilities": {"textDocumentSync": 1, "diagnosticProvider": {"interFileDependencies": False, "workspaceDiagnostics": False}}}
                return self._response(request_id, result)
            if method == "shutdown":
                return self._response(request_id, None)
            if method == "textDocument/didOpen":
                item = params["textDocument"]
                document = TextDocument(item["uri"], item["text"], item.get("version", 0), item.get("languageId", "java"))
                self._documents[document.uri] = document
                return self._notification("textDocument/publishDiagnostics", self.publisher.analyze(document).to_dict())
            if method == "textDocument/didChange":
                item = params["textDocument"]
                changes = params.get("contentChanges", [])
                if not changes:
                    raise LspProtocolError("didChange requires contentChanges")
                document = TextDocument(item["uri"], changes[-1]["text"], item.get("version", 0), self._documents.get(item["uri"], TextDocument(item["uri"], "")).language_id)
                self._documents[document.uri] = document
                return self._notification("textDocument/publishDiagnostics", self.publisher.analyze(document).to_dict())
            if method == "textDocument/didClose":
                uri = params["textDocument"]["uri"]
                document = self._documents.pop(uri, None)
                version = document.version if document else 0
                return self._notification("textDocument/publishDiagnostics", self.publisher.clear(uri, version=version).to_dict())
            if method == "exit":
                return None
            raise LspProtocolError(f"method not supported: {method}")
        except (KeyError, TypeError, ValueError) as exc:
            if request_id is None:
                raise LspProtocolError(str(exc)) from exc
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": str(exc)}}

    def handle_json(self, text: str) -> str:
        try:
            message = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LspProtocolError(f"invalid JSON: {exc.msg}") from exc
        result = self.handle(message)
        return "" if result is None else json.dumps(result, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _response(request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _notification(method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "method": method, "params": dict(params)}
