from __future__ import annotations

import json
import os
from pathlib import Path

from moughorai.global_symbols.database import GlobalSymbolDatabase
from moughorai.global_symbols.models import (
    GlobalSymbol,
    GlobalSymbolKind,
    SymbolId,
)


class GlobalSymbolStore:
    SCHEMA_VERSION = 1

    def save(self, db: GlobalSymbolDatabase, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = []
        for symbol in db.symbols:
            item = {
                "id": str(symbol.id),
                "kind": symbol.kind.value,
                "name": symbol.name,
                "qualified_name": symbol.qualified_name,
                "owner_id": str(symbol.owner_id) if symbol.owner_id else None,
                "source": str(symbol.source) if symbol.source else None,
                "metadata": dict(symbol.metadata),
                "project_id": symbol.project_id,
            }
            if symbol.scope_id is not None:
                item["scope_id"] = symbol.scope_id
            encoded.append(item)
        payload = {"schema_version": self.SCHEMA_VERSION, "symbols": encoded}
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)

    def load(self, path: Path) -> GlobalSymbolDatabase:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("unsupported global symbol schema")
        return GlobalSymbolDatabase(
            GlobalSymbol(
                SymbolId(item["id"]),
                GlobalSymbolKind(item["kind"]),
                item["name"],
                item["qualified_name"],
                SymbolId(item["owner_id"]) if item["owner_id"] else None,
                Path(item["source"]) if item["source"] else None,
                tuple(sorted(item.get("metadata", {}).items())),
                item.get("project_id"),
                item.get("scope_id"),
            )
            for item in payload["symbols"]
        )
