"""Source-free evidence references shared by canonical graph consumers.

The canonical graph retains producer evidence strings for traceability.  Public
feature projections expose only validated, one-way references so repository
paths or arbitrary producer text cannot leak through an API response.
"""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
from pathlib import PurePosixPath
import re
import unicodedata

from moughorai.platform.safety import contains_absolute_path_text

from .models import KnowledgeRelation


MAXIMUM_EDGE_EVIDENCE_REFS = 64
_SYMBOL_EVIDENCE = re.compile(
    r"global_symbol\.metadata:(?:imports|inherits|bases|overrides):"
    r"[A-Za-z_$][A-Za-z0-9_.$#()*\[\],?<>+-]{0,255}\Z"
)
_WORKSPACE_DEPENDENCY_EVIDENCE = re.compile(
    r"workspace\.projects:[A-Za-z0-9_.@%+-]{1,128}:dependencies:"
    r"[A-Za-z0-9_.@%+-]{1,128}\Z"
)
_SEMANTIC_GRAPH_EVIDENCE = re.compile(
    r"semantic_graph:(?:imports|member_of|extends|implements|inheritance|"
    r"composition|calls|overrides|dependencies|depends_on|ownership)\Z"
)
_DEPENDENCY_EVIDENCE = re.compile(
    r"declared_dependency:[A-Za-z0-9_.@%+~:/-]{1,512}\Z"
)
_EVIDENCE_REFERENCE_ID = re.compile(
    r"(?:evidence|report-item|repository-report):[0-9a-f]{64}\Z"
)
_FIXED_EDGE_EVIDENCE = frozenset({
    "global_symbol.owner_id",
    "workspace.root",
    "workspace.projects",
    "repository_summary.projects",
    "repository_summary.module_hierarchy",
    "repository_summary.build_systems",
    "repository_summary.frameworks",
    "semantic_graph.project_id",
    "metadata:domain",
    "metadata:capability",
    "calls",
    "moughorai.call_graph.v1:calls",
    "extends",
    "implements",
    "uses",
    "imports",
    "annotated_by",
})
_FRAMEWORK_SCOPES = frozenset({
    "project-local",
    "test-only",
    "test-or-sample",
    "documentation",
    "build-tooling",
    "optional",
    "optional-integration",
})


def is_structured_edge_evidence(value: object) -> bool:
    """Return whether a canonical edge reference is structured and portable."""

    text = unicodedata.normalize("NFKC", str(value).strip())
    return _is_structured_edge_evidence_text(text)


def safe_edge_evidence_refs(values: Iterable[object]) -> tuple[str, ...]:
    """Project accepted evidence into bounded, traceable, non-reversible IDs."""

    accepted: set[str] = set()
    for value in values:
        text = unicodedata.normalize("NFKC", str(value).strip())
        if not text or not _is_structured_edge_evidence_text(text):
            continue
        reference = _edge_evidence_reference_id(text)
        if reference in accepted:
            continue
        if len(accepted) < MAXIMUM_EDGE_EVIDENCE_REFS:
            accepted.add(reference)
            continue
        largest = max(accepted)
        if reference < largest:
            accepted.remove(largest)
            accepted.add(reference)
    return tuple(sorted(accepted))


def has_authoritative_edge_evidence(
    relation: KnowledgeRelation,
    values: Iterable[object],
) -> bool:
    """Return whether evidence establishes one canonical relationship.

    The canonical graph models more relationships than the normal production
    pipeline can currently prove.  Consumers must therefore bind an edge to a
    known structured producer before treating it as semantic evidence.  This
    shared predicate centralizes that producer boundary without assigning any
    feature-specific score, propagation direction, or interpretation.
    """

    evidence = tuple(
        text
        for item in values
        if (
            text := unicodedata.normalize("NFKC", str(item).strip())
        )
        and _is_structured_edge_evidence_text(text)
    )
    if not evidence:
        return False
    if relation is KnowledgeRelation.CALLS:
        return "moughorai.call_graph.v1:calls" in evidence
    if relation is KnowledgeRelation.IMPORTS:
        return any(
            item == "imports"
            or item.startswith("global_symbol.metadata:imports:")
            for item in evidence
        )
    if relation is KnowledgeRelation.INHERITS:
        return any(
            item in {"extends", "implements"}
            or item.startswith("global_symbol.metadata:inherits:")
            or item.startswith("global_symbol.metadata:bases:")
            for item in evidence
        )
    if relation is KnowledgeRelation.OVERRIDES:
        return any(
            item.startswith("global_symbol.metadata:overrides:")
            for item in evidence
        )
    if relation is KnowledgeRelation.DEPENDS_ON:
        return any(
            item.startswith("workspace.projects:")
            or item.startswith("declared_dependency:")
            or item == "repository_summary.frameworks"
            or item.partition(":")[0] in _FRAMEWORK_SCOPES
            or item in {"calls", "uses", "imports", "extends", "implements"}
            for item in evidence
        )
    if relation is KnowledgeRelation.MEMBER_OF:
        return "global_symbol.owner_id" in evidence
    if relation is KnowledgeRelation.OWNS:
        return any(
            item in {
                "workspace.root",
                "workspace.projects",
                "repository_summary.projects",
                "repository_summary.module_hierarchy",
                "semantic_graph.project_id",
                "global_symbol.owner_id",
            }
            for item in evidence
        )
    return False


def _is_structured_edge_evidence_text(text: str) -> bool:
    if (
        not text
        or len(text) > 512
        or any(character.isspace() or ord(character) < 32 for character in text)
        or "://" in text
    ):
        return False
    if text in _FIXED_EDGE_EVIDENCE:
        return True
    if contains_absolute_path_text(text):
        return False
    if (
        _SYMBOL_EVIDENCE.fullmatch(text)
        or _WORKSPACE_DEPENDENCY_EVIDENCE.fullmatch(text)
        or _SEMANTIC_GRAPH_EVIDENCE.fullmatch(text)
        or _EVIDENCE_REFERENCE_ID.fullmatch(text)
    ):
        return True
    if text.startswith("declared_dependency.source:"):
        raw_path = text.removeprefix("declared_dependency.source:")
        path = PurePosixPath(raw_path)
        return bool(
            raw_path
            and "\\" not in raw_path
            and not path.is_absolute()
            and all(part not in {"", ".", ".."} for part in path.parts)
            and re.fullmatch(r"[A-Za-z0-9_.@%+~#=/,-]+", raw_path)
        )
    if text.startswith("declared_dependency:"):
        payload = text.removeprefix("declared_dependency:")
        return bool(
            _DEPENDENCY_EVIDENCE.fullmatch(text)
            and len(payload.split(":")) >= 4
            and ".." not in payload
        )
    scope, separator, reference = text.partition(":")
    return bool(
        separator
        and scope in _FRAMEWORK_SCOPES
        and reference
        and len(reference) <= 384
        and re.fullmatch(r"[A-Za-z0-9_.@%+~#=/,:()-]+", reference)
        and ".." not in reference
    )


def _edge_evidence_reference_id(value: str) -> str:
    return "semantic_graph.edge_ref:" + hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()
