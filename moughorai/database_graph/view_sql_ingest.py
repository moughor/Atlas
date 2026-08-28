"""View SQL ingest for the Atlas Sygma Database Graph.

Scans Flyway ``R__*.sql`` files in a Sygma repository to extract view and
materialized view definitions.  Produces :class:`DatabaseGraphNode` and
:class:`DatabaseGraphEdge` instances with full evidence provenance, ready
for the reconciler.

Scan paths (relative to *repo_root*):

- ``sygma-db/src/main/resources/db/migration/views/R__*.sql``         — regular views
- ``sygma-db/src/main/resources/db/env_specific/mviews/R__*.sql``     — materialized views
- ``csc-common/csc-common-db/src/main/resources/db_csc/migration/views/R__*.sql``  — CSC views
"""

from __future__ import annotations

import glob as _glob_mod
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .models import (
    DatabaseGraphNode,
    DatabaseGraphEdge,
    DatabaseGraphCoverage,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    NodeKind,
    EdgeKind,
)

__all__ = [
    "ViewSqlIngestResult",
    "ingest_view_sql",
]

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default scan-path globs (relative to repo root)
# ---------------------------------------------------------------------------

_DEFAULT_VIEW_RELPATHS: tuple[str, ...] = (
    "sygma-db/src/main/resources/db/migration/views/R__*.sql",
    "csc-common/csc-common-db/src/main/resources/db_csc/migration/views/R__*.sql",
)

_DEFAULT_MVIEW_RELPATHS: tuple[str, ...] = (
    "sygma-db/src/main/resources/db/env_specific/mviews/R__*.sql",
)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ViewSqlIngestResult:
    """Outcome of a view SQL ingest run.

    Attributes:
        nodes: All produced nodes (views, materialized views, columns).
        edges: All produced edges (HAS_COLUMN, READS_FROM).
        view_count: Number of regular-view nodes produced.
        materialized_view_count: Number of materialized-view nodes produced.
        column_count: Number of projected-column nodes produced.
        dependency_count: Number of READS_FROM edges (view → source table).
        warnings: Non-fatal parse warnings collected during ingest.
    """

    nodes: tuple[DatabaseGraphNode, ...]
    edges: tuple[DatabaseGraphEdge, ...]
    view_count: int
    materialized_view_count: int
    column_count: int
    dependency_count: int
    warnings: tuple[str, ...]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _stable_id(canonical_name: str) -> str:
    """Produce a deterministic SHA-256-based identifier from a canonical name."""
    return hashlib.sha256(canonical_name.encode()).hexdigest()


def _edge_id(*parts: str) -> str:
    """Produce a deterministic edge identifier from ordered parts."""
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# SQL comment stripping
# ---------------------------------------------------------------------------

# Matches block comments  /* ... */  (non-greedy, DOTALL)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
# Matches single-line comments  -- ...
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL block and line comments, preserving line structure."""
    # Replace block comments with equivalent whitespace to keep line numbers stable.
    def _block_repl(m: re.Match[str]) -> str:
        # Preserve newlines inside the comment so line-offsets stay valid.
        return "\n" * m.group(0).count("\n")

    sql = _BLOCK_COMMENT_RE.sub(_block_repl, sql)
    sql = _LINE_COMMENT_RE.sub("", sql)
    return sql


# ---------------------------------------------------------------------------
# CREATE VIEW / MATERIALIZED VIEW regex
# ---------------------------------------------------------------------------

# Captures:
#   group('mat')   — 'MATERIALIZED' if present
#   group('name')  — view name, optionally schema-qualified and/or quoted
#   group('cols')  — parenthesised column-alias list (without parens), optional
#   group('body')  — the SELECT ... body after AS
_CREATE_VIEW_RE = re.compile(
    r"""
    \bCREATE\s+
    (?:OR\s+REPLACE\s+)?
    (?:(?:FORCE|NOFORCE)\s+)?
    (?:(?:EDITIONABLE|NONEDITIONABLE)\s+)?
    (?P<mat>MATERIALIZED\s+)?
    VIEW\s+
    (?P<name>
        (?:"[^"]+"|[A-Za-z_]\w*)       # first identifier (schema or view)
        (?:                              # optional .second identifier
            \s*\.\s*
            (?:"[^"]+"|[A-Za-z_]\w*)
        )?
    )
    \s*
    (?:
        \(\s*(?P<cols>[^)]+)\s*\)        # optional column alias list in parens
    )?
    [\s\S]*?                             # skip any MV clauses (REFRESH, BUILD, etc.)
    \bAS\s+
    (?P<body>.+)
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)


# ---------------------------------------------------------------------------
# Identifier parsing helpers
# ---------------------------------------------------------------------------

def _unquote(ident: str) -> str:
    """Remove surrounding double-quotes from an Oracle quoted identifier."""
    s = ident.strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s.upper()  # Oracle identifiers are case-insensitive → normalise


def _parse_qualified_name(raw: str) -> tuple[str | None, str]:
    """Parse an optionally schema-qualified name.

    Returns (schema_or_None, object_name), both normalised.
    """
    parts = [_unquote(p) for p in raw.strip().split(".")]
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, parts[0]


# ---------------------------------------------------------------------------
# Column alias extraction
# ---------------------------------------------------------------------------

def _parse_column_list(raw: str) -> list[str]:
    """Parse a comma-separated column alias list from inside parentheses."""
    cols: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if token:
            cols.append(_unquote(token))
    return cols


def _extract_select_aliases(body: str) -> list[str]:
    """Best-effort extraction of column aliases from a SELECT clause.

    Only handles the top-level SELECT (not subqueries).  Stops at the first
    unparenthesised FROM keyword.
    """
    # Locate the SELECT keyword
    m = re.match(r"\s*SELECT\s+(?:DISTINCT\s+|ALL\s+)?", body, re.IGNORECASE)
    if not m:
        return []

    # Walk forward from the end of SELECT, tracking paren depth.
    start = m.end()
    depth = 0
    pos = start
    end = len(body)
    while pos < end:
        ch = body[pos]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            # Check for FROM keyword at top level
            rest = body[pos:]
            if re.match(r"\bFROM\b", rest, re.IGNORECASE):
                break
        pos += 1

    select_clause = body[start:pos]
    aliases: list[str] = []

    # Split on commas at depth-0
    items: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in select_clause:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    trailing = "".join(current).strip()
    if trailing:
        items.append(trailing)

    for item in items:
        # Skip '*' expressions
        if item.strip() in ("*",) or item.strip().endswith(".*"):
            continue
        alias = _alias_from_select_item(item)
        if alias:
            aliases.append(alias)

    return aliases


def _alias_from_select_item(item: str) -> str | None:
    """Extract the column alias from a single SELECT item expression.

    Handles:  ``expr AS alias``, ``expr alias`` (when alias is a simple ident),
    ``table.column``.
    """
    item = item.strip()
    if not item:
        return None

    # Explicit AS alias
    m = re.search(r'\bAS\s+(?P<alias>"[^"]+"|[A-Za-z_]\w*)\s*$', item, re.IGNORECASE)
    if m:
        return _unquote(m.group("alias"))

    # Implicit alias: last token if it looks like a plain identifier and is
    # separated by whitespace from the rest
    parts = item.rsplit(None, 1)
    if len(parts) == 2:
        candidate = parts[1].strip()
        # Must look like a plain identifier (not an operator, number, etc.)
        if re.fullmatch(r'"[^"]+"|[A-Za-z_]\w*', candidate):
            return _unquote(candidate)

    # table.column or just column — use the last segment
    m = re.fullmatch(r'(?:(?:"[^"]+"|[A-Za-z_]\w*)\s*\.\s*)*(?P<col>"[^"]+"|[A-Za-z_]\w*)', item)
    if m:
        return _unquote(m.group("col"))

    return None


# ---------------------------------------------------------------------------
# Source-table extraction (FROM / JOIN clauses)
# ---------------------------------------------------------------------------

# Matches FROM and JOIN table references.
# Stops collecting when we hit WHERE, GROUP, ORDER, HAVING, UNION, INTERSECT,
# MINUS, EXCEPT, FETCH, LIMIT, WITH, or end of string.
_FROM_JOIN_RE = re.compile(
    r"""
    (?:\bFROM\b|\bJOIN\b)
    \s+
    (?P<table>
        (?:"[^"]+"|[A-Za-z_]\w*)
        (?:\s*\.\s*(?:"[^"]+"|[A-Za-z_]\w*))*
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Keywords after which table references are no longer source tables
_STOP_KEYWORDS = re.compile(
    r"\b(?:WHERE|GROUP\s+BY|ORDER\s+BY|HAVING|UNION|INTERSECT|MINUS|EXCEPT|FETCH|LIMIT)\b",
    re.IGNORECASE,
)

# SQL keywords that should never be interpreted as table names
_SQL_KEYWORDS = frozenset({
    "SELECT", "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER",
    "FULL", "CROSS", "ON", "AND", "OR", "NOT", "IN", "EXISTS", "BETWEEN",
    "LIKE", "IS", "NULL", "AS", "CASE", "WHEN", "THEN", "ELSE", "END",
    "GROUP", "BY", "ORDER", "HAVING", "UNION", "ALL", "DISTINCT", "SET",
    "INSERT", "INTO", "UPDATE", "DELETE", "VALUES", "CREATE", "ALTER",
    "DROP", "TABLE", "VIEW", "INDEX", "MATERIALIZED", "WITH", "RECURSIVE",
    "LATERAL", "DUAL", "FETCH", "FIRST", "NEXT", "ROWS", "ONLY", "OFFSET",
    "LIMIT", "EXCEPT", "INTERSECT", "MINUS", "REPLACE", "FORCE", "NOFORCE",
    "NATURAL", "USING", "TRUE", "FALSE", "PARTITION", "OVER", "WINDOW",
    "ROW_NUMBER", "RANK", "DENSE_RANK", "COUNT", "SUM", "AVG", "MIN", "MAX",
    "COALESCE", "NVL", "DECODE", "CAST", "TRIM", "SUBSTR", "UPPER", "LOWER",
    "TO_DATE", "TO_CHAR", "TO_NUMBER", "SYSDATE", "SYSTIMESTAMP", "ROWNUM",
    "ROWID", "LEVEL", "CONNECT", "START", "PRIOR", "NOCYCLE",
})


def _extract_source_tables(body: str) -> list[tuple[str | None, str]]:
    """Extract source tables from FROM/JOIN clauses in a view body.

    Returns a de-duplicated list of (schema_or_None, table_name) tuples.
    Stops scanning at stop-keywords (WHERE, GROUP BY, etc.) at
    parenthesis depth 0, but continues scanning for additional
    FROM/JOIN inside subqueries.
    """
    seen: set[tuple[str | None, str]] = set()
    result: list[tuple[str | None, str]] = []

    for m in _FROM_JOIN_RE.finditer(body):
        raw = m.group("table")
        schema, name = _parse_qualified_name(raw)

        # Skip SQL keywords accidentally captured
        if name in _SQL_KEYWORDS:
            continue

        key = (schema, name)
        if key not in seen:
            seen.add(key)
            result.append(key)

    return result


# ---------------------------------------------------------------------------
# Single-file parser
# ---------------------------------------------------------------------------

@dataclass
class _ParsedView:
    """Intermediate parse result from a single SQL file."""

    name: str
    schema: str | None
    is_materialized: bool
    columns: list[str]
    source_tables: list[tuple[str | None, str]]
    start_line: int  # 1-based
    end_line: int    # 1-based, inclusive
    rel_path: str    # repo-relative path


def _parse_sql_file(
    file_path: Path,
    repo_root: Path,
    *,
    is_mview_dir: bool,
) -> tuple[list[_ParsedView], list[str]]:
    """Parse a single R__*.sql file and return parsed views + warnings."""
    warnings: list[str] = []
    results: list[_ParsedView] = []

    rel_path = str(file_path.relative_to(repo_root))

    try:
        raw_text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warnings.append(f"Cannot read {rel_path}: {exc}")
        return results, warnings

    total_lines = raw_text.count("\n") + (1 if raw_text and not raw_text.endswith("\n") else 0)
    if total_lines == 0:
        total_lines = 1

    # Strip comments while preserving line structure
    cleaned = _strip_sql_comments(raw_text)

    # Try to find CREATE VIEW / CREATE MATERIALIZED VIEW statements
    for m in _CREATE_VIEW_RE.finditer(cleaned):
        mat_group = m.group("mat")
        is_mat = bool(mat_group and mat_group.strip()) or is_mview_dir
        raw_name = m.group("name")
        cols_raw = m.group("cols")
        body = m.group("body")

        schema, view_name = _parse_qualified_name(raw_name)

        # Determine line numbers (1-based) from the match position
        start_line = cleaned[:m.start()].count("\n") + 1
        end_line = cleaned[:m.end()].count("\n") + 1
        # Clamp end_line to file length
        if end_line > total_lines:
            end_line = total_lines

        # Column aliases
        columns: list[str] = []
        if cols_raw:
            columns = _parse_column_list(cols_raw)
        else:
            # Best-effort: extract from SELECT clause
            columns = _extract_select_aliases(body)

        # Source tables
        source_tables = _extract_source_tables(body)

        # Determine node kind — use directory hint or SQL keyword
        kind_name = "materialized_view" if is_mat else "view"

        results.append(_ParsedView(
            name=view_name,
            schema=schema,
            is_materialized=is_mat,
            columns=columns,
            source_tables=source_tables,
            start_line=start_line,
            end_line=end_line,
            rel_path=rel_path,
        ))

    if not results:
        warnings.append(f"No CREATE VIEW statement found in {rel_path}")

    return results, warnings


# ---------------------------------------------------------------------------
# Node / edge builders
# ---------------------------------------------------------------------------

def _make_evidence(
    *,
    kind: str,
    rel_path: str,
    start_line: int,
    end_line: int,
) -> EvidenceRecord:
    """Build a verified EvidenceRecord with a single source."""
    return EvidenceRecord.verified(
        confidence=1.0,
        sources=(
            EvidenceSource(
                kind=kind,
                path=rel_path,
                start_line=start_line,
                end_line=end_line,
            ),
        ),
    )


def _build_view_node(parsed: _ParsedView) -> DatabaseGraphNode:
    """Build a DatabaseGraphNode for a view or materialized view."""
    kind = NodeKind.MATERIALIZED_VIEW.value if parsed.is_materialized else NodeKind.VIEW.value
    source_kind = "materialized_view_sql" if parsed.is_materialized else "view_sql"

    qualified_name = (
        f"{parsed.schema}.{parsed.name}" if parsed.schema else parsed.name
    )
    node_id = _stable_id(f"{kind}:{qualified_name}")

    evidence = _make_evidence(
        kind=source_kind,
        rel_path=parsed.rel_path,
        start_line=parsed.start_line,
        end_line=parsed.end_line,
    )

    return DatabaseGraphNode(
        id=node_id,
        kind=kind,
        qualified_name=qualified_name,
        schema=parsed.schema,
        properties=(
            ("read_only", True),
            ("source_file", parsed.rel_path),
        ),
        evidence=evidence,
    )


def _build_column_node(
    col_name: str,
    view_qualified_name: str,
    view_schema: str | None,
    parsed: _ParsedView,
) -> DatabaseGraphNode:
    """Build a DatabaseGraphNode for a projected column alias."""
    qualified_name = f"{view_qualified_name}.{col_name}"
    node_id = _stable_id(f"column:{qualified_name}")
    source_kind = "materialized_view_sql" if parsed.is_materialized else "view_sql"

    evidence = _make_evidence(
        kind=source_kind,
        rel_path=parsed.rel_path,
        start_line=parsed.start_line,
        end_line=parsed.end_line,
    )

    return DatabaseGraphNode(
        id=node_id,
        kind=NodeKind.COLUMN.value,
        qualified_name=qualified_name,
        schema=view_schema,
        properties=(
            ("read_only", True),
            ("source_file", parsed.rel_path),
        ),
        evidence=evidence,
    )


def _build_has_column_edge(
    view_node_id: str,
    col_node_id: str,
    parsed: _ParsedView,
) -> DatabaseGraphEdge:
    """Build a HAS_COLUMN edge from a view to a column."""
    edge_id = _edge_id("HAS_COLUMN", view_node_id, col_node_id)
    source_kind = "materialized_view_sql" if parsed.is_materialized else "view_sql"

    evidence = _make_evidence(
        kind=source_kind,
        rel_path=parsed.rel_path,
        start_line=parsed.start_line,
        end_line=parsed.end_line,
    )

    return DatabaseGraphEdge(
        id=edge_id,
        kind=EdgeKind.HAS_COLUMN.value,
        from_node=view_node_id,
        to_node=col_node_id,
        evidence=evidence,
    )


def _build_reads_from_edge(
    view_node_id: str,
    source_schema: str | None,
    source_table: str,
    parsed: _ParsedView,
) -> DatabaseGraphEdge:
    """Build a READS_FROM edge from a view to a source table."""
    source_qualified = (
        f"{source_schema}.{source_table}" if source_schema else source_table
    )
    # The target table node might not exist yet — produce a stable id for it
    # so the reconciler can match or create it later.
    target_node_id = _stable_id(f"table:{source_qualified}")
    edge_id = _edge_id("READS_FROM", view_node_id, target_node_id)
    source_kind = "materialized_view_sql" if parsed.is_materialized else "view_sql"

    evidence = _make_evidence(
        kind=source_kind,
        rel_path=parsed.rel_path,
        start_line=parsed.start_line,
        end_line=parsed.end_line,
    )

    return DatabaseGraphEdge(
        id=edge_id,
        kind=EdgeKind.READS_FROM.value,
        from_node=view_node_id,
        to_node=target_node_id,
        properties=(
            ("source_table", source_qualified),
        ),
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_view_sql(
    repo_root: str | Path,
    *,
    view_relpaths: tuple[str, ...] = _DEFAULT_VIEW_RELPATHS,
    mview_relpaths: tuple[str, ...] = _DEFAULT_MVIEW_RELPATHS,
) -> ViewSqlIngestResult:
    """Scan Flyway ``R__*.sql`` files and extract view/MV definitions.

    Parameters:
        repo_root: Absolute or relative path to the repository root.
        view_relpaths: Glob patterns (relative to *repo_root*) for regular
            view SQL files.
        mview_relpaths: Glob patterns (relative to *repo_root*) for
            materialized view SQL files.

    Returns:
        A :class:`ViewSqlIngestResult` with all discovered nodes, edges,
        and summary counts.
    """
    root = Path(repo_root).resolve()

    all_nodes: list[DatabaseGraphNode] = []
    all_edges: list[DatabaseGraphEdge] = []
    all_warnings: list[str] = []

    view_count = 0
    mview_count = 0
    column_count = 0
    dependency_count = 0

    # Collect SQL files from all configured paths
    file_specs: list[tuple[Path, bool]] = []  # (path, is_mview_dir)

    for pattern in view_relpaths:
        matched = sorted(root.glob(pattern))
        if not matched:
            log.debug("No files matched view pattern: %s", pattern)
        for p in matched:
            file_specs.append((p, False))

    for pattern in mview_relpaths:
        matched = sorted(root.glob(pattern))
        if not matched:
            log.debug("No files matched mview pattern: %s", pattern)
        for p in matched:
            file_specs.append((p, True))

    # Track seen view qualified names to avoid duplicates
    seen_views: set[str] = set()

    for file_path, is_mview_dir in file_specs:
        parsed_views, warnings = _parse_sql_file(file_path, root, is_mview_dir=is_mview_dir)
        all_warnings.extend(warnings)

        for parsed in parsed_views:
            # Build view/MV node
            view_node = _build_view_node(parsed)

            # Deduplicate (same view defined in multiple files — last one wins,
            # but we warn).
            if view_node.qualified_name in seen_views:
                all_warnings.append(
                    f"Duplicate view definition: {view_node.qualified_name} "
                    f"in {parsed.rel_path} (already seen)"
                )
                continue
            seen_views.add(view_node.qualified_name)

            all_nodes.append(view_node)
            if parsed.is_materialized:
                mview_count += 1
            else:
                view_count += 1

            # Build column nodes + HAS_COLUMN edges
            seen_cols: set[str] = set()
            for col_name in parsed.columns:
                if col_name in seen_cols:
                    continue
                seen_cols.add(col_name)

                col_node = _build_column_node(
                    col_name,
                    view_node.qualified_name,
                    parsed.schema,
                    parsed,
                )
                all_nodes.append(col_node)
                column_count += 1

                edge = _build_has_column_edge(view_node.id, col_node.id, parsed)
                all_edges.append(edge)

            # Build READS_FROM edges to source tables
            seen_deps: set[tuple[str | None, str]] = set()
            for src_schema, src_table in parsed.source_tables:
                dep_key = (src_schema, src_table)
                if dep_key in seen_deps:
                    continue
                seen_deps.add(dep_key)

                # Skip self-references (recursive views)
                if src_table == parsed.name and src_schema == parsed.schema:
                    continue

                edge = _build_reads_from_edge(
                    view_node.id, src_schema, src_table, parsed,
                )
                all_edges.append(edge)
                dependency_count += 1

    log.info(
        "View SQL ingest: %d views, %d MVs, %d columns, %d deps, %d warnings",
        view_count,
        mview_count,
        column_count,
        dependency_count,
        len(all_warnings),
    )

    return ViewSqlIngestResult(
        nodes=tuple(all_nodes),
        edges=tuple(all_edges),
        view_count=view_count,
        materialized_view_count=mview_count,
        column_count=column_count,
        dependency_count=dependency_count,
        warnings=tuple(all_warnings),
    )
