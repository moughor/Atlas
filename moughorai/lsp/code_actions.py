from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from .models import Diagnostic, TextDocument


@dataclass(frozen=True, slots=True)
class CodeAction:
    title: str
    kind: str
    command: str
    diagnostics: tuple[Diagnostic, ...] = ()
    arguments: tuple[Any, ...] = ()
    data: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("code action title must not be empty")
        if not self.kind.strip():
            raise ValueError("code action kind must not be empty")
        if not self.command.strip():
            raise ValueError("code action command must not be empty")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "title": self.title,
            "kind": self.kind,
            "command": {
                "title": self.title,
                "command": self.command,
                "arguments": list(self.arguments),
            },
        }
        if self.diagnostics:
            result["diagnostics"] = [item.to_dict() for item in self.diagnostics]
        if self.data:
            result["data"] = dict(self.data)
        return result


class CodeActionProvider(Protocol):
    def actions(self, document: TextDocument, diagnostics: tuple[Diagnostic, ...]) -> Iterable[CodeAction]: ...


class DefaultCodeActionProvider:
    """Non-mutating actions shared by all Atlas LSP analyzers."""

    def actions(self, document: TextDocument, diagnostics: tuple[Diagnostic, ...]) -> tuple[CodeAction, ...]:
        actions: list[CodeAction] = []
        for diagnostic in diagnostics:
            code = diagnostic.code or "finding"
            identity = (("code", code), ("uri", document.uri))
            actions.extend((
                CodeAction(
                    f"Explain {code}",
                    "quickfix",
                    "atlas.explainFinding",
                    (diagnostic,),
                    ({"uri": document.uri, "code": code},),
                    identity,
                ),
                CodeAction(
                    f"Suppress {code}",
                    "quickfix",
                    "atlas.suppressFinding",
                    (diagnostic,),
                    ({"uri": document.uri, "code": code},),
                    identity,
                ),
            ))
        actions.append(CodeAction(
            "Rescan document",
            "source",
            "atlas.rescanDocument",
            arguments=({"uri": document.uri},),
            data=(("uri", document.uri),),
        ))
        return tuple(sorted(actions, key=lambda item: (item.kind, item.title, item.command)))
