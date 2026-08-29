"""Oracle synonym SQL ingestion for the Atlas Database Graph.

Scans a repository for synonym definition scripts. Detects both static
CREATE SYNONYM statements and dynamic PL/SQL synonym generators.

Static synonyms produce verified graph nodes. Dynamic generators produce
nodes with status='inferred' and confidence=0.5 because the actual synonym
set depends on the runtime Oracle catalog.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import (
    DatabaseGraphEdge,
    DatabaseGraphNode,
    EdgeKind,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    NodeKind,
)

__all__ = ["SynonymIngestResult", "ingest_synonyms"]

log = logging.getLogger(__name__)

_CREATE_SYNONYM_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:PUBLIC\s+)?SYNONYM\s+"
    r'(?:(?P<syn_schema>"[^"]+"|[A-Za-z_]\w*)\s*\.\s*)?'
    r'(?P<syn_name>"[^"]+"|[A-Za-z_]\w*)\s+'
    r"FOR\s+"
    r'(?:(?P<tgt_schema>"[^"]+"|[A-Za-z_]\w*)\s*\.\s*)?'
    r'(?P<tgt_name>"[^"]+"|[A-Za-z_]\w*)',
    re.IGNORECASE,
)

_DYNAMIC_GENERATOR_RE = re.compile(
    r"(?:for\s+\w+\s+in\s*\(.*?all_objects.*?\))"
    r"|(?:execute\s+immediate\s+.*?synonym)",
    re.IGNORECASE | re.DOTALL,
)

_SCAN_DIRS = (
    "sygma-db/src/main/resources/SYNONYMS",
    "sygma-db/src/main/resources/db/migration/synonyms",
)


def _unquote(ident: str) -> str:
    return ident.strip('"').upper()


def _stable_id(canonical_name: str) -> str:
    return hashlib.sha256(canonical_name.encode("utf-8")).hexdigest()


def _make_evidence(rel_path, start_line, end_line, *, status=EvidenceStatus.VERIFIED.value, confidence=1.0):
    return EvidenceRecord(
        status=status, confidence=confidence,
        sources=(EvidenceSource(kind="synonym_sql", path=rel_path, start_line=start_line, end_line=end_line),),
    )


@dataclass
class SynonymIngestResult:
    nodes: list[DatabaseGraphNode] = field(default_factory=list)
    edges: list[DatabaseGraphEdge] = field(default_factory=list)
    static_count: int = 0
    dynamic_generator_count: int = 0
    scanned_paths: list[str] = field(default_factory=list)


def ingest_synonyms(repo_root: Path) -> SynonymIngestResult:
    repo_root = Path(repo_root).resolve()
    result = SynonymIngestResult()

    for scan_dir in _SCAN_DIRS:
        abs_dir = repo_root / scan_dir
        if not abs_dir.is_dir():
            continue
        result.scanned_paths.append(scan_dir)

        for sql_file in sorted(abs_dir.rglob("*.sql")):
            if "BACK_UP" in str(sql_file) or "target" in sql_file.parts:
                continue
            rel_path = str(sql_file.relative_to(repo_root)).replace("\\", "/")
            try:
                content = sql_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for m in _CREATE_SYNONYM_RE.finditer(content):
                syn_name = _unquote(m.group("syn_name"))
                tgt_schema = _unquote(m.group("tgt_schema")) if m.group("tgt_schema") else None
                tgt_name = _unquote(m.group("tgt_name"))
                line_no = content[:m.start()].count("\n") + 1
                node_id = _stable_id(f"synonym:{syn_name}")
                node = DatabaseGraphNode(
                    id=node_id, kind=NodeKind.SYNONYM.value,
                    qualified_name=syn_name, schema=None,
                    properties=(("target_schema", tgt_schema or ""), ("target_name", tgt_name), ("source_file", rel_path)),
                    evidence=_make_evidence(rel_path, line_no, line_no),
                )
                result.nodes.append(node)
                target_qname = f"{tgt_schema}.{tgt_name}" if tgt_schema else tgt_name
                edge = DatabaseGraphEdge(
                    id=_stable_id(f"alias:{syn_name}->{target_qname}"),
                    kind=EdgeKind.ALIAS_OF.value,
                    from_node=node_id, to_node=_stable_id(f"table:{tgt_name}"),
                    properties=(("synonym_name", syn_name), ("target_name", tgt_name), ("target_schema", tgt_schema or "")),
                    evidence=_make_evidence(rel_path, line_no, line_no),
                )
                result.edges.append(edge)
                result.static_count += 1

            if _DYNAMIC_GENERATOR_RE.search(content):
                dyn_id = _stable_id(f"dynamic-synonym-generator:{rel_path}")
                dyn_node = DatabaseGraphNode(
                    id=dyn_id, kind=NodeKind.SYNONYM.value,
                    qualified_name="DYNAMIC:ALL_SYGMA_OBJECTS", schema=None,
                    properties=(("generator_type", "dynamic_all_objects"), ("source_file", rel_path), ("runtime_dependent", "true")),
                    evidence=_make_evidence(rel_path, 1, 1, status=EvidenceStatus.INFERRED.value, confidence=0.5),
                )
                result.nodes.append(dyn_node)
                result.dynamic_generator_count += 1

    return result
