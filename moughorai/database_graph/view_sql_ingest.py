"""Oracle view and materialized-view SQL ingestion for the Atlas Database Graph.

Scans a Sygma repository for Oracle view and materialized-view SQL definitions
across four source directories, parses each file to extract object names,
projected columns, and table dependencies, detects duplicate definitions, and
produces :class:`DatabaseGraphNode` and :class:`DatabaseGraphEdge` instances
with full evidence provenance.

Scan paths (relative to *repo_root*):

1. ``sygma-db/src/main/resources/VIEWS/``          — regular views (recursive)
2. ``sygma-db/src/main/resources/MATERIALIZED_VIEWS/`` — materialized views (recursive)
3. ``sygma-db/src/main/resources/db/migration/views/`` — Flyway repeatable view defs
4. ``sygma-db/src/main/resources/db/env_specific/mviews/`` — environment-specific MVs

``BACK_UP`` directories and ``target/`` build-artifact directories are excluded.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .models import (
    ConflictRecord,
    DatabaseGraphEdge,
    DatabaseGraphNode,
    EdgeKind,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    NodeKind,
)

__all__ = [
    "ViewIngestResult",
    "ViewSqlIngestResult",  # backward-compatible alias
    "ingest_view_sql",
]

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scan-path configuration
# ---------------------------------------------------------------------------

# (relative_dir, glob, is_mview, priority)
# Priority: higher number = more current.  Migration/env_specific preferred.
_SCAN_SPECS: tuple[tuple[str, str, bool, int], ...] = (
    ("sygma-db/src/main/resources/VIEWS", "**/*.sql", False, 1),
    ("sygma-db/src/main/resources/MATERIALIZED_VIEWS", "**/*.sql", True, 1),
    ("sygma-db/src/main/resources/db/migration/views", "*.sql", False, 2),
    ("sygma-db/src/main/resources/db/env_specific/mviews", "*.sql", True, 2),
)

# Path segments to exclude
_EXCLUDED_SEGMENTS = {"BACK_UP", "target"}


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ViewIngestResult:
    """Outcome of a view SQL ingest run."""

    view_nodes: tuple[DatabaseGraphNode, ...]
    column_nodes: tuple[DatabaseGraphNode, ...]
    dependency_edges: tuple[DatabaseGraphEdge, ...]
    column_edges: tuple[DatabaseGraphEdge, ...]
    all_nodes: tuple[DatabaseGraphNode, ...]
    all_edges: tuple[DatabaseGraphEdge, ...]
    view_count: int
    mv_count: int
    column_count: int
    dependency_count: int
    conflicts: tuple[ConflictRecord, ...]
    source_paths_scanned: tuple[str, ...]
    warnings: tuple[str, ...]

    # Backward-compatible aliases used by reconciler.py
    @property
    def nodes(self) -> tuple[DatabaseGraphNode, ...]:
        """Alias for :attr:`all_nodes` (backward compatibility)."""
        return self.all_nodes

    @property
    def edges(self) -> tuple[DatabaseGraphEdge, ...]:
        """Alias for :attr:`all_edges` (backward compatibility)."""
        return self.all_edges

    @property
    def materialized_view_count(self) -> int:
        """Alias for :attr:`mv_count` (backward compatibility)."""
        return self.mv_count


# Backward-compatible alias for existing code that imported ViewSqlIngestResult
ViewSqlIngestResult = ViewIngestResult


# ---------------------------------------------------------------------------
# Deterministic id helpers
# ---------------------------------------------------------------------------

def _stable_id(canonical_name: str) -> str:
    return hashlib.sha256(canonical_name.encode()).hexdigest()


def _edge_id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# SQL comment stripping
# ---------------------------------------------------------------------------

_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


def _strip_sql_comments(sql: str) -> str:
    """Remove SQL block and line comments, preserving line structure."""
    def _block_repl(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")
    sql = _BLOCK_COMMENT_RE.sub(_block_repl, sql)
    sql = _LINE_COMMENT_RE.sub("", sql)
    return sql


# ---------------------------------------------------------------------------
# PL/SQL wrapper stripping
# ---------------------------------------------------------------------------

# Matches SET SERVEROUTPUT ON at the start
_SET_SERVEROUTPUT_RE = re.compile(
    r"^\s*set\s+serveroutput\s+on\s*;?\s*\n?",
    re.IGNORECASE | re.MULTILINE,
)

# Matches DECLARE ... BEGIN ... END; / blocks (PL/SQL anonymous blocks)
# Uses a conservative approach: find DECLARE, track BEGIN/END depth
_PLSQL_BLOCK_RE = re.compile(
    r"""
    (?:^|\n)\s*                # start of line or after newline
    (?:DECLARE|BEGIN)\b        # PL/SQL block start keyword
    [\s\S]*?                   # block body (non-greedy)
    \bEND\s*;                  # END; terminator
    \s*/?\s*\n?                # optional / execution and newline
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _strip_plsql_wrappers(sql: str) -> str:
    """Remove PL/SQL wrapper blocks that precede the actual CREATE statement.

    Handles SET SERVEROUTPUT ON and DECLARE...BEGIN...END;/ blocks that
    appear before CREATE MATERIALIZED VIEW in Sygma MV files.
    """
    # Only strip content before the first CREATE keyword
    create_match = re.search(r"\bCREATE\b", sql, re.IGNORECASE)
    if create_match is None:
        return sql

    prefix = sql[:create_match.start()]
    rest = sql[create_match.start():]

    # Count newlines in prefix to preserve line numbering offset
    prefix_lines = prefix.count("\n")
    return "\n" * prefix_lines + rest


# ---------------------------------------------------------------------------
# CREATE VIEW / MATERIALIZED VIEW regex
# ---------------------------------------------------------------------------

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
    [\s\S]*?                             # skip any MV clauses (BUILD, REFRESH, etc.)
    \bAS\s+
    (?P<body>.+)
    """,
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)


# ---------------------------------------------------------------------------
# Identifier parsing
# ---------------------------------------------------------------------------

def _unquote(ident: str) -> str:
    s = ident.strip()
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s.upper()


def _parse_qualified_name(raw: str) -> tuple[str | None, str]:
    parts = [_unquote(p) for p in raw.strip().split(".")]
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, parts[0]


# ---------------------------------------------------------------------------
# Column alias extraction
# ---------------------------------------------------------------------------

def _parse_column_list(raw: str) -> list[str]:
    cols: list[str] = []
    for token in raw.split(","):
        token = token.strip()
        if token:
            cols.append(_unquote(token))
    return cols


def _extract_select_aliases(body: str) -> list[str]:
    """Best-effort extraction of column aliases from a SELECT clause.

    Handles CTE (WITH ... AS ...) by skipping to the final SELECT.
    Handles UNION ALL by only parsing the first SELECT's column list.
    """
    # If the body starts with WITH (CTE), skip to the outer query SELECT.
    # The outer SELECT is the FIRST top-level SELECT that comes AFTER all
    # CTE definitions close, not the LAST SELECT in the file (which may be
    # inside a trailing PL/SQL GRANT/INDEX block).
    work = body.strip()
    if re.match(r"\s*WITH\b", work, re.IGNORECASE):
        depth = 0
        cte_ended = False
        outer_select_pos = -1
        i = 4  # skip past "WITH"
        while i < len(work):
            ch = work[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    cte_ended = True
            elif depth == 0 and cte_ended:
                rest = work[i:]
                m = re.match(r"\bSELECT\b", rest, re.IGNORECASE)
                if m:
                    outer_select_pos = i
                    break
                # A comma after a CTE block means another CTE follows
                if ch == ",":
                    cte_ended = False
            i += 1
        if outer_select_pos >= 0:
            work = work[outer_select_pos:]
        else:
            return []

    # Match the SELECT keyword
    m = re.match(r"\s*SELECT\s+(?:DISTINCT\s+|ALL\s+)?", work, re.IGNORECASE)
    if not m:
        return []

    # Walk from end of SELECT, tracking paren depth, to find top-level FROM.
    # We cannot simply use re.match(r'\bFROM\b', rest) on a slice because
    # start-of-string counts as a word boundary, causing false matches on
    # identifiers ending with 'from' (e.g., 'period_from').  Instead, check
    # that the preceding character is a non-word character or the start of
    # the string.
    start = m.end()
    depth = 0
    pos = start
    end = len(work)
    while pos < end:
        ch = work[pos]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            rest = work[pos:]
            if re.match(r"FROM\b", rest, re.IGNORECASE):
                # Verify the preceding char is non-word (true word boundary)
                if pos == 0 or not work[pos - 1].isalnum() and work[pos - 1] != "_":
                    break
        pos += 1

    select_clause = work[start:pos]
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
        stripped = item.strip()
        if stripped in ("*",) or stripped.endswith(".*"):
            continue
        alias = _alias_from_select_item(item)
        if alias:
            aliases.append(alias)

    return aliases


def _alias_from_select_item(item: str) -> str | None:
    item = item.strip()
    if not item:
        return None

    # Explicit AS alias
    m = re.search(r'\bAS\s+(?P<alias>"[^"]+"|[A-Za-z_]\w*)\s*$', item, re.IGNORECASE)
    if m:
        return _unquote(m.group("alias"))

    # Implicit alias: last token separated by whitespace
    parts = item.rsplit(None, 1)
    if len(parts) == 2:
        candidate = parts[1].strip()
        if re.fullmatch(r'"[^"]+"|[A-Za-z_]\w*', candidate):
            # Exclude Oracle functions / keywords that look like identifiers
            upper = candidate.upper().strip('"')
            if upper not in _SQL_KEYWORDS:
                return _unquote(candidate)

    # table.column or bare column
    m = re.fullmatch(
        r'(?:(?:"[^"]+"|[A-Za-z_]\w*)\s*\.\s*)*(?P<col>"[^"]+"|[A-Za-z_]\w*)',
        item,
    )
    if m:
        return _unquote(m.group("col"))

    return None


# ---------------------------------------------------------------------------
# Source-table extraction (FROM / JOIN clauses)
# ---------------------------------------------------------------------------

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
    """Extract source tables from FROM/JOIN clauses in a view body."""
    seen: set[tuple[str | None, str]] = set()
    result: list[tuple[str | None, str]] = []

    for m in _FROM_JOIN_RE.finditer(body):
        raw = m.group("table")
        schema, name = _parse_qualified_name(raw)
        if name in _SQL_KEYWORDS:
            continue
        key = (schema, name)
        if key not in seen:
            seen.add(key)
            result.append(key)

    return result


# ---------------------------------------------------------------------------
# Trim trailing GRANT / CREATE INDEX / COMMENT statements from body
# ---------------------------------------------------------------------------

_POST_VIEW_STMTS_RE = re.compile(
    r"""
    \b(?:GRANT|CREATE\s+(?:UNIQUE\s+)?INDEX|COMMENT\s+ON)\b
    [\s\S]*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

_WITH_READ_ONLY_RE = re.compile(
    r"\bWITH\s+READ\s+ONLY\b[\s;]*$",
    re.IGNORECASE,
)


def _trim_body(body: str) -> str:
    """Remove GRANT, index creation, and COMMENT statements trailing the body.

    Also strips ``WITH READ ONLY`` and trailing semicolons.
    """
    body = _POST_VIEW_STMTS_RE.sub("", body)
    body = _WITH_READ_ONLY_RE.sub("", body)
    # Strip trailing semicolons and whitespace
    body = body.rstrip().rstrip(";").rstrip()
    return body


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
    start_line: int
    end_line: int
    rel_path: str
    priority: int
    body_fingerprint: str  # SHA-256 of trimmed body for conflict detection


def _parse_sql_file(
    file_path: Path,
    repo_root: Path,
    *,
    is_mview_dir: bool,
    priority: int,
) -> tuple[list[_ParsedView], list[str]]:
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

    # Strip comments
    cleaned = _strip_sql_comments(raw_text)

    # Strip PL/SQL wrappers (DECLARE...BEGIN...END blocks before CREATE)
    cleaned = _strip_plsql_wrappers(cleaned)

    for m in _CREATE_VIEW_RE.finditer(cleaned):
        mat_group = m.group("mat")
        is_mat = bool(mat_group and mat_group.strip()) or is_mview_dir
        raw_name = m.group("name")
        cols_raw = m.group("cols")
        body = m.group("body")

        schema, view_name = _parse_qualified_name(raw_name)

        start_line = cleaned[:m.start()].count("\n") + 1
        end_line = cleaned[:m.end()].count("\n") + 1
        if end_line > total_lines:
            end_line = total_lines

        # Trim trailing non-body statements
        trimmed_body = _trim_body(body)

        # Column aliases
        columns: list[str] = []
        if cols_raw:
            columns = _parse_column_list(cols_raw)
        else:
            columns = _extract_select_aliases(trimmed_body)

        # Source tables
        source_tables = _extract_source_tables(trimmed_body)

        # Body fingerprint for conflict detection
        body_fp = hashlib.sha256(
            re.sub(r"\s+", " ", trimmed_body.strip()).upper().encode("utf-8")
        ).hexdigest()

        results.append(_ParsedView(
            name=view_name,
            schema=schema,
            is_materialized=is_mat,
            columns=columns,
            source_tables=source_tables,
            start_line=start_line,
            end_line=end_line,
            rel_path=rel_path,
            priority=priority,
            body_fingerprint=body_fp,
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
    kind = NodeKind.MATERIALIZED_VIEW.value if parsed.is_materialized else NodeKind.VIEW.value
    evidence_kind = "mv_sql" if parsed.is_materialized else "view_sql"

    # Canonical name uses just the object name (strip schema for the ID)
    qualified_name = parsed.name  # canonical name, always uppercase
    node_id = _stable_id(f"{kind}:{qualified_name}")

    evidence = _make_evidence(
        kind=evidence_kind,
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
            ("writable", False),
            ("source_file", parsed.rel_path),
            ("original_schema", parsed.schema) if parsed.schema else ("original_schema", None),
        ),
        evidence=evidence,
    )


def _build_column_node(
    col_name: str,
    view_name: str,
    view_schema: str | None,
    parsed: _ParsedView,
) -> DatabaseGraphNode:
    qualified_name = f"{view_name}.{col_name}"
    node_id = _stable_id(f"column:{qualified_name}")
    evidence_kind = "mv_sql" if parsed.is_materialized else "view_sql"

    evidence = _make_evidence(
        kind=evidence_kind,
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
            ("writable", False),
            ("source_file", parsed.rel_path),
        ),
        evidence=evidence,
    )


def _build_has_column_edge(
    view_node_id: str,
    col_node_id: str,
    parsed: _ParsedView,
) -> DatabaseGraphEdge:
    eid = _edge_id("HAS_COLUMN", view_node_id, col_node_id)
    evidence_kind = "mv_sql" if parsed.is_materialized else "view_sql"

    evidence = _make_evidence(
        kind=evidence_kind,
        rel_path=parsed.rel_path,
        start_line=parsed.start_line,
        end_line=parsed.end_line,
    )

    return DatabaseGraphEdge(
        id=eid,
        kind=EdgeKind.HAS_COLUMN.value,
        from_node=view_node_id,
        to_node=col_node_id,
        evidence=evidence,
    )


def _build_dependency_edge(
    view_node_id: str,
    source_schema: str | None,
    source_table: str,
    parsed: _ParsedView,
    *,
    is_from_mv: bool,
) -> DatabaseGraphEdge:
    """Build a DERIVED_FROM (for MVs) or READS_FROM (for views) edge."""
    source_qualified = f"{source_schema}.{source_table}" if source_schema else source_table
    target_node_id = _stable_id(f"table:{source_qualified}")

    edge_kind = EdgeKind.DERIVED_FROM.value if is_from_mv else EdgeKind.READS_FROM.value
    eid = _edge_id(edge_kind, view_node_id, target_node_id)
    evidence_kind = "mv_sql" if parsed.is_materialized else "view_sql"

    evidence = _make_evidence(
        kind=evidence_kind,
        rel_path=parsed.rel_path,
        start_line=parsed.start_line,
        end_line=parsed.end_line,
    )

    return DatabaseGraphEdge(
        id=eid,
        kind=edge_kind,
        from_node=view_node_id,
        to_node=target_node_id,
        properties=(
            ("source_table", source_qualified),
        ),
        evidence=evidence,
    )


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _is_excluded(path: Path) -> bool:
    """Return True if any path component is an excluded segment."""
    for part in path.parts:
        if part in _EXCLUDED_SEGMENTS:
            return True
    return False


def _discover_files(
    repo_root: Path,
) -> tuple[list[tuple[Path, bool, int]], list[str]]:
    """Discover SQL files from all configured scan paths.

    Returns (file_specs, scanned_dirs) where file_specs is a list of
    (path, is_mview, priority) tuples.
    """
    file_specs: list[tuple[Path, bool, int]] = []
    scanned_dirs: list[str] = []

    for rel_dir, pattern, is_mview, priority in _SCAN_SPECS:
        scan_dir = repo_root / rel_dir
        if not scan_dir.is_dir():
            log.debug("Scan directory does not exist: %s", scan_dir)
            continue

        scanned_dirs.append(str(scan_dir.relative_to(repo_root)))

        matched = sorted(scan_dir.glob(pattern))
        for p in matched:
            if _is_excluded(p.relative_to(repo_root)):
                continue
            if p.is_file():
                file_specs.append((p, is_mview, priority))

    return file_specs, scanned_dirs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_view_sql(
    repo_root: str | Path,
) -> ViewIngestResult:
    """Scan a Sygma repository for Oracle view and materialized-view SQL.

    Parameters:
        repo_root: Absolute path to the Sygma repository root.

    Returns:
        A :class:`ViewIngestResult` with all discovered nodes, edges,
        summary counts, and conflicts.
    """
    root = Path(repo_root).resolve()

    all_warnings: list[str] = []
    conflicts: list[ConflictRecord] = []

    # Phase 1: discover files
    file_specs, scanned_dirs = _discover_files(root)

    # Phase 2: parse all files
    # Group by canonical view name for duplicate detection.
    # Key: uppercase view name  ->  list of _ParsedView (possibly from multiple files)
    parsed_by_name: dict[str, list[_ParsedView]] = {}

    for file_path, is_mview, priority in file_specs:
        parsed_views, warnings = _parse_sql_file(
            file_path, root,
            is_mview_dir=is_mview,
            priority=priority,
        )
        all_warnings.extend(warnings)

        for pv in parsed_views:
            canonical = pv.name  # already uppercase from _unquote
            parsed_by_name.setdefault(canonical, []).append(pv)

    # Phase 3: resolve duplicates and build nodes/edges
    view_nodes: list[DatabaseGraphNode] = []
    column_nodes: list[DatabaseGraphNode] = []
    dependency_edges: list[DatabaseGraphEdge] = []
    column_edges: list[DatabaseGraphEdge] = []

    view_count = 0
    mv_count = 0
    column_count = 0
    dependency_count = 0

    for canonical_name, candidates in sorted(parsed_by_name.items()):
        # Select the winning definition
        if len(candidates) == 1:
            winner = candidates[0]
        else:
            # Sort by priority descending, then by rel_path for determinism
            candidates_sorted = sorted(
                candidates, key=lambda c: (-c.priority, c.rel_path)
            )
            winner = candidates_sorted[0]

            # Check if definitions actually differ (body fingerprint)
            fingerprints = {c.body_fingerprint for c in candidates}
            if len(fingerprints) > 1:
                # Definitions differ — record conflict
                conflict = ConflictRecord(
                    description=(
                        f"View {canonical_name} defined in {len(candidates)} files "
                        f"with differing SQL bodies; using {winner.rel_path} "
                        f"(priority={winner.priority})"
                    ),
                    sources=tuple(
                        EvidenceSource(
                            kind="mv_sql" if c.is_materialized else "view_sql",
                            path=c.rel_path,
                            start_line=c.start_line,
                            end_line=c.end_line,
                        )
                        for c in candidates
                    ),
                    resolution="resolved_priority",
                    resolved_value=winner.rel_path,
                )
                conflicts.append(conflict)
                log.info(
                    "Conflict for %s: %d definitions, using %s",
                    canonical_name, len(candidates), winner.rel_path,
                )
            else:
                # Same body in multiple files — just log, no conflict
                log.debug(
                    "View %s defined in %d files with identical body",
                    canonical_name, len(candidates),
                )

        parsed = winner

        # Build view/MV node
        view_node = _build_view_node(parsed)
        view_nodes.append(view_node)

        if parsed.is_materialized:
            mv_count += 1
        else:
            view_count += 1

        # Build column nodes + HAS_COLUMN edges
        seen_cols: set[str] = set()
        for col_name in parsed.columns:
            if col_name in seen_cols:
                continue
            seen_cols.add(col_name)

            col_node = _build_column_node(
                col_name, parsed.name, parsed.schema, parsed,
            )
            column_nodes.append(col_node)
            column_count += 1

            edge = _build_has_column_edge(view_node.id, col_node.id, parsed)
            column_edges.append(edge)

        # Build dependency edges
        seen_deps: set[tuple[str | None, str]] = set()
        for src_schema, src_table in parsed.source_tables:
            dep_key = (src_schema, src_table)
            if dep_key in seen_deps:
                continue
            seen_deps.add(dep_key)

            # Skip self-references
            if src_table == parsed.name and src_schema == parsed.schema:
                continue

            edge = _build_dependency_edge(
                view_node.id, src_schema, src_table, parsed,
                is_from_mv=parsed.is_materialized,
            )
            dependency_edges.append(edge)
            dependency_count += 1

    all_nodes = list(view_nodes) + list(column_nodes)
    all_edges = list(dependency_edges) + list(column_edges)

    log.info(
        "View SQL ingest: %d views, %d MVs, %d columns, %d deps, "
        "%d conflicts, %d warnings",
        view_count, mv_count, column_count, dependency_count,
        len(conflicts), len(all_warnings),
    )

    return ViewIngestResult(
        view_nodes=tuple(view_nodes),
        column_nodes=tuple(column_nodes),
        dependency_edges=tuple(dependency_edges),
        column_edges=tuple(column_edges),
        all_nodes=tuple(all_nodes),
        all_edges=tuple(all_edges),
        view_count=view_count,
        mv_count=mv_count,
        column_count=column_count,
        dependency_count=dependency_count,
        conflicts=tuple(conflicts),
        source_paths_scanned=tuple(scanned_dirs),
        warnings=tuple(all_warnings),
    )
