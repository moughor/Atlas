"""Static JPA entity extractor for Sygma Java source files.

Reads .java files as text and uses regex/string matching to extract:
- @Entity / @Table annotations with constant-valued table names
- @Column name mappings and @Id annotations
- LazySetProvider / LazyCollectionProvider relationships
- @Embedded / @AttributeOverride column overrides
- @SequenceGenerator sequence names
- In-file constant resolution (ClassName.FIELD_NAME -> string literal)

This is a **static text parser**. It does not require a Java runtime, AST
parser, compilation, or classpath resolution.  Cross-file constant references
that cannot be resolved within the same file are recorded as unresolved.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from moughorai.database_graph.models import EvidenceSource

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result data-classes (plain, not frozen — accumulated during extraction)
# ---------------------------------------------------------------------------


@dataclass
class ColumnMapping:
    """A single @Column annotation found on a Java field."""

    java_field_name: str
    column_name: str
    java_type: str
    is_id: bool = False
    is_lob: bool = False
    nullable: bool = True
    updatable: bool = True
    insertable: bool = True
    source: EvidenceSource | None = None


@dataclass
class EmbeddedOverride:
    """A single @AttributeOverride on an @Embedded field."""

    java_field_name: str
    embedded_type: str
    attribute_name: str
    column_name: str
    nullable: bool = True
    updatable: bool = True
    insertable: bool = True
    source: EvidenceSource | None = None


@dataclass
class LazyRelationship:
    """A LazySetProvider or LazyCollectionProvider relationship."""

    java_field_name: str
    target_type: str
    foreign_key_field: str
    foreign_key_resolved: bool
    collection_name: str
    provider_kind: str  # 'LazySetProvider' or 'LazyCollectionProvider'
    source: EvidenceSource | None = None


@dataclass
class SequenceInfo:
    """A @SequenceGenerator annotation."""

    generator_name: str
    sequence_name: str
    sequence_name_resolved: bool
    initial_value: int = 1
    allocation_size: int = 1
    source: EvidenceSource | None = None


@dataclass
class JpaEntity:
    """A single JPA @Entity extracted from a Java source file."""

    class_name: str
    qualified_name: str
    table_name: str | None
    table_name_resolved: bool
    schema_name: str | None
    extends_class: str | None
    is_test: bool
    source_path: str
    entity_line: int
    columns: list[ColumnMapping] = field(default_factory=list)
    embedded_overrides: list[EmbeddedOverride] = field(default_factory=list)
    relationships: list[LazyRelationship] = field(default_factory=list)
    sequences: list[SequenceInfo] = field(default_factory=list)
    id_columns: list[str] = field(default_factory=list)
    constants: dict[str, str] = field(default_factory=dict)
    has_inheritance: bool = False
    inheritance_strategy: str | None = None


@dataclass
class UnresolvedConstant:
    """A constant reference that could not be resolved within the file."""

    reference: str
    context: str
    source_path: str
    line: int


@dataclass
class JpaExtractionResult:
    """Complete result of JPA extraction across a repository tree."""

    entities: list[JpaEntity] = field(default_factory=list)
    unresolved_constants: list[UnresolvedConstant] = field(default_factory=list)
    files_scanned: int = 0
    files_with_entities: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Well-known Sygma constants (PersistenceConstants)
# ---------------------------------------------------------------------------

_WELL_KNOWN_CONSTANTS: dict[str, str] = {
    "PersistenceConstants.SCHEMA_NAME": "",
    "PersistenceConstants.SEQUENCE_SCHEMA_NAME": "",
}

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# Entity / Table / Inheritance annotations
_RE_ENTITY = re.compile(r"@Entity\b")
_RE_TABLE = re.compile(
    r"@Table\s*\("
    r"(?P<args>[^)]*)"
    r"\)",
    re.DOTALL,
)
_RE_INHERITANCE = re.compile(
    r"@Inheritance\s*\(\s*strategy\s*=\s*InheritanceType\.(?P<strat>\w+)\s*\)"
)

# Class declaration
_RE_CLASS_DECL = re.compile(
    r"(?:public\s+(?:abstract\s+)?)?class\s+(?P<name>\w+)"
    r"(?:\s+extends\s+(?P<extends>[\w.]+))?"
)

# Package declaration
_RE_PACKAGE = re.compile(r"^package\s+([\w.]+)\s*;", re.MULTILINE)

# String constant definition:  public static final String NAME = "value";
_RE_STRING_CONSTANT = re.compile(
    r'(?:public\s+|private\s+|protected\s+)?'
    r'(?:static\s+)?(?:final\s+)?'
    r'static\s+final\s+String\s+'
    r'(?P<name>\w+)\s*=\s*"(?P<value>[^"]*)"'
)
# A simpler broader catch for 'static final String X = "Y"' order variations:
_RE_STRING_CONSTANT_ALT = re.compile(
    r'\bstatic\s+(?:final\s+)?String\s+(?P<name>\w+)\s*=\s*"(?P<value>[^"]*)"'
)
_RE_FINAL_STRING_CONSTANT = re.compile(
    r'\bfinal\s+static\s+String\s+(?P<name>\w+)\s*=\s*"(?P<value>[^"]*)"'
)

# @Column annotation
_RE_COLUMN = re.compile(
    r"@Column\s*\((?P<args>[^)]*)\)",
    re.DOTALL,
)

# @Id annotation
_RE_ID = re.compile(r"@Id\b")

# @Lob annotation
_RE_LOB = re.compile(r"@Lob\b")

# @Embedded annotation
_RE_EMBEDDED = re.compile(r"@Embedded\b")

# @AttributeOverride (single)
_RE_ATTR_OVERRIDE = re.compile(
    r"@AttributeOverride\s*\(\s*"
    r'name\s*=\s*"(?P<attr_name>[^"]+)"\s*,\s*'
    r"column\s*=\s*@Column\s*\((?P<col_args>[^)]*)\)"
    r"\s*\)",
    re.DOTALL,
)

# @AttributeOverrides (plural — contains multiple @AttributeOverride)
_RE_ATTR_OVERRIDES = re.compile(
    r"@AttributeOverrides\s*\(\s*\{(?P<body>[^}]*)\}\s*\)",
    re.DOTALL,
)

# @SequenceGenerator annotation
_RE_SEQUENCE_GEN = re.compile(
    r"@SequenceGenerator\s*\((?P<args>[^)]*)\)",
    re.DOTALL,
)

# LazySetProvider / LazyCollectionProvider field declaration
_RE_LAZY_PROVIDER = re.compile(
    r"(?:private|protected)\s+(?:final\s+)?"
    r"(?P<kind>LazySetProvider|LazyCollectionProvider)"
    r"<(?P<target>\w+)>\s+(?P<field>\w+)\s*="
    r"\s*new\s+(?:LazySetProvider|LazyCollectionProvider)<>\s*\("
    r"\s*this\s*,\s*(?P<fk_arg>[^,]+)\s*,\s*(?P<coll_arg>[^,)]+)",
    re.DOTALL,
)

# Field declaration (to capture type + name after annotations)
_RE_FIELD_DECL = re.compile(
    r"(?:private|protected|public)\s+(?:final\s+)?"
    r"(?P<type>[\w<>.,\s\[\]?]+?)\s+(?P<name>\w+)\s*[;=]"
)

# @MappedSuperclass
_RE_MAPPED_SUPERCLASS = re.compile(r"@MappedSuperclass\b")

# Annotation name parameter:  name = "value" or name = Const.FIELD
_RE_NAME_PARAM = re.compile(
    r'name\s*=\s*(?:"(?P<literal>[^"]*)"|(?P<ref>[\w.]+))'
)
# schema parameter
_RE_SCHEMA_PARAM = re.compile(
    r'schema\s*=\s*(?:"(?P<literal>[^"]*)"|(?P<ref>[\w.]+))'
)
# sequenceName parameter (may use + concatenation)
_RE_SEQ_NAME_PARAM = re.compile(
    r"sequenceName\s*=\s*(?P<expr>[^,)]+)"
)
# initialValue and allocationSize
_RE_INITIAL_VALUE = re.compile(r"initialValue\s*=\s*(?P<val>\d+)")
_RE_ALLOC_SIZE = re.compile(r"allocationSize\s*=\s*(?P<val>\d+)")

# nullable / updatable / insertable boolean attrs in @Column
_RE_NULLABLE = re.compile(r"nullable\s*=\s*(?P<val>true|false)", re.IGNORECASE)
_RE_UPDATABLE = re.compile(r"updatable\s*=\s*(?P<val>true|false)", re.IGNORECASE)
_RE_INSERTABLE = re.compile(r"insertable\s*=\s*(?P<val>true|false)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _extract_column_name(args: str) -> tuple[str | None, bool]:
    """Extract the column name from @Column(...) args text.

    Returns (column_name, is_literal).  is_literal is True when the name was
    a quoted string in the annotation (i.e. already resolved).
    """
    m = _RE_NAME_PARAM.search(args)
    if m:
        if m.group("literal") is not None:
            return m.group("literal"), True
        return m.group("ref"), False
    return None, True


def _extract_column_attrs(args: str) -> dict[str, Any]:
    """Extract nullable/updatable/insertable from @Column args."""
    attrs: dict[str, Any] = {}
    m = _RE_NULLABLE.search(args)
    if m:
        attrs["nullable"] = _parse_bool(m.group("val"))
    m = _RE_UPDATABLE.search(args)
    if m:
        attrs["updatable"] = _parse_bool(m.group("val"))
    m = _RE_INSERTABLE.search(args)
    if m:
        attrs["insertable"] = _parse_bool(m.group("val"))
    return attrs


def _find_line_number(content: str, pos: int) -> int:
    """Return 1-based line number for a character position."""
    return content[:pos].count("\n") + 1


def _resolve_constant(
    ref: str,
    class_name: str,
    constants: dict[str, str],
) -> tuple[str | None, bool]:
    """Resolve a constant reference to a literal string value.

    Returns (resolved_value, was_resolved).
    """
    ref = ref.strip()

    # Already a string literal
    if ref.startswith('"') and ref.endswith('"'):
        return ref[1:-1], True

    # Well-known framework constants
    if ref in _WELL_KNOWN_CONSTANTS:
        return _WELL_KNOWN_CONSTANTS[ref], True

    # Fully-qualified: ClassName.FIELD
    if "." in ref:
        parts = ref.split(".", 1)
        ref_class = parts[0]
        ref_field = parts[1]
        # Same class?
        if ref_class == class_name:
            if ref_field in constants:
                return constants[ref_field], True
        # Well-known?
        if ref in _WELL_KNOWN_CONSTANTS:
            return _WELL_KNOWN_CONSTANTS[ref], True
        # Check local constants (unqualified)
        if ref_field in constants:
            return constants[ref_field], True
        return None, False

    # Unqualified local constant
    if ref in constants:
        return constants[ref], True

    return None, False


def _resolve_concat_expr(
    expr: str,
    class_name: str,
    constants: dict[str, str],
) -> tuple[str | None, bool]:
    """Resolve a Java string concatenation expression like A + B."""
    expr = expr.strip()
    if "+" not in expr:
        return _resolve_constant(expr, class_name, constants)

    parts = [p.strip() for p in expr.split("+")]
    resolved_parts: list[str] = []
    all_resolved = True
    for part in parts:
        val, ok = _resolve_constant(part, class_name, constants)
        if ok and val is not None:
            resolved_parts.append(val)
        else:
            all_resolved = False
            break

    if all_resolved:
        return "".join(resolved_parts), True
    return None, False


def _is_test_path(path: str) -> bool:
    """Determine if a file path indicates a test source."""
    normalized = path.replace("\\", "/")
    return "/test/" in normalized or "/tests/" in normalized


def _make_evidence(
    path: str,
    line: int,
    end_line: int | None = None,
) -> EvidenceSource:
    return EvidenceSource(
        kind="jpa_annotation",
        path=path,
        start_line=line,
        end_line=end_line or line,
    )


# ---------------------------------------------------------------------------
# Per-file extractor
# ---------------------------------------------------------------------------


def _extract_constants(content: str) -> dict[str, str]:
    """Extract all `static final String NAME = "value"` constants."""
    constants: dict[str, str] = {}
    for m in _RE_STRING_CONSTANT.finditer(content):
        constants[m.group("name")] = m.group("value")
    for m in _RE_STRING_CONSTANT_ALT.finditer(content):
        name = m.group("name")
        if name not in constants:
            constants[name] = m.group("value")
    for m in _RE_FINAL_STRING_CONSTANT.finditer(content):
        name = m.group("name")
        if name not in constants:
            constants[name] = m.group("value")
    return constants


def _extract_entity_from_file(
    content: str,
    rel_path: str,
) -> tuple[JpaEntity | None, list[UnresolvedConstant]]:
    """Extract a JPA entity from a single Java file's content.

    Returns (entity_or_None, unresolved_constants).
    """
    unresolved: list[UnresolvedConstant] = []

    # Must have @Entity
    entity_match = _RE_ENTITY.search(content)
    if entity_match is None:
        return None, unresolved

    entity_line = _find_line_number(content, entity_match.start())

    # Check for @MappedSuperclass (not an entity table)
    is_mapped_superclass = _RE_MAPPED_SUPERCLASS.search(content) is not None

    # Package
    pkg_match = _RE_PACKAGE.search(content)
    package_name = pkg_match.group(1) if pkg_match else ""

    # Class declaration
    class_match = _RE_CLASS_DECL.search(content)
    if class_match is None:
        return None, unresolved

    class_name = class_match.group("name")
    extends_class = class_match.group("extends")
    qualified_name = f"{package_name}.{class_name}" if package_name else class_name

    # Constants
    constants = _extract_constants(content)

    # Inheritance
    inheritance_match = _RE_INHERITANCE.search(content)
    has_inheritance = inheritance_match is not None
    inheritance_strategy = (
        inheritance_match.group("strat") if inheritance_match else None
    )

    # @Table
    table_name: str | None = None
    table_resolved = False
    schema_name: str | None = None

    table_match = _RE_TABLE.search(content)
    if table_match:
        table_args = table_match.group("args")
        name_m = _RE_NAME_PARAM.search(table_args)
        if name_m:
            if name_m.group("literal") is not None:
                table_name = name_m.group("literal")
                table_resolved = True
            else:
                ref = name_m.group("ref")
                val, ok = _resolve_constant(ref, class_name, constants)
                if ok:
                    table_name = val
                    table_resolved = True
                else:
                    table_name = ref
                    table_resolved = False
                    unresolved.append(UnresolvedConstant(
                        reference=ref,
                        context="@Table name",
                        source_path=rel_path,
                        line=_find_line_number(content, table_match.start()),
                    ))

        schema_m = _RE_SCHEMA_PARAM.search(table_args)
        if schema_m:
            if schema_m.group("literal") is not None:
                schema_name = schema_m.group("literal") or None
            else:
                ref = schema_m.group("ref")
                val, ok = _resolve_constant(ref, class_name, constants)
                if ok:
                    schema_name = val or None  # empty string -> None
                else:
                    schema_name = ref
                    unresolved.append(UnresolvedConstant(
                        reference=ref,
                        context="@Table schema",
                        source_path=rel_path,
                        line=_find_line_number(content, table_match.start()),
                    ))
    elif not is_mapped_superclass:
        # @Entity without @Table: JPA defaults table name to class name
        table_name = class_name
        table_resolved = True

    is_test = _is_test_path(rel_path)

    entity = JpaEntity(
        class_name=class_name,
        qualified_name=qualified_name,
        table_name=table_name,
        table_name_resolved=table_resolved,
        schema_name=schema_name,
        extends_class=extends_class,
        is_test=is_test,
        source_path=rel_path,
        entity_line=entity_line,
        constants=constants,
        has_inheritance=has_inheritance,
        inheritance_strategy=inheritance_strategy,
    )

    # ------------------------------------------------------------------
    # @SequenceGenerator
    # ------------------------------------------------------------------
    for sg_match in _RE_SEQUENCE_GEN.finditer(content):
        sg_args = sg_match.group("args")
        sg_line = _find_line_number(content, sg_match.start())

        # generator name
        gen_name_m = _RE_NAME_PARAM.search(sg_args)
        gen_name = ""
        if gen_name_m:
            if gen_name_m.group("literal") is not None:
                gen_name = gen_name_m.group("literal")
            else:
                ref = gen_name_m.group("ref")
                val, ok = _resolve_constant(ref, class_name, constants)
                gen_name = val if ok and val is not None else ref

        # sequenceName (may be a + concatenation)
        seq_name: str | None = None
        seq_resolved = False
        seq_m = _RE_SEQ_NAME_PARAM.search(sg_args)
        if seq_m:
            expr = seq_m.group("expr").strip()
            val, ok = _resolve_concat_expr(expr, class_name, constants)
            if ok and val is not None:
                seq_name = val
                seq_resolved = True
            else:
                seq_name = expr
                seq_resolved = False
                unresolved.append(UnresolvedConstant(
                    reference=expr,
                    context="@SequenceGenerator sequenceName",
                    source_path=rel_path,
                    line=sg_line,
                ))

        iv_m = _RE_INITIAL_VALUE.search(sg_args)
        initial_value = int(iv_m.group("val")) if iv_m else 1
        as_m = _RE_ALLOC_SIZE.search(sg_args)
        allocation_size = int(as_m.group("val")) if as_m else 1

        entity.sequences.append(SequenceInfo(
            generator_name=gen_name,
            sequence_name=seq_name or "",
            sequence_name_resolved=seq_resolved,
            initial_value=initial_value,
            allocation_size=allocation_size,
            source=_make_evidence(rel_path, sg_line),
        ))

    # ------------------------------------------------------------------
    # Field-level annotations: walk through lines to accumulate context
    # ------------------------------------------------------------------
    lines = content.split("\n")
    pending_annotations: dict[str, Any] = {
        "id": False,
        "lob": False,
        "column": None,          # (column_name, attrs, line)
        "embedded": False,
        "overrides": [],          # [(attr_name, col_name, attrs, line), ...]
    }
    # Lines consumed by multi-line annotation blocks (skip on re-encounter)
    skip_lines: set[int] = set()

    def _reset_pending() -> None:
        pending_annotations["id"] = False
        pending_annotations["lob"] = False
        pending_annotations["column"] = None
        pending_annotations["embedded"] = False
        pending_annotations["overrides"] = []

    for line_idx, line in enumerate(lines):
        line_num = line_idx + 1
        stripped = line.strip()

        if line_idx in skip_lines:
            continue

        # Detect @Id
        if _RE_ID.search(stripped):
            pending_annotations["id"] = True
            continue

        # Detect @Lob
        if _RE_LOB.search(stripped):
            pending_annotations["lob"] = True
            continue

        # Detect @Embedded
        if _RE_EMBEDDED.search(stripped):
            pending_annotations["embedded"] = True
            continue

        # Detect @AttributeOverrides (plural)
        ao_plural_m = _RE_ATTR_OVERRIDES.search(stripped)
        consumed_end = line_idx
        if ao_plural_m is None and "@AttributeOverrides" in stripped:
            # Multi-line: accumulate forward
            combined = stripped
            for fwd in range(line_idx + 1, min(line_idx + 20, len(lines))):
                combined += " " + lines[fwd].strip()
                ao_plural_m = _RE_ATTR_OVERRIDES.search(combined)
                if ao_plural_m:
                    consumed_end = fwd
                    break
        if ao_plural_m:
            # Mark consumed lines so individual @AttributeOverride lines are skipped
            for skip_idx in range(line_idx, consumed_end + 1):
                skip_lines.add(skip_idx)
            body = ao_plural_m.group("body")
            for single_m in _RE_ATTR_OVERRIDE.finditer(body):
                attr_name = single_m.group("attr_name")
                col_args = single_m.group("col_args")
                col_name, _ = _extract_column_name(col_args)
                col_attrs = _extract_column_attrs(col_args)
                if col_name:
                    pending_annotations["overrides"].append(
                        (attr_name, col_name, col_attrs, line_num)
                    )
            continue

        # Detect single @AttributeOverride
        ao_single_m = _RE_ATTR_OVERRIDE.search(stripped)
        if ao_single_m is None and "@AttributeOverride" in stripped and "@AttributeOverrides" not in stripped:
            # Multi-line: accumulate forward
            combined = stripped
            for fwd in range(line_idx + 1, min(line_idx + 10, len(lines))):
                combined += " " + lines[fwd].strip()
                ao_single_m = _RE_ATTR_OVERRIDE.search(combined)
                if ao_single_m:
                    # Mark consumed forward lines
                    for skip_idx in range(line_idx + 1, fwd + 1):
                        skip_lines.add(skip_idx)
                    break
        if ao_single_m:
            attr_name = ao_single_m.group("attr_name")
            col_args = ao_single_m.group("col_args")
            col_name, _ = _extract_column_name(col_args)
            col_attrs = _extract_column_attrs(col_args)
            if col_name:
                pending_annotations["overrides"].append(
                    (attr_name, col_name, col_attrs, line_num)
                )
            continue

        # Detect @Column (not inside @AttributeOverride)
        col_m = _RE_COLUMN.search(stripped)
        if col_m is None and "@Column" in stripped:
            # Multi-line @Column
            combined = stripped
            for fwd in range(line_idx + 1, min(line_idx + 5, len(lines))):
                combined += " " + lines[fwd].strip()
                col_m = _RE_COLUMN.search(combined)
                if col_m:
                    break
        if col_m and "@AttributeOverride" not in stripped:
            col_args = col_m.group("args")
            col_name, col_is_literal = _extract_column_name(col_args)
            col_attrs = _extract_column_attrs(col_args)
            if col_name:
                # Resolve constant references in column name (only for non-literal refs)
                if not col_is_literal:
                    val, ok = _resolve_constant(col_name, class_name, constants)
                    if ok and val is not None:
                        col_name = val
                    else:
                        unresolved.append(UnresolvedConstant(
                            reference=col_name,
                            context="@Column name",
                            source_path=rel_path,
                            line=line_num,
                        ))
                pending_annotations["column"] = (col_name, col_attrs, line_num)
            continue

        # Detect LazySetProvider / LazyCollectionProvider
        lazy_m = _RE_LAZY_PROVIDER.search(stripped)
        if lazy_m is None and ("LazySetProvider" in stripped or "LazyCollectionProvider" in stripped):
            # Multi-line
            combined = stripped
            for fwd in range(line_idx + 1, min(line_idx + 10, len(lines))):
                combined += " " + lines[fwd].strip()
                lazy_m = _RE_LAZY_PROVIDER.search(combined)
                if lazy_m:
                    break
        if lazy_m:
            provider_kind = lazy_m.group("kind")
            target_type = lazy_m.group("target")
            field_name = lazy_m.group("field")
            fk_arg = lazy_m.group("fk_arg").strip()
            coll_arg = lazy_m.group("coll_arg").strip()

            # Resolve FK field argument
            fk_resolved = False
            if fk_arg.startswith('"') and fk_arg.endswith('"'):
                fk_field = fk_arg[1:-1]
                fk_resolved = True
            else:
                val, ok = _resolve_constant(fk_arg, class_name, constants)
                if ok and val is not None:
                    fk_field = val
                    fk_resolved = True
                else:
                    fk_field = fk_arg
                    fk_resolved = False
                    unresolved.append(UnresolvedConstant(
                        reference=fk_arg,
                        context="LazyProvider foreign key",
                        source_path=rel_path,
                        line=line_num,
                    ))

            # Resolve collection name argument
            if coll_arg.startswith('"') and coll_arg.endswith('"'):
                coll_name = coll_arg[1:-1]
            else:
                val, ok = _resolve_constant(coll_arg, class_name, constants)
                coll_name = val if ok and val is not None else coll_arg

            entity.relationships.append(LazyRelationship(
                java_field_name=field_name,
                target_type=target_type,
                foreign_key_field=fk_field,
                foreign_key_resolved=fk_resolved,
                collection_name=coll_name,
                provider_kind=provider_kind,
                source=_make_evidence(rel_path, line_num),
            ))
            _reset_pending()
            continue

        # Detect field declaration -> consume pending annotations
        field_m = _RE_FIELD_DECL.search(stripped)
        if field_m:
            java_type = field_m.group("type").strip()
            java_field = field_m.group("name")

            # If we have pending @Embedded + overrides
            if pending_annotations["embedded"] and pending_annotations["overrides"]:
                for attr_name, col_name, col_attrs, ao_line in pending_annotations["overrides"]:
                    entity.embedded_overrides.append(EmbeddedOverride(
                        java_field_name=java_field,
                        embedded_type=java_type,
                        attribute_name=attr_name,
                        column_name=col_name,
                        nullable=col_attrs.get("nullable", True),
                        updatable=col_attrs.get("updatable", True),
                        insertable=col_attrs.get("insertable", True),
                        source=_make_evidence(rel_path, ao_line),
                    ))
                _reset_pending()
                continue

            # If we have a pending @Column
            if pending_annotations["column"] is not None:
                col_name, col_attrs, col_line = pending_annotations["column"]
                is_id = pending_annotations["id"]
                is_lob = pending_annotations["lob"]

                cm = ColumnMapping(
                    java_field_name=java_field,
                    column_name=col_name,
                    java_type=java_type,
                    is_id=is_id,
                    is_lob=is_lob,
                    nullable=col_attrs.get("nullable", True),
                    updatable=col_attrs.get("updatable", True),
                    insertable=col_attrs.get("insertable", True),
                    source=_make_evidence(rel_path, col_line),
                )
                entity.columns.append(cm)
                if is_id:
                    entity.id_columns.append(col_name)

                _reset_pending()
                continue

            # If we have @Embedded but without overrides (bare @Embedded)
            if pending_annotations["embedded"]:
                # Still record the embedded field, no column overrides
                _reset_pending()
                continue

            # If we have a standalone @Id without @Column
            if pending_annotations["id"]:
                _reset_pending()
                continue

            # Reset on any field declaration
            _reset_pending()
            continue

        # Don't accumulate annotations across method boundaries / braces
        if stripped.startswith("public ") or stripped.startswith("private ") or stripped.startswith("protected "):
            if "(" in stripped and ")" in stripped:
                _reset_pending()

    return entity, unresolved


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_jpa_entities(
    root_path: str | Path,
    *,
    exclude_patterns: tuple[str, ...] = (
        "/target/",
        "/build/",
        "/node_modules/",
        "/.git/",
    ),
) -> JpaExtractionResult:
    """Scan a directory tree for Java JPA entities and extract mappings.

    Args:
        root_path: Root directory to scan recursively.
        exclude_patterns: Path substrings to skip.

    Returns:
        JpaExtractionResult with all discovered entities, relationships,
        unresolved constants, and statistics.
    """
    root = Path(root_path).resolve()
    if not root.is_dir():
        raise ValueError(f"root_path is not a directory: {root}")

    result = JpaExtractionResult()

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune excluded directories
        dirnames[:] = [
            d for d in dirnames
            if not any(
                excl.strip("/") == d
                for excl in exclude_patterns
            )
        ]

        for fname in filenames:
            if not fname.endswith(".java"):
                continue

            fpath = Path(dirpath) / fname
            rel_path = str(fpath.relative_to(root))
            norm_path = rel_path.replace("\\", "/")

            # Skip excluded paths
            if any(excl in f"/{norm_path}" for excl in exclude_patterns):
                continue

            result.files_scanned += 1

            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                result.errors.append(f"read error {rel_path}: {exc}")
                continue

            # Quick check: skip files without @Entity
            if "@Entity" not in content:
                continue

            try:
                entity, unresolved = _extract_entity_from_file(content, rel_path)
            except Exception as exc:
                logger.warning("extraction error in %s: %s", rel_path, exc)
                result.errors.append(f"parse error {rel_path}: {exc}")
                continue

            if entity is not None:
                result.entities.append(entity)
                result.files_with_entities += 1

            result.unresolved_constants.extend(unresolved)

    # Sort entities by qualified name for deterministic output
    result.entities.sort(key=lambda e: e.qualified_name)

    logger.info(
        "JPA extraction complete: %d entities from %d/%d files, "
        "%d unresolved constants, %d errors",
        len(result.entities),
        result.files_with_entities,
        result.files_scanned,
        len(result.unresolved_constants),
        len(result.errors),
    )

    return result


def extract_jpa_entities_from_content(
    content: str,
    rel_path: str = "<inline>",
) -> tuple[JpaEntity | None, list[UnresolvedConstant]]:
    """Extract a JPA entity from a single Java file's content string.

    Useful for testing or single-file analysis.
    """
    if "@Entity" not in content:
        return None, []
    return _extract_entity_from_file(content, rel_path)
