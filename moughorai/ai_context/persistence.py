from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from moughorai.global_symbols import GlobalSymbol, GlobalSymbolKind
from moughorai.global_symbols.models import SymbolId
from moughorai.semantic import Diagnostic, DiagnosticSeverity, SemanticDocument
from moughorai.semantic.types import TypeTable, type_from_dict, type_to_dict


_DOCUMENT_MARKER = "atlas.semantic-document.v1"


def encode_analysis_result(value: Any) -> Any:
    """Encode Atlas semantic results while preserving legacy analyzer values."""
    if not isinstance(value, SemanticDocument):
        return value
    return {
        "$type": _DOCUMENT_MARKER,
        "language": value.language,
        "metadata": dict(value.metadata),
        "diagnostics": [
            {
                "code": item.code,
                "message": item.message,
                "severity": item.severity.value,
                "location": str(item.location) if item.location is not None else None,
                "rule": item.rule,
                "pass_name": item.pass_name,
            }
            for item in value.diagnostics
        ],
        "global_symbols": [_encode_symbol(item) for item in value.get_artifact("global_symbols", ())],
        "types": [
            {"key": key, "type": type_to_dict(item)}
            for key, item in sorted(value.types.entries.items(), key=lambda pair: str(pair[0]))
            if isinstance(key, (str, int, float, bool)) or key is None
        ],
    }


def decode_analysis_result(value: Any) -> Any:
    """Restore semantic results and pass through pre-PR121 persisted values."""
    if not isinstance(value, Mapping) or value.get("$type") != _DOCUMENT_MARKER:
        return value
    document = SemanticDocument(
        language=str(value["language"]),
        source="",
        syntax_tree=(),
        metadata=dict(value.get("metadata", {})),
    )
    document = document.with_artifact(
        "global_symbols",
        tuple(_decode_symbol(item) for item in value.get("global_symbols", ())),
    )
    document = document.with_artifact(
        "types",
        TypeTable({
            item["key"]: type_from_dict(item["type"])
            for item in value.get("types", ())
        }),
    )
    return document.with_diagnostics(
        Diagnostic(
            code=str(item["code"]),
            message=str(item["message"]),
            severity=DiagnosticSeverity(str(item["severity"])),
            location=Path(item["location"]) if item.get("location") is not None else None,
            rule=item.get("rule"),
            pass_name=item.get("pass_name"),
        )
        for item in value.get("diagnostics", ())
    )


def _encode_symbol(symbol: GlobalSymbol) -> dict[str, Any]:
    return {
        "kind": symbol.kind.value,
        "name": symbol.name,
        "qualified_name": symbol.qualified_name,
        "owner_id": str(symbol.owner_id) if symbol.owner_id is not None else None,
        "source": str(symbol.source) if symbol.source is not None else None,
        "metadata": dict(symbol.metadata),
    }


def _decode_symbol(value: Mapping[str, Any]) -> GlobalSymbol:
    symbol = GlobalSymbol.create(
        GlobalSymbolKind(str(value["kind"])),
        str(value["name"]),
        str(value["qualified_name"]),
        source=Path(value["source"]) if value.get("source") is not None else None,
        metadata={str(key): str(item) for key, item in value.get("metadata", {}).items()},
    )
    owner = value.get("owner_id")
    if owner is None:
        return symbol
    return GlobalSymbol(
        symbol.id,
        symbol.kind,
        symbol.name,
        symbol.qualified_name,
        SymbolId(str(owner)),
        symbol.source,
        symbol.metadata,
    )
