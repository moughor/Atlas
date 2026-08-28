"""Flyway versioned migration SQL ingest for the Atlas Database Graph.

Parses ``V*.sql`` files from Flyway-managed migration directories to discover
schema changes made *after* the Jailer baseline snapshot:

- **CREATE TABLE** — tables introduced by migrations.
- **ALTER TABLE ADD** — columns added post-Jailer.
- **ALTER TABLE DROP COLUMN** — dropped columns (with lineage).
- **ALTER TABLE RENAME COLUMN** — column renames.
- **ALTER TABLE MODIFY** — column type/constraint changes.

Every produced node and edge carries a fully-populated
:class:`~.models.EvidenceRecord` with ``kind='migration'``, the
repository-relative source path, and line numbers.

Migration files are processed in Flyway version order
(``V{major}_{minor}_{seq}__description.sql``).
"""

from __future__ import annotations

import glob
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIGRATION_EVIDENCE_KIND = "migration"

_DEFAULT_MIGRATION_RELPATHS: tuple[str, ...] = (
    "sygma-db/src/main/resources/db/migration/releases/*/structures/V*.sql",
    "csc-common/csc-common-db/src/main/resources/db_csc/migration/releases/*/structures/V*.sql",
)

# ---------------------------------------------------------------------------
# Flyway version key extraction for ordering
# ---------------------------------------------------------------------------

_FLYWAY_VERSION_RE = re.compile(
    r"V(\d+)(?:_(\d+))?(?:_(\d+))?",
    re.IGNORECASE,
)


def _flyway_sort_key(path: Path) -> tuple[int, int, int, str]:
    """Return a sort key that orders files in Flyway version order.

    Falls back to lexicographic sort on the stem if the version pattern
    does not match.
    """
    m = _FLYWAY_VERSION_RE.match(path.stem)
    if m:
        major = int(m.group(1))
        minor = int(m.group(2)) if m.group(2) else 0
        seq = int(m.group(3)) if m.group(3) else 0
        return (major, minor, seq, path.stem)
    return (0, 0, 0, path.stem)


# ---------------------------------------------------------------------------
# Regex patterns for SQL parsing
# ---------------------------------------------------------------------------

# Matches: CREATE TABLE [IF NOT EXISTS] [schema.]name (
_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?:\"?(\w+)\"?\.)?\"?(\w+)\"?\s*\(",
    re.IGNORECASE,
)

# Matches: ALTER TABLE [schema.]name ADD ( col type ... )
# Also handles: ALTER TABLE [schema.]name ADD col type ...  (without parens)
_ALTER_ADD_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:\"?(\w+)\"?\.)?\"?(\w+)\"?\s+ADD\s+(?!\s*CONSTRAINT)",
    re.IGNORECASE,
)

# Matches: ALTER TABLE [schema.]name ADD CONSTRAINT ...
_ALTER_ADD_CONSTRAINT_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:\"?(\w+)\"?\.)?\"?(\w+)\"?\s+ADD\s+CONSTRAINT\b",
    re.IGNORECASE,
)

# Matches: ALTER TABLE [schema.]name DROP COLUMN col
_ALTER_DROP_COL_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:\"?(\w+)\"?\.)?\"?(\w+)\"?\s+DROP\s+COLUMN\s+\"?(\w+)\"?",
    re.IGNORECASE,
)

# Matches: ALTER TABLE [schema.]name RENAME COLUMN old TO new
_ALTER_RENAME_COL_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:\"?(\w+)\"?\.)?\"?(\w+)\"?\s+RENAME\s+COLUMN\s+"
    r"\"?(\w+)\"?\s+TO\s+\"?(\w+)\"?",
    re.IGNORECASE,
)

# Matches: ALTER TABLE [schema.]name MODIFY ( col type ... )
# Also handles: ALTER TABLE [schema.]name MODIFY col type ... (without parens)
_ALTER_MODIFY_RE = re.compile(
    r"ALTER\s+TABLE\s+(?:\"?(\w+)\"?\.)?\"?(\w+)\"?\s+MODIFY\s+(?!\s*CONSTRAINT)",
    re.IGNORECASE,
)

# Column definition inside CREATE TABLE or ADD/MODIFY block:
# col_name TYPE [( precision )] [NOT NULL] [DEFAULT ...] [CONSTRAINT ...]
_COLUMN_DEF_RE = re.compile(
    r"^\s*\"?(\w+)\"?\s+"
    r"((?:(?:NUMBER|VARCHAR2?|CHAR|NVARCHAR2?|NCHAR|CLOB|NCLOB|BLOB|DATE|"
    r"TIMESTAMP|INTEGER|INT|BIGINT|SMALLINT|DECIMAL|NUMERIC|FLOAT|"
    r"DOUBLE\s+PRECISION|REAL|BOOLEAN|RAW|LONG\s+RAW|LONG|XMLTYPE|"
    r"INTERVAL\s+\w+(?:\s+TO\s+\w+)?|ROWID|UROWID|BFILE|BINARY_FLOAT|"
    r"BINARY_DOUBLE|SDO_GEOMETRY|SYS\.?\w+)"
    r"(?:\s*\([^)]*\))?)"       # optional precision/scale in parens
    r")"
    r"(\s+.+)?$",               # remaining constraints (NOT NULL, DEFAULT, etc.)
    re.IGNORECASE,
)

# Detects constraint lines to skip (PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK, CONSTRAINT ...)
_CONSTRAINT_LINE_RE = re.compile(
    r"^\s*(?:CONSTRAINT|PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Stable ID helpers
# ---------------------------------------------------------------------------

def _stable_id(canonical_name: str) -> str:
    """SHA-256 hex digest of a canonical name string."""
    return hashlib.sha256(canonical_name.encode()).hexdigest()


def _table_qname(schema: str | None, table: str) -> str:
    table_up = table.upper()
    if schema:
        return f"{schema.upper()}.{table_up}"
    return table_up


def _column_qname(schema: str | None, table: str, column: str) -> str:
    return f"{_table_qname(schema, table)}.{column.upper()}"


# ---------------------------------------------------------------------------
# Evidence helper
# ---------------------------------------------------------------------------

def _make_evidence(
    rel_path: str,
    start_line: int,
    end_line: int,
    *,
    observed_version: str | None = None,
) -> EvidenceRecord:
    """Build a verified evidence record for a migration source location."""
    return EvidenceRecord(
        status=EvidenceStatus.VERIFIED.value,
        confidence=1.0,
        sources=(
            EvidenceSource(
                kind=_MIGRATION_EVIDENCE_KIND,
                path=rel_path,
                start_line=start_line,
                end_line=end_line,
                observed_version=observed_version,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MigrationIngestResult:
    """Outcome of a Flyway migration ingest run.

    Attributes:
        nodes: All produced nodes (tables, columns, migration markers).
        edges: All produced edges (HAS_COLUMN, RENAMES, etc.).
        created_tables: Names of tables created by migrations.
        dropped_columns: Tuples of (table_name, column_name, migration_path)
            for every column dropped.
        migration_count: Number of migration files successfully processed.
        warnings: Non-fatal parse warnings.
    """

    nodes: tuple[DatabaseGraphNode, ...]
    edges: tuple[DatabaseGraphEdge, ...]
    created_tables: tuple[str, ...]
    dropped_columns: tuple[tuple[str, str, str], ...]
    migration_count: int
    warnings: tuple[str, ...]


# ---------------------------------------------------------------------------
# Internal: statement block extraction
# ---------------------------------------------------------------------------

def _find_statement_end(lines: list[str], start_idx: int) -> int:
    """Find the 1-based end line of a SQL statement beginning at *start_idx*.

    Scans forward until a line ending with ``;`` or ``/`` (Oracle terminator)
    or until end-of-file.
    """
    for i in range(start_idx, len(lines)):
        stripped = lines[i].rstrip()
        if stripped.endswith(";") or stripped == "/":
            return i + 1  # 1-based
    return len(lines)


def _extract_paren_block(text: str, open_pos: int) -> str | None:
    """Extract text between balanced parentheses starting at *open_pos*.

    Returns the inner text (without the outer parens), or None on mismatch.
    """
    if open_pos >= len(text) or text[open_pos] != "(":
        return None
    depth = 0
    for i in range(open_pos, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[open_pos + 1 : i]
    return None


def _parse_column_defs(block: str) -> list[tuple[str, str, str]]:
    """Parse column definitions from the inner text of a parenthesised block.

    Returns a list of ``(column_name, data_type, constraints_tail)`` tuples.
    Constraint-only lines (PRIMARY KEY, FOREIGN KEY, etc.) are skipped.
    """
    columns: list[tuple[str, str, str]] = []
    # Split on commas that are NOT inside nested parentheses
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in block:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))

    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Skip constraint declarations
        if _CONSTRAINT_LINE_RE.match(part):
            continue
        m = _COLUMN_DEF_RE.match(part)
        if m:
            col_name = m.group(1)
            col_type = m.group(2).strip()
            col_tail = (m.group(3) or "").strip()
            columns.append((col_name, col_type, col_tail))
    return columns


# ---------------------------------------------------------------------------
# Internal: per-statement handlers
# ---------------------------------------------------------------------------

class _IngestAccumulator:
    """Mutable accumulator for a single ingest run."""

    __slots__ = (
        "nodes", "edges", "created_tables", "dropped_columns",
        "warnings", "_seen_nodes", "_seen_edges",
    )

    def __init__(self) -> None:
        self.nodes: list[DatabaseGraphNode] = []
        self.edges: list[DatabaseGraphEdge] = []
        self.created_tables: list[str] = []
        self.dropped_columns: list[tuple[str, str, str]] = []
        self.warnings: list[str] = []
        self._seen_nodes: set[str] = set()
        self._seen_edges: set[str] = set()

    # ---- node/edge de-duplication helpers ----

    def add_node(self, node: DatabaseGraphNode) -> None:
        if node.id not in self._seen_nodes:
            self.nodes.append(node)
            self._seen_nodes.add(node.id)

    def add_edge(self, edge: DatabaseGraphEdge) -> None:
        if edge.id not in self._seen_edges:
            self.edges.append(edge)
            self._seen_edges.add(edge.id)

    def update_node(self, node_id: str, new_node: DatabaseGraphNode) -> None:
        """Replace an existing node in-place (for MODIFY / RENAME)."""
        for idx, existing in enumerate(self.nodes):
            if existing.id == node_id:
                self.nodes[idx] = new_node
                return
        # Not found — just add
        self.add_node(new_node)


def _handle_create_table(
    acc: _IngestAccumulator,
    sql_text: str,
    match: re.Match[str],
    rel_path: str,
    start_line: int,
    end_line: int,
) -> None:
    """Process a CREATE TABLE statement."""
    schema = match.group(1)
    table = match.group(2)
    table_qn = _table_qname(schema, table)

    evidence = _make_evidence(rel_path, start_line, end_line)

    # Table node
    table_node = DatabaseGraphNode(
        id=_stable_id(table_qn),
        kind=NodeKind.TABLE.value,
        qualified_name=table_qn,
        schema=schema.upper() if schema else None,
        properties=(
            ("source", "migration"),
            ("migration_path", rel_path),
        ),
        evidence=evidence,
    )
    acc.add_node(table_node)
    acc.created_tables.append(table_qn)

    # Parse column definitions from the parenthesised block
    paren_pos = sql_text.find("(", match.end() - 1)
    if paren_pos == -1:
        acc.warnings.append(
            f"{rel_path}:{start_line}: CREATE TABLE {table_qn} — "
            f"could not locate opening parenthesis"
        )
        return

    inner = _extract_paren_block(sql_text, paren_pos)
    if inner is None:
        acc.warnings.append(
            f"{rel_path}:{start_line}: CREATE TABLE {table_qn} — "
            f"unbalanced parentheses"
        )
        return

    col_defs = _parse_column_defs(inner)
    for col_name, col_type, col_tail in col_defs:
        col_qn = _column_qname(schema, table, col_name)
        nullable = "NOT NULL" not in col_tail.upper() if col_tail else True
        col_node = DatabaseGraphNode(
            id=_stable_id(col_qn),
            kind=NodeKind.COLUMN.value,
            qualified_name=col_qn,
            schema=schema.upper() if schema else None,
            properties=(
                ("data_type", col_type),
                ("nullable", nullable),
                ("source", "migration"),
                ("migration_path", rel_path),
            ),
            evidence=evidence,
        )
        acc.add_node(col_node)

        edge_id = _stable_id(f"HAS_COLUMN:{table_qn}->{col_qn}")
        edge = DatabaseGraphEdge(
            id=edge_id,
            kind=EdgeKind.HAS_COLUMN.value,
            from_node=table_node.id,
            to_node=col_node.id,
            evidence=evidence,
        )
        acc.add_edge(edge)


def _handle_alter_add(
    acc: _IngestAccumulator,
    sql_text: str,
    match: re.Match[str],
    rel_path: str,
    start_line: int,
    end_line: int,
) -> None:
    """Process an ALTER TABLE ... ADD (column definitions) statement."""
    schema = match.group(1)
    table = match.group(2)
    table_qn = _table_qname(schema, table)
    evidence = _make_evidence(rel_path, start_line, end_line)

    # Look for the table node; create a placeholder if missing
    table_id = _stable_id(table_qn)
    if table_id not in {n.id for n in acc.nodes}:
        table_node = DatabaseGraphNode(
            id=table_id,
            kind=NodeKind.TABLE.value,
            qualified_name=table_qn,
            schema=schema.upper() if schema else None,
            evidence=EvidenceRecord(
                status=EvidenceStatus.INFERRED.value,
                confidence=0.8,
            ),
        )
        acc.add_node(table_node)

    remaining = sql_text[match.end():]

    # Check for parenthesised block: ADD ( col1, col2 )
    paren_match = re.match(r"\s*\(", remaining)
    if paren_match:
        paren_pos = match.end() + remaining.index("(")
        inner = _extract_paren_block(sql_text, paren_pos)
        if inner is None:
            acc.warnings.append(
                f"{rel_path}:{start_line}: ALTER TABLE {table_qn} ADD — "
                f"unbalanced parentheses"
            )
            return
        col_defs = _parse_column_defs(inner)
    else:
        # Single column ADD without parens: ADD col_name TYPE ...
        # Take everything up to the statement terminator
        single_def = remaining.strip().rstrip(";").rstrip("/").strip()
        col_defs = _parse_column_defs(single_def)

    for col_name, col_type, col_tail in col_defs:
        col_qn = _column_qname(schema, table, col_name)
        nullable = "NOT NULL" not in col_tail.upper() if col_tail else True

        col_node = DatabaseGraphNode(
            id=_stable_id(col_qn),
            kind=NodeKind.COLUMN.value,
            qualified_name=col_qn,
            schema=schema.upper() if schema else None,
            properties=(
                ("data_type", col_type),
                ("nullable", nullable),
                ("source", "migration"),
                ("migration_path", rel_path),
            ),
            evidence=evidence,
        )
        acc.add_node(col_node)

        edge_id = _stable_id(f"HAS_COLUMN:{table_qn}->{col_qn}")
        edge = DatabaseGraphEdge(
            id=edge_id,
            kind=EdgeKind.HAS_COLUMN.value,
            from_node=table_id,
            to_node=col_node.id,
            evidence=evidence,
        )
        acc.add_edge(edge)


def _handle_alter_drop_column(
    acc: _IngestAccumulator,
    match: re.Match[str],
    rel_path: str,
    start_line: int,
    end_line: int,
) -> None:
    """Process an ALTER TABLE ... DROP COLUMN statement."""
    schema = match.group(1)
    table = match.group(2)
    column = match.group(3)
    table_qn = _table_qname(schema, table)
    col_qn = _column_qname(schema, table, column)
    evidence = _make_evidence(rel_path, start_line, end_line)

    col_node = DatabaseGraphNode(
        id=_stable_id(col_qn),
        kind=NodeKind.COLUMN.value,
        qualified_name=col_qn,
        schema=schema.upper() if schema else None,
        properties=(
            ("dropped", True),
            ("dropped_by", rel_path),
            ("source", "migration"),
            ("migration_path", rel_path),
        ),
        evidence=evidence,
    )
    # Replace existing node if present, otherwise add
    acc.update_node(col_node.id, col_node)
    acc.dropped_columns.append((table_qn, column.upper(), rel_path))


def _handle_alter_rename_column(
    acc: _IngestAccumulator,
    match: re.Match[str],
    rel_path: str,
    start_line: int,
    end_line: int,
) -> None:
    """Process an ALTER TABLE ... RENAME COLUMN old TO new."""
    schema = match.group(1)
    table = match.group(2)
    old_col = match.group(3)
    new_col = match.group(4)
    table_qn = _table_qname(schema, table)
    old_qn = _column_qname(schema, table, old_col)
    new_qn = _column_qname(schema, table, new_col)
    evidence = _make_evidence(rel_path, start_line, end_line)
    table_id = _stable_id(table_qn)

    # Create a node for the new column name
    new_col_node = DatabaseGraphNode(
        id=_stable_id(new_qn),
        kind=NodeKind.COLUMN.value,
        qualified_name=new_qn,
        schema=schema.upper() if schema else None,
        properties=(
            ("renamed_from", old_col.upper()),
            ("source", "migration"),
            ("migration_path", rel_path),
        ),
        evidence=evidence,
    )
    acc.add_node(new_col_node)

    # RENAMES edge from old column id to new column id
    rename_edge_id = _stable_id(f"RENAMES:{old_qn}->{new_qn}")
    rename_edge = DatabaseGraphEdge(
        id=rename_edge_id,
        kind=EdgeKind.RENAMES.value,
        from_node=_stable_id(old_qn),
        to_node=new_col_node.id,
        evidence=evidence,
    )
    acc.add_edge(rename_edge)

    # HAS_COLUMN edge for the new column
    has_col_edge_id = _stable_id(f"HAS_COLUMN:{table_qn}->{new_qn}")
    has_col_edge = DatabaseGraphEdge(
        id=has_col_edge_id,
        kind=EdgeKind.HAS_COLUMN.value,
        from_node=table_id,
        to_node=new_col_node.id,
        evidence=evidence,
    )
    acc.add_edge(has_col_edge)


def _handle_alter_modify(
    acc: _IngestAccumulator,
    sql_text: str,
    match: re.Match[str],
    rel_path: str,
    start_line: int,
    end_line: int,
) -> None:
    """Process an ALTER TABLE ... MODIFY statement."""
    schema = match.group(1)
    table = match.group(2)
    table_qn = _table_qname(schema, table)
    evidence = _make_evidence(rel_path, start_line, end_line)

    remaining = sql_text[match.end():]

    # Check for parenthesised block: MODIFY ( col1, col2 )
    paren_match = re.match(r"\s*\(", remaining)
    if paren_match:
        paren_pos = match.end() + remaining.index("(")
        inner = _extract_paren_block(sql_text, paren_pos)
        if inner is None:
            acc.warnings.append(
                f"{rel_path}:{start_line}: ALTER TABLE {table_qn} MODIFY — "
                f"unbalanced parentheses"
            )
            return
        col_defs = _parse_column_defs(inner)
    else:
        single_def = remaining.strip().rstrip(";").rstrip("/").strip()
        col_defs = _parse_column_defs(single_def)

    for col_name, col_type, col_tail in col_defs:
        col_qn = _column_qname(schema, table, col_name)
        nullable = "NOT NULL" not in col_tail.upper() if col_tail else True
        col_id = _stable_id(col_qn)

        col_node = DatabaseGraphNode(
            id=col_id,
            kind=NodeKind.COLUMN.value,
            qualified_name=col_qn,
            schema=schema.upper() if schema else None,
            properties=(
                ("data_type", col_type),
                ("nullable", nullable),
                ("modified", True),
                ("source", "migration"),
                ("migration_path", rel_path),
            ),
            evidence=evidence,
        )
        acc.update_node(col_id, col_node)


# ---------------------------------------------------------------------------
# Single-file parser
# ---------------------------------------------------------------------------

def _parse_migration_file(
    file_path: Path,
    rel_path: str,
    acc: _IngestAccumulator,
) -> None:
    """Parse one migration SQL file and accumulate nodes/edges/warnings."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        acc.warnings.append(f"{rel_path}: could not read file — {exc}")
        return

    lines = content.splitlines()
    # Remove single-line comments and collapse for multi-line matching,
    # but keep the original lines for line-number evidence.
    # We process the raw text statement-by-statement.

    # Join all lines into one text block for regex matching,
    # recording the character offset of each line start for line mapping.
    line_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line) + 1  # +1 for the newline

    full_text = "\n".join(lines)

    def _char_to_line(pos: int) -> int:
        """Convert a character offset in *full_text* to a 1-based line number."""
        lo, hi = 0, len(line_offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_offsets[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1  # 1-based

    # ---- Strip block comments for cleaner matching ----
    # We keep original text for line-number mapping, but strip comments
    # from a working copy used for regex matching.
    clean_text = re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group()), full_text, flags=re.DOTALL)
    clean_text = re.sub(r"--[^\n]*", lambda m: " " * len(m.group()), clean_text)

    # ---- CREATE TABLE ----
    for m in _CREATE_TABLE_RE.finditer(clean_text):
        stmt_start = _char_to_line(m.start())
        # Find the closing paren + semicolon for end_line
        paren_pos = clean_text.find("(", m.end() - 1)
        if paren_pos != -1:
            inner = _extract_paren_block(clean_text, paren_pos)
            if inner is not None:
                close_pos = paren_pos + len(inner) + 2  # +2 for ( and )
                stmt_end = _char_to_line(min(close_pos, len(clean_text) - 1))
            else:
                stmt_end = _char_to_line(m.end())
        else:
            stmt_end = _char_to_line(m.end())

        _handle_create_table(acc, clean_text, m, rel_path, stmt_start, stmt_end)

    # ---- ALTER TABLE ... ADD CONSTRAINT (skip — no column production) ----
    # These are matched first to avoid false positives with ADD column.
    add_constraint_spans: list[tuple[int, int]] = []
    for m in _ALTER_ADD_CONSTRAINT_RE.finditer(clean_text):
        add_constraint_spans.append((m.start(), m.end()))

    def _in_constraint_span(pos: int) -> bool:
        return any(s <= pos < e for s, e in add_constraint_spans)

    # ---- ALTER TABLE ... ADD (columns) ----
    for m in _ALTER_ADD_RE.finditer(clean_text):
        if _in_constraint_span(m.start()):
            continue
        stmt_start = _char_to_line(m.start())
        # Determine statement end
        remaining = clean_text[m.end():]
        paren_m = re.match(r"\s*\(", remaining)
        if paren_m:
            paren_pos = m.end() + remaining.index("(")
            inner = _extract_paren_block(clean_text, paren_pos)
            if inner is not None:
                close_pos = paren_pos + len(inner) + 2
                stmt_end = _char_to_line(min(close_pos, len(clean_text) - 1))
            else:
                stmt_end = _char_to_line(m.end())
        else:
            # Single-column ADD — find ;
            semi = clean_text.find(";", m.end())
            stmt_end = _char_to_line(semi) if semi != -1 else _char_to_line(m.end())

        _handle_alter_add(acc, clean_text, m, rel_path, stmt_start, stmt_end)

    # ---- ALTER TABLE ... DROP COLUMN ----
    for m in _ALTER_DROP_COL_RE.finditer(clean_text):
        stmt_start = _char_to_line(m.start())
        semi = clean_text.find(";", m.end())
        stmt_end = _char_to_line(semi) if semi != -1 else _char_to_line(m.end())
        _handle_alter_drop_column(acc, m, rel_path, stmt_start, stmt_end)

    # ---- ALTER TABLE ... RENAME COLUMN ----
    for m in _ALTER_RENAME_COL_RE.finditer(clean_text):
        stmt_start = _char_to_line(m.start())
        semi = clean_text.find(";", m.end())
        stmt_end = _char_to_line(semi) if semi != -1 else _char_to_line(m.end())
        _handle_alter_rename_column(acc, m, rel_path, stmt_start, stmt_end)

    # ---- ALTER TABLE ... MODIFY ----
    for m in _ALTER_MODIFY_RE.finditer(clean_text):
        stmt_start = _char_to_line(m.start())
        remaining = clean_text[m.end():]
        paren_m = re.match(r"\s*\(", remaining)
        if paren_m:
            paren_pos = m.end() + remaining.index("(")
            inner = _extract_paren_block(clean_text, paren_pos)
            if inner is not None:
                close_pos = paren_pos + len(inner) + 2
                stmt_end = _char_to_line(min(close_pos, len(clean_text) - 1))
            else:
                stmt_end = _char_to_line(m.end())
        else:
            semi = clean_text.find(";", m.end())
            stmt_end = _char_to_line(semi) if semi != -1 else _char_to_line(m.end())

        _handle_alter_modify(acc, clean_text, m, rel_path, stmt_start, stmt_end)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_migrations(
    repo_root: str | Path,
    *,
    migration_relpaths: tuple[str, ...] = _DEFAULT_MIGRATION_RELPATHS,
) -> MigrationIngestResult:
    """Scan Flyway versioned migration files and produce graph nodes/edges.

    Parameters
    ----------
    repo_root:
        Absolute or relative path to the repository root directory.
    migration_relpaths:
        Glob patterns (relative to *repo_root*) for migration SQL files.
        Defaults to the standard SyGMa and CSC-Common migration paths.

    Returns
    -------
    MigrationIngestResult
        Contains the discovered nodes, edges, created tables, dropped columns,
        migration count, and any parse warnings.
    """
    root = Path(repo_root).resolve()
    acc = _IngestAccumulator()
    migration_count = 0

    # Collect all matching migration files across all glob patterns
    all_files: list[Path] = []
    for relpath_pattern in migration_relpaths:
        pattern = str(root / relpath_pattern)
        matched = [Path(p) for p in glob.glob(pattern, recursive=False)]
        all_files.extend(matched)

    # De-duplicate (in case patterns overlap) and sort by Flyway version
    seen_paths: set[str] = set()
    unique_files: list[Path] = []
    for f in all_files:
        resolved = str(f.resolve())
        if resolved not in seen_paths:
            seen_paths.add(resolved)
            unique_files.append(f)

    unique_files.sort(key=_flyway_sort_key)

    for file_path in unique_files:
        try:
            rel_path = str(file_path.relative_to(root))
        except ValueError:
            rel_path = str(file_path)

        logger.debug("Parsing migration: %s", rel_path)
        _parse_migration_file(file_path, rel_path, acc)
        migration_count += 1

    if migration_count == 0:
        logger.info(
            "No migration files found under %s for patterns: %s",
            root,
            migration_relpaths,
        )

    return MigrationIngestResult(
        nodes=tuple(acc.nodes),
        edges=tuple(acc.edges),
        created_tables=tuple(acc.created_tables),
        dropped_columns=tuple(acc.dropped_columns),
        migration_count=migration_count,
        warnings=tuple(acc.warnings),
    )
