from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from moughorai.global_symbols import GlobalSymbol, GlobalSymbolKind
from moughorai.global_symbols.models import SymbolId
from moughorai.semantic import Diagnostic, DiagnosticSeverity, SemanticDocument
from moughorai.semantic.types import TypeTable, type_from_dict, type_to_dict
from moughorai.dependency_intelligence import DeclaredDependency
from moughorai.java_architecture import (
    ArchitectureEdge,
    ArchitectureEdgeKind,
    ArchitectureNode,
    JavaArchitectureGraph,
    UnresolvedArchitectureReference,
)


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
        "declared_dependencies": [
            item.to_dict()
            for item in value.get_artifact("declared_dependencies", ())
            if isinstance(item, DeclaredDependency)
        ],
        "java_architecture_graph": _encode_java_architecture(
            value.get_artifact("java_architecture_graph")
        ),
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
    document = document.with_artifact(
        "declared_dependencies",
        tuple(
            DeclaredDependency(
                str(item["ecosystem"]), str(item["name"]),
                None if item.get("version") is None else str(item["version"]),
                str(item["scope"]), Path(str(item["source"])),
                bool(item.get("optional", False)),
            )
            for item in value.get("declared_dependencies", ())
        ),
    )
    raw_architecture = value.get("java_architecture_graph")
    if isinstance(raw_architecture, Mapping):
        document = document.with_artifact(
            "java_architecture_graph",
            _decode_java_architecture(raw_architecture),
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
        "project_id": symbol.project_id,
    }


def _decode_symbol(value: Mapping[str, Any]) -> GlobalSymbol:
    symbol = GlobalSymbol.create(
        GlobalSymbolKind(str(value["kind"])),
        str(value["name"]),
        str(value["qualified_name"]),
        source=Path(value["source"]) if value.get("source") is not None else None,
        metadata={str(key): str(item) for key, item in value.get("metadata", {}).items()},
        project_id=str(value["project_id"]) if value.get("project_id") is not None else None,
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
        symbol.project_id,
    )


def _encode_java_architecture(value: object) -> dict[str, object] | None:
    if not isinstance(value, JavaArchitectureGraph):
        return None
    return {
        "nodes": [
            {
                "qualified_name": item.qualified_name,
                "simple_name": item.simple_name,
                "type_kind": item.type_kind,
                "package_name": item.package_name,
                "source": str(item.source) if item.source is not None else None,
            }
            for item in sorted(value.nodes, key=lambda item: item.qualified_name)
        ],
        "edges": [
            {
                "source": item.source,
                "target": item.target,
                "kind": item.kind.value,
                "role": item.role,
                "requested_name": item.requested_name,
            }
            for item in sorted(
                value.edges,
                key=lambda item: (
                    item.source, item.target, item.kind.value, item.role,
                ),
            )
        ],
        "unresolved": [
            {
                "owner": item.owner,
                "role": item.role,
                "requested_name": item.requested_name,
                "status": item.status,
                "candidates": list(item.candidates),
            }
            for item in sorted(
                value.unresolved,
                key=lambda item: (
                    item.owner, item.role, item.requested_name,
                ),
            )
        ],
    }


def _decode_java_architecture(
    value: Mapping[str, object],
) -> JavaArchitectureGraph:
    return JavaArchitectureGraph(
        (
            ArchitectureNode(
                str(item["qualified_name"]),
                str(item["simple_name"]),
                str(item["type_kind"]),
                str(item["package_name"]),
                (
                    Path(str(item["source"]))
                    if item.get("source") is not None
                    else None
                ),
            )
            for item in value.get("nodes", ())
            if isinstance(item, Mapping)
        ),
        (
            ArchitectureEdge(
                str(item["source"]),
                str(item["target"]),
                ArchitectureEdgeKind(str(item["kind"])),
                str(item["role"]),
                str(item["requested_name"]),
            )
            for item in value.get("edges", ())
            if isinstance(item, Mapping)
        ),
        (
            UnresolvedArchitectureReference(
                str(item["owner"]),
                str(item["role"]),
                str(item["requested_name"]),
                str(item["status"]),
                tuple(map(str, item.get("candidates", ()))),
            )
            for item in value.get("unresolved", ())
            if isinstance(item, Mapping)
        ),
    )
