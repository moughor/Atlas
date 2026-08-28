"""Jailer CSV ingest for the Atlas Sygma Database Graph.

Parses Jailer-exported CSV files (semicolon-delimited) and produces
:class:`DatabaseGraphNode` and :class:`DatabaseGraphEdge` instances with
full evidence provenance.

Jailer files expected under a repository-relative directory such as
``sygma-it/sygma-it-services/src/test/jailer/Sygma/``:

- ``table.csv``       — table/view/materialized-view inventory
- ``column.csv``      — column definitions per table
- ``association.csv``  — foreign-key associations with join conditions
- ``version.csv``      — Jailer data-model version string
- ``modelname.csv``    — model name and timestamp identifier

All produced nodes and edges carry an :class:`EvidenceRecord` with
``observed_version`` from ``version.csv`` and the originating file path.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from moughorai.database_graph.models import (
    DatabaseGraphCoverage,
    DatabaseGraphEdge,
    DatabaseGraphNode,
    EdgeKind,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    NodeKind,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JAILER_EVIDENCE_KIND = "jailer_csv"

# Relative path from the repository root to the Jailer directory.
_DEFAULT_JAILER_RELPATH = (
    "sygma-it/sygma-it-services/src/test/jailer/Sygma"
)

# Name-prefix classification patterns.
_MV_PREFIX = re.compile(r"^MV_", re.IGNORECASE)
_VW_PREFIX = re.compile(r"^(V_|VW_)", re.IGNORECASE)
_VW_INFIX = re.compile(r"_VW_", re.IGNORECASE)
_TVW_PREFIX = re.compile(r"^TVW_", re.IGNORECASE)
_BCK_PREFIX = re.compile(r"^BCK", re.IGNORECASE)
_BACKUP_TOKEN = re.compile(r"BACK_UP", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class JailerIngestResult:
    """Outcome of a Jailer CSV ingest run.

    Attributes:
        nodes: All produced nodes (tables, views, materialized views, columns).
        edges: All produced edges (HAS_COLUMN, FOREIGN_KEY_TO, PRIMARY_KEY_OF).
        source_version: Version string from ``version.csv``.
        model_timestamp: Timestamp identifier from ``modelname.csv``.
        coverage: Resolution coverage statistics for the ingested facts.
        table_count: Number of table-kind nodes produced.
        view_count: Number of view-kind nodes produced.
        materialized_view_count: Number of materialized-view-kind nodes produced.
        column_count: Number of column nodes produced.
        primary_key_count: Number of primary-key nodes produced.
        foreign_key_count: Number of foreign-key edges produced.
        historical_count: Number of nodes flagged as historical (BCK/BACK_UP).
        warnings: Non-fatal parse warnings.
    """

    nodes: tuple[DatabaseGraphNode, ...]
    edges: tuple[DatabaseGraphEdge, ...]
    source_version: str
    model_timestamp: str
    coverage: DatabaseGraphCoverage
    table_count: int = 0
    view_count: int = 0
    materialized_view_count: int = 0
    column_count: int = 0
    primary_key_count: int = 0
    foreign_key_count: int = 0
    historical_count: int = 0
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _stable_id(*parts: str) -> str:
    """Produce a deterministic SHA-256-based identifier from ordered parts."""
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _strip_quotes(value: str) -> str:
    """Remove surrounding double-quotes from a Jailer field value."""
    s = value.strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


def _clean_line(raw: str) -> str:
    """Strip CR/LF and trailing whitespace from a raw line."""
    return raw.rstrip("\r\n").rstrip()


def _split_semicolons(line: str) -> list[str]:
    """Split a semicolon-delimited line and strip each field."""
    return [f.strip() for f in line.split(";")]


def _classify_table_name(name: str) -> tuple[NodeKind, bool]:
    """Classify a Jailer table name into a NodeKind and historical flag.

    Returns:
        (node_kind, is_historical) tuple.
    """
    upper = name.upper()
    is_historical = bool(_BCK_PREFIX.match(upper)) or bool(_BACKUP_TOKEN.search(upper))

    if _MV_PREFIX.match(upper):
        return NodeKind.MATERIALIZED_VIEW, is_historical
    if _VW_PREFIX.match(upper) or _VW_INFIX.search(upper) or _TVW_PREFIX.match(upper):
        return NodeKind.VIEW, is_historical
    return NodeKind.TABLE, is_historical


def _parse_column_type(raw: str) -> tuple[str, str, bool]:
    """Parse a single column definition like ``ID NUMBER(38)`` or ``NAME VARCHAR2(100) null``.

    Returns:
        (column_name, data_type, nullable) tuple.
    """
    parts = raw.strip().split()
    if not parts:
        return ("", "", True)

    col_name = _strip_quotes(parts[0])
    nullable = False
    type_parts: list[str] = []

    for p in parts[1:]:
        if p.lower() == "null":
            nullable = True
        else:
            type_parts.append(p)

    data_type = " ".join(type_parts) if type_parts else ""
    return (col_name, data_type, nullable)


def _make_evidence(
    *,
    file_path: str,
    line_number: int,
    observed_version: str,
) -> EvidenceRecord:
    """Build a verified EvidenceRecord for a single Jailer CSV line."""
    source = EvidenceSource(
        kind=_JAILER_EVIDENCE_KIND,
        path=file_path,
        start_line=line_number,
        end_line=line_number,
        observed_version=observed_version,
    )
    return EvidenceRecord.verified(
        confidence=1.0,
        sources=(source,),
    )


def _make_evidence_multi(
    *,
    file_paths: list[tuple[str, int]],
    observed_version: str,
) -> EvidenceRecord:
    """Build a verified EvidenceRecord from multiple source lines."""
    sources = tuple(
        EvidenceSource(
            kind=_JAILER_EVIDENCE_KIND,
            path=fp,
            start_line=ln,
            end_line=ln,
            observed_version=observed_version,
        )
        for fp, ln in file_paths
    )
    return EvidenceRecord.verified(
        confidence=1.0,
        sources=sources,
    )


# ---------------------------------------------------------------------------
# File readers
# ---------------------------------------------------------------------------

def _read_version(jailer_dir: Path) -> str:
    """Read ``version.csv`` and return the version string."""
    path = jailer_dir / "version.csv"
    if not path.exists():
        return "unknown"
    text = path.read_text(encoding="utf-8").strip()
    # version.csv contains just the version string, e.g. "9.3.3"
    return text if text else "unknown"


def _read_model_timestamp(jailer_dir: Path) -> str:
    """Read ``modelname.csv`` and return the model timestamp identifier."""
    path = jailer_dir / "modelname.csv"
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    # Format: header "# name; last modification" then "Sygma; 1627897393968"
    for raw_line in lines:
        line = _clean_line(raw_line)
        if line.startswith("#") or not line:
            continue
        fields = _split_semicolons(line)
        if len(fields) >= 2:
            return fields[1].strip()
    return ""


def _read_csv_lines(path: Path) -> list[tuple[int, str]]:
    """Read a semicolon-delimited CSV, returning (1-based line number, cleaned line).

    Skips the header line (starting with ``#``) and blank lines.
    """
    if not path.exists():
        return []
    results: list[tuple[int, str]] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno_0, raw in enumerate(fh):
            lineno = lineno_0 + 1  # 1-based
            line = _clean_line(raw)
            if not line or line.startswith("#"):
                continue
            results.append((lineno, line))
    return results


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_tables(
    jailer_dir: Path,
    repo_relpath: str,
    observed_version: str,
) -> tuple[
    dict[str, DatabaseGraphNode],
    dict[str, list[str]],
    list[DatabaseGraphNode],
    list[DatabaseGraphEdge],
    list[str],
    int,
]:
    """Parse ``table.csv``.

    Returns:
        (table_nodes_by_name, pk_columns_by_table, pk_nodes, pk_edges, warnings, historical_count)

    ``table_nodes_by_name`` maps the canonical (upper) table name to its node.
    ``pk_columns_by_table`` maps the canonical table name to its PK column definitions
    (raw strings like ``ID NUMBER(38)``).
    """
    file_relpath = f"{repo_relpath}/table.csv"
    table_csv = jailer_dir / "table.csv"
    lines = _read_csv_lines(table_csv)

    table_nodes: dict[str, DatabaseGraphNode] = {}
    pk_columns_by_table: dict[str, list[str]] = {}
    pk_nodes: list[DatabaseGraphNode] = []
    pk_edges: list[DatabaseGraphEdge] = []
    warnings: list[str] = []
    historical_count = 0

    for lineno, line in lines:
        fields = _split_semicolons(line)
        if not fields or not fields[0]:
            warnings.append(f"table.csv:{lineno}: empty table name, skipped")
            continue

        raw_name = _strip_quotes(fields[0])
        if not raw_name:
            warnings.append(f"table.csv:{lineno}: empty table name after quote removal, skipped")
            continue

        canonical_name = raw_name.upper()
        kind, is_historical = _classify_table_name(canonical_name)
        if is_historical:
            historical_count += 1

        # Upsert flag is field[1] (N/Y) — informational, stored as property
        upsert = fields[1].strip() if len(fields) > 1 else ""

        # Primary key columns are fields[2..] up to the first empty field,
        # then the Author field follows after the empty field.
        # Format: Name; Upsert; PK_col_1 TYPE; PK_col_2 TYPE; ...; ; Author; ;
        pk_cols: list[str] = []
        author = ""
        past_pk_section = False
        for i in range(2, len(fields)):
            f = fields[i].strip()
            if not f:
                past_pk_section = True
                continue
            if past_pk_section:
                # First non-empty field after the blank gap is the Author
                if not author:
                    author = f
                continue
            pk_cols.append(f)

        # Build the table/view/materialized_view node
        node_id = _stable_id("jailer", "table", canonical_name)
        properties: list[tuple[str, Any]] = [
            ("source_name", raw_name),
            ("upsert", upsert),
        ]
        if author:
            properties.append(("author", author))
        if is_historical:
            properties.append(("historical", True))
        if pk_cols:
            properties.append(("primary_key_definitions", pk_cols))

        evidence = _make_evidence(
            file_path=file_relpath,
            line_number=lineno,
            observed_version=observed_version,
        )

        node = DatabaseGraphNode(
            id=node_id,
            kind=kind.value,
            qualified_name=canonical_name,
            schema=None,
            properties=tuple(properties),
            evidence=evidence,
        )
        table_nodes[canonical_name] = node
        pk_columns_by_table[canonical_name] = pk_cols

        # Build primary-key node and edge if PK columns exist
        if pk_cols:
            pk_col_names = [_parse_column_type(c)[0] for c in pk_cols]
            pk_qualified = f"{canonical_name}.PK"
            pk_id = _stable_id("jailer", "pk", canonical_name)
            pk_node = DatabaseGraphNode(
                id=pk_id,
                kind=NodeKind.PRIMARY_KEY.value,
                qualified_name=pk_qualified,
                schema=None,
                properties=(
                    ("columns", pk_col_names),
                    ("column_definitions", pk_cols),
                ),
                evidence=evidence,
            )
            pk_nodes.append(pk_node)

            pk_edge = DatabaseGraphEdge(
                id=_stable_id("jailer", "pk_edge", canonical_name),
                kind=EdgeKind.PRIMARY_KEY_OF.value,
                from_node=pk_id,
                to_node=node_id,
                evidence=evidence,
            )
            pk_edges.append(pk_edge)

    return table_nodes, pk_columns_by_table, pk_nodes, pk_edges, warnings, historical_count


def _parse_columns(
    jailer_dir: Path,
    repo_relpath: str,
    observed_version: str,
    table_nodes: dict[str, DatabaseGraphNode],
) -> tuple[list[DatabaseGraphNode], list[DatabaseGraphEdge], list[str], int, int]:
    """Parse ``column.csv``.

    Returns:
        (column_nodes, has_column_edges, warnings, columns_resolved, columns_unresolved)
    """
    file_relpath = f"{repo_relpath}/column.csv"
    column_csv = jailer_dir / "column.csv"
    lines = _read_csv_lines(column_csv)

    column_nodes: list[DatabaseGraphNode] = []
    edges: list[DatabaseGraphEdge] = []
    warnings: list[str] = []
    columns_resolved = 0
    columns_unresolved = 0

    for lineno, line in lines:
        fields = _split_semicolons(line)
        if not fields or not fields[0]:
            warnings.append(f"column.csv:{lineno}: empty table name, skipped")
            continue

        raw_table = _strip_quotes(fields[0])
        if not raw_table:
            warnings.append(f"column.csv:{lineno}: empty table name after quote removal, skipped")
            continue

        canonical_table = raw_table.upper()
        table_node = table_nodes.get(canonical_table)
        table_node_id = table_node.id if table_node else _stable_id("jailer", "table", canonical_table)

        evidence = _make_evidence(
            file_path=file_relpath,
            line_number=lineno,
            observed_version=observed_version,
        )

        # Columns are fields[1..] — each is a column definition.
        # Empty fields at the end are just trailing semicolons.
        for field_idx in range(1, len(fields)):
            col_def_raw = fields[field_idx].strip()
            if not col_def_raw:
                continue  # trailing empty field

            col_name, data_type, nullable = _parse_column_type(col_def_raw)
            if not col_name:
                continue

            canonical_col = col_name.upper()
            qualified = f"{canonical_table}.{canonical_col}"
            col_id = _stable_id("jailer", "column", canonical_table, canonical_col)

            # Determine historical flag from parent table
            is_historical = False
            if table_node:
                is_historical = table_node.get_property("historical") is True

            properties: list[tuple[str, Any]] = [
                ("source_name", col_name),
                ("data_type", data_type),
                ("nullable", nullable),
                ("definition", col_def_raw),
            ]
            if is_historical:
                properties.append(("historical", True))

            col_node = DatabaseGraphNode(
                id=col_id,
                kind=NodeKind.COLUMN.value,
                qualified_name=qualified,
                schema=None,
                properties=tuple(properties),
                evidence=evidence,
            )
            column_nodes.append(col_node)

            if table_node:
                columns_resolved += 1
            else:
                columns_unresolved += 1

            # HAS_COLUMN edge from table to column
            edge_id = _stable_id("jailer", "has_column", canonical_table, canonical_col)
            edge = DatabaseGraphEdge(
                id=edge_id,
                kind=EdgeKind.HAS_COLUMN.value,
                from_node=table_node_id,
                to_node=col_id,
                evidence=evidence,
            )
            edges.append(edge)

    return column_nodes, edges, warnings, columns_resolved, columns_unresolved


def _parse_associations(
    jailer_dir: Path,
    repo_relpath: str,
    observed_version: str,
    table_nodes: dict[str, DatabaseGraphNode],
) -> tuple[list[DatabaseGraphEdge], list[DatabaseGraphNode], list[str]]:
    """Parse ``association.csv``.

    Returns:
        (fk_edges, fk_nodes, warnings)
    """
    file_relpath = f"{repo_relpath}/association.csv"
    assoc_csv = jailer_dir / "association.csv"
    lines = _read_csv_lines(assoc_csv)

    fk_edges: list[DatabaseGraphEdge] = []
    fk_nodes: list[DatabaseGraphNode] = []
    warnings: list[str] = []

    for lineno, line in lines:
        fields = _split_semicolons(line)
        # Expected: Table A; Table B; First-insert; Cardinality; Join-condition; Name; Author; ...
        if len(fields) < 6:
            warnings.append(
                f"association.csv:{lineno}: fewer than 6 fields ({len(fields)}), skipped"
            )
            continue

        raw_table_a = _strip_quotes(fields[0])
        raw_table_b = _strip_quotes(fields[1])
        first_insert = fields[2].strip()
        cardinality = fields[3].strip()
        join_condition = fields[4].strip()
        fk_name = fields[5].strip()
        author = fields[6].strip() if len(fields) > 6 else ""

        if not raw_table_a or not raw_table_b:
            warnings.append(f"association.csv:{lineno}: empty table name, skipped")
            continue

        canonical_a = raw_table_a.upper()
        canonical_b = raw_table_b.upper()

        # Resolve node ids — use canonical hash if table not found in table.csv
        node_a = table_nodes.get(canonical_a)
        node_b = table_nodes.get(canonical_b)
        node_id_a = node_a.id if node_a else _stable_id("jailer", "table", canonical_a)
        node_id_b = node_b.id if node_b else _stable_id("jailer", "table", canonical_b)

        evidence = _make_evidence(
            file_path=file_relpath,
            line_number=lineno,
            observed_version=observed_version,
        )

        # Build a foreign-key node representing this FK constraint
        fk_qualified = fk_name if fk_name else f"{canonical_a}_TO_{canonical_b}"
        fk_id = _stable_id("jailer", "fk", canonical_a, canonical_b, join_condition, fk_name)

        properties: list[tuple[str, Any]] = [
            ("join_condition", join_condition),
            ("fk_name", fk_name),
            ("cardinality", cardinality),
            ("first_insert", first_insert),
            ("source_table", canonical_a),
            ("target_table", canonical_b),
        ]
        if author:
            properties.append(("author", author))

        fk_node = DatabaseGraphNode(
            id=fk_id,
            kind=NodeKind.FOREIGN_KEY.value,
            qualified_name=fk_qualified,
            schema=None,
            properties=tuple(properties),
            evidence=evidence,
        )
        fk_nodes.append(fk_node)

        # FOREIGN_KEY_TO edge: from table A to table B
        # Parse source/target columns from join_condition (e.g. "A.GROUP_PF_ID=B.ID")
        source_col = ""
        target_col = ""
        if "=" in join_condition:
            lhs, rhs = join_condition.split("=", 1)
            source_col = lhs.split(".", 1)[1] if "." in lhs else lhs
            target_col = rhs.split(".", 1)[1] if "." in rhs else rhs
            source_col = source_col.strip()
            target_col = target_col.strip()

        fk_edge_id = _stable_id(
            "jailer", "fk_edge", canonical_a, canonical_b, join_condition, fk_name
        )
        edge = DatabaseGraphEdge(
            id=fk_edge_id,
            kind=EdgeKind.FOREIGN_KEY_TO.value,
            from_node=node_id_a,
            to_node=node_id_b,
            properties=tuple([
                ("join_condition", join_condition),
                ("fk_name", fk_name),
                ("cardinality", cardinality),
                ("first_insert", first_insert),
                ("fk_node_id", fk_id),
                ("source_table", canonical_a),
                ("source_column", source_col),
                ("target_table", canonical_b),
                ("target_column", target_col),
            ]),
            evidence=evidence,
        )
        fk_edges.append(edge)

    return fk_edges, fk_nodes, warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_jailer(
    repo_root: str | Path,
    *,
    jailer_relpath: str = _DEFAULT_JAILER_RELPATH,
) -> JailerIngestResult:
    """Parse the Jailer CSV directory and produce graph nodes and edges.

    Args:
        repo_root: Absolute path to the Sygma repository root.
        jailer_relpath: Repository-relative path to the Jailer directory.
            Defaults to ``sygma-it/sygma-it-services/src/test/jailer/Sygma``.

    Returns:
        A :class:`JailerIngestResult` containing all nodes, edges, version,
        timestamp, coverage counts, and any parse warnings.

    Raises:
        FileNotFoundError: If the Jailer directory does not exist.
    """
    repo_root = Path(repo_root)
    jailer_dir = repo_root / jailer_relpath

    if not jailer_dir.is_dir():
        raise FileNotFoundError(
            f"Jailer directory not found: {jailer_dir}"
        )

    # Read metadata files
    observed_version = _read_version(jailer_dir)
    model_timestamp = _read_model_timestamp(jailer_dir)

    all_warnings: list[str] = []

    # Phase 1: tables
    (
        table_nodes,
        pk_columns_by_table,
        pk_nodes,
        pk_edges,
        table_warnings,
        historical_count,
    ) = _parse_tables(jailer_dir, jailer_relpath, observed_version)
    all_warnings.extend(table_warnings)

    # Phase 2: columns
    (
        column_nodes,
        has_column_edges,
        column_warnings,
        columns_resolved,
        columns_unresolved,
    ) = _parse_columns(jailer_dir, jailer_relpath, observed_version, table_nodes)
    all_warnings.extend(column_warnings)

    # Phase 3: associations (foreign keys)
    (
        fk_edges,
        fk_nodes,
        assoc_warnings,
    ) = _parse_associations(jailer_dir, jailer_relpath, observed_version, table_nodes)
    all_warnings.extend(assoc_warnings)

    # Classify table-kind counts
    table_count = 0
    view_count = 0
    mv_count = 0
    for node in table_nodes.values():
        if node.kind == NodeKind.TABLE.value:
            table_count += 1
        elif node.kind == NodeKind.VIEW.value:
            view_count += 1
        elif node.kind == NodeKind.MATERIALIZED_VIEW.value:
            mv_count += 1

    # Assemble all nodes and edges
    all_nodes: list[DatabaseGraphNode] = []
    all_nodes.extend(table_nodes.values())
    all_nodes.extend(pk_nodes)
    all_nodes.extend(column_nodes)
    all_nodes.extend(fk_nodes)

    all_edges: list[DatabaseGraphEdge] = []
    all_edges.extend(pk_edges)
    all_edges.extend(has_column_edges)
    all_edges.extend(fk_edges)

    # Build coverage
    # All tables ingested are "resolved" by definition (Jailer is the source of truth);
    # unresolved tables would come from references in associations to tables not in table.csv.
    referenced_tables = set()
    for edge in fk_edges:
        for prop_key, prop_val in edge.properties:
            if prop_key == "source_table":
                referenced_tables.add(prop_val)
            elif prop_key == "target_table":  # noqa: SIM114
                referenced_tables.add(prop_val)

    tables_in_csv = set(table_nodes.keys())
    tables_unresolved_set = referenced_tables - tables_in_csv

    coverage = DatabaseGraphCoverage(
        tables_resolved=table_count,
        tables_unresolved=len(tables_unresolved_set),
        views_resolved=view_count,
        views_unresolved=0,
        columns_resolved=columns_resolved,
        columns_unresolved=columns_unresolved,
        constraints_resolved=len(pk_nodes) + len(fk_nodes),
        constraints_unresolved=0,
        total_nodes=len(all_nodes),
        total_edges=len(all_edges),
    )

    return JailerIngestResult(
        nodes=tuple(all_nodes),
        edges=tuple(all_edges),
        source_version=observed_version,
        model_timestamp=model_timestamp,
        coverage=coverage,
        table_count=table_count,
        view_count=view_count,
        materialized_view_count=mv_count,
        column_count=len(column_nodes),
        primary_key_count=len(pk_nodes),
        foreign_key_count=len(fk_edges),
        historical_count=historical_count,
        warnings=tuple(all_warnings),
    )
