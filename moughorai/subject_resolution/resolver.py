from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
import hashlib
from pathlib import PurePosixPath
import re
from types import MappingProxyType
import unicodedata

from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.repository_report.safety import contains_absolute_path_text
from moughorai.semantic_snapshot import AtlasSemanticSnapshot

from .models import (
    PathCandidateEvidence,
    PathSubjectCandidates,
    ResolutionStatus,
    SubjectCandidate,
    SubjectMatchBasis,
    SubjectQuery,
    SubjectResolution,
    _relative_path,
)


class CanonicalSubjectResolver:
    """Resolve structured subjects against one indexed PR129 graph."""

    DEFAULT_MAXIMUM_CANDIDATES = 12
    DEFAULT_MAXIMUM_PATH_CANDIDATES = 128

    def __init__(
        self,
        graph: KnowledgeGraph | None,
        *,
        symbols: Iterable[Mapping[str, object]] = (),
        graph_digest: str = "unavailable",
        maximum_candidates: int = DEFAULT_MAXIMUM_CANDIDATES,
        limitations: Iterable[str] = (),
    ) -> None:
        if maximum_candidates < 1:
            raise ValueError("maximum subject candidates must be positive")
        self._graph = graph
        self.graph_digest = graph_digest or "unavailable"
        self.maximum_candidates = maximum_candidates
        self.limitations = tuple(sorted({str(item) for item in limitations if str(item)}))
        self._by_id: Mapping[str, KnowledgeNode] = MappingProxyType({})
        self._by_public_id: Mapping[str, tuple[KnowledgeNode, ...]] = MappingProxyType({})
        self._by_qualified: Mapping[str, tuple[KnowledgeNode, ...]] = MappingProxyType({})
        self._by_normalized: Mapping[str, tuple[KnowledgeNode, ...]] = MappingProxyType({})
        self._simple_names: Mapping[str, str] = MappingProxyType({})
        self._paths: Mapping[str, tuple[str, ...]] = MappingProxyType({})
        self._path_sources: Mapping[
            str, Mapping[str, tuple[str, ...]]
        ] = MappingProxyType({})
        self._by_path: Mapping[str, tuple[KnowledgeNode, ...]] = MappingProxyType({})
        self._projects_by_root: Mapping[str, tuple[KnowledgeNode, ...]] = (
            MappingProxyType({})
        )
        self._project_scopes: Mapping[str, tuple[str, ...]] = MappingProxyType({})
        self._available_kinds: frozenset[KnowledgeKind] = frozenset()
        if graph is not None:
            self._build_indexes(tuple(symbols))

    @property
    def graph(self) -> KnowledgeGraph | None:
        return self._graph

    def has_kind(self, kind: KnowledgeKind) -> bool:
        """Return whether the already-indexed graph contains a subject kind."""

        return kind in self._available_kinds

    def candidate_for_graph_id(
        self,
        node_id: str,
        *,
        match_basis: SubjectMatchBasis = SubjectMatchBasis.CANONICAL_ID,
    ) -> SubjectCandidate | None:
        """Project one internal graph identity into its source-free public form."""

        node = self._by_id.get(node_id)
        return self._candidate(node, match_basis) if node is not None else None

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AtlasSemanticSnapshot,
        *,
        maximum_candidates: int = DEFAULT_MAXIMUM_CANDIDATES,
    ) -> CanonicalSubjectResolver:
        context = snapshot.semantic_context
        raw_graph = context.get("semantic_graph")
        if not isinstance(raw_graph, Mapping):
            return cls(
                None,
                maximum_candidates=maximum_candidates,
                limitations=("Canonical PR129 graph is unavailable in this snapshot.",),
            )
        try:
            schema = int(raw_graph["schema_version"])
        except KeyError:
            return cls(
                None,
                maximum_candidates=maximum_candidates,
                limitations=("Canonical graph schema is unavailable in this snapshot.",),
            )
        except (TypeError, ValueError):
            schema = -1
        if schema != 1:
            return cls(
                None,
                maximum_candidates=maximum_candidates,
                limitations=(f"Canonical graph schema {schema} is unsupported.",),
            )
        raw_nodes = _strict_mapping_items(raw_graph.get("nodes"))
        if raw_nodes is None:
            return cls(
                None,
                maximum_candidates=maximum_candidates,
                limitations=("Canonical graph subject nodes are malformed.",),
            )
        node_ids = tuple(str(item.get("id", "")) for item in raw_nodes)
        if not raw_nodes or any(not item for item in node_ids):
            return cls(
                None,
                maximum_candidates=maximum_candidates,
                limitations=("Canonical graph contains no usable subject nodes.",),
            )
        if len(set(node_ids)) != len(node_ids):
            return cls(
                None,
                maximum_candidates=maximum_candidates,
                limitations=("Canonical graph contains duplicate subject identities.",),
            )
        node_id_set = set(node_ids)
        raw_edges = _strict_mapping_items(raw_graph.get("edges", ()))
        if raw_edges is None:
            return cls(
                None,
                maximum_candidates=maximum_candidates,
                limitations=("Canonical graph relationships are malformed.",),
            )
        dangling_count = sum(
            1
            for item in raw_edges
            if str(item.get("source", "")) not in node_id_set
            or str(item.get("target", "")) not in node_id_set
        )
        normalized_edges = []
        for item in raw_edges:
            source = str(item.get("source", ""))
            target = str(item.get("target", ""))
            if source not in node_id_set or target not in node_id_set:
                continue
            raw_evidence = item.get("evidence", ())
            evidence = (
                sorted({str(value) for value in raw_evidence})
                if isinstance(raw_evidence, Sequence)
                and not isinstance(raw_evidence, (str, bytes, bytearray))
                else []
            )
            normalized_edges.append({
                "source": source,
                "target": target,
                "kind": str(item.get("kind", "related_to")),
                "evidence": evidence,
            })
        try:
            graph = KnowledgeGraph.from_dict({
                "schema_version": 1,
                "nodes": raw_nodes,
                "edges": normalized_edges,
            })
            graph_digest = graph.stable_digest()
        except (TypeError, ValueError) as exc:
            return cls(
                None,
                maximum_candidates=maximum_candidates,
                limitations=(f"Canonical graph could not be restored: {type(exc).__name__}.",),
            )
        limitations = ()
        if dangling_count:
            limitations = (
                f"Ignored {dangling_count} dangling canonical graph relationship(s).",
            )
        symbols = _mapping_items(context.get("symbols"))
        return cls(
            graph,
            symbols=symbols,
            graph_digest=graph_digest,
            maximum_candidates=maximum_candidates,
            limitations=limitations,
        )

    @classmethod
    def from_graph(
        cls,
        graph: KnowledgeGraph,
        *,
        symbols: Iterable[Mapping[str, object]] = (),
        maximum_candidates: int = DEFAULT_MAXIMUM_CANDIDATES,
    ) -> CanonicalSubjectResolver:
        return cls(
            graph,
            symbols=symbols,
            graph_digest=graph.stable_digest(),
            maximum_candidates=maximum_candidates,
        )

    def resolve(self, query: SubjectQuery) -> SubjectResolution:
        if not isinstance(query, SubjectQuery):
            raise TypeError("subject query must be a SubjectQuery")
        if self._graph is None:
            return self._result(query, ResolutionStatus.UNAVAILABLE)

        exact = self._by_id.get(query.identifier)
        if exact is not None:
            if self._matches(exact, query):
                return self._resolved(query, exact, SubjectMatchBasis.CANONICAL_ID)
            return self._result(
                query,
                ResolutionStatus.NOT_FOUND,
                limitations=(
                    "The canonical subject exists but does not satisfy the supplied constraints.",
                ),
            )
        public_matches = tuple(
            node
            for node in self._by_public_id.get(query.identifier, ())
            if self._matches(node, query)
        )
        if len(public_matches) == 1:
            return self._resolved(
                query, public_matches[0], SubjectMatchBasis.CANONICAL_ID,
            )
        if len(public_matches) > 1:
            return self._ambiguous(
                query, public_matches, SubjectMatchBasis.CANONICAL_ID,
            )

        exact_qualified = tuple(
            node
            for node in self._by_qualified.get(query.identifier, ())
            if self._matches(node, query)
        )
        if len(exact_qualified) == 1:
            return self._resolved(
                query, exact_qualified[0], SubjectMatchBasis.QUALIFIED_NAME
            )
        if len(exact_qualified) > 1:
            return self._ambiguous(
                query, exact_qualified, SubjectMatchBasis.QUALIFIED_NAME
            )

        normalized = _normalized_name(query.identifier)
        matches = tuple(
            node
            for node in self._by_normalized.get(normalized, ())
            if self._matches(node, query)
        )
        if len(matches) == 1:
            return self._resolved(query, matches[0], SubjectMatchBasis.NORMALIZED_NAME)
        if len(matches) > 1:
            return self._ambiguous(query, matches, SubjectMatchBasis.NORMALIZED_NAME)
        limitations = (
            (
                "No concrete build target or task matched; detected build systems "
                "are represented separately.",
            )
            if query.kind is KnowledgeKind.BUILD_TARGET
            else ("No canonical subject matched the supplied structured constraints.",)
        )
        return self._result(
            query,
            ResolutionStatus.NOT_FOUND,
            limitations=limitations,
        )

    def candidates_for_path(
        self,
        path: str,
        *,
        maximum_candidates: int = DEFAULT_MAXIMUM_PATH_CANDIDATES,
    ) -> PathSubjectCandidates:
        """Return bounded canonical subjects associated with one exact source path.

        Exact persisted path evidence takes precedence.  When it is absent, the
        deepest containing canonical project is returned as an explicitly marked
        structural fallback.  No basename, suffix, or fuzzy-name inference is used.
        """

        if (
            isinstance(maximum_candidates, bool)
            or not isinstance(maximum_candidates, int)
            or maximum_candidates < 1
        ):
            raise ValueError(
                "maximum path subject candidates must be a positive integer"
            )
        normalized_path = _relative_path(path)
        if self._graph is None:
            return PathSubjectCandidates(
                normalized_path,
                (),
                0,
                0,
                False,
                self.graph_digest,
                (
                    *self.limitations,
                    (
                        "Canonical graph is unavailable; exact path association was "
                        "not performed."
                    ),
                ),
            )

        exact_nodes = self._by_path.get(normalized_path, ())
        project_fallback = False
        limitations: tuple[str, ...] = self.limitations
        nodes = exact_nodes
        if not nodes:
            nodes = self._containing_projects(normalized_path)
            if nodes:
                project_fallback = True
                limitations = (
                    *limitations,
                    (
                        "No exact canonical subject source matched; returned the deepest "
                        "containing project as a structural fallback. Project containment "
                        "does not identify a changed declaration."
                    ),
                )
            else:
                limitations = (
                    *limitations,
                    (
                        "No exact canonical subject source or containing canonical project "
                        "matched this workspace-relative path."
                    ),
                )

        ordered = tuple(sorted(set(nodes), key=self._path_node_sort_key))
        included_nodes = ordered[:maximum_candidates]
        omitted = len(ordered) - len(included_nodes)
        if omitted:
            limitations = (
                *limitations,
                (
                    f"Returned {len(included_nodes)} of {len(ordered)} canonical path "
                    "candidate(s); remaining candidates were deterministically omitted."
                ),
            )
        elif len(ordered) > 1 and not project_fallback:
            limitations = (
                *limitations,
                (
                    "The exact path is associated with multiple canonical subjects; "
                    "path evidence does not identify which declaration a hunk changed."
                ),
            )
        return PathSubjectCandidates(
            normalized_path,
            tuple(
                self._candidate(node, SubjectMatchBasis.PATH)
                for node in included_nodes
            ),
            len(ordered),
            omitted,
            project_fallback,
            self.graph_digest,
            limitations,
            tuple(
                PathCandidateEvidence(
                    self._public_id(node),
                    self._candidate_path_sources(
                        node,
                        normalized_path,
                        project_fallback=project_fallback,
                    ),
                )
                for node in included_nodes
            ),
        )

    def _build_indexes(self, symbols: tuple[Mapping[str, object], ...]) -> None:
        if self._graph is None:
            raise RuntimeError("canonical subject indexes require a graph")
        symbol_metadata: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for item in symbols:
            raw_node_id = item.get("id")
            node_id = str(raw_node_id).strip() if raw_node_id is not None else ""
            if not node_id:
                continue
            raw_name = item.get("name")
            raw_source = item.get("source")
            symbol_metadata[node_id].add((
                str(raw_name).strip() if raw_name is not None else "",
                str(raw_source).strip() if raw_source is not None else "",
            ))
        conflicting_symbol_ids = {
            node_id
            for node_id, values in symbol_metadata.items()
            if len(values) > 1
        }
        by_symbol_id = {
            node_id: {"name": name, "source": source}
            for node_id, values in symbol_metadata.items()
            if len(values) == 1
            for name, source in values
        }
        if conflicting_symbol_ids:
            self.limitations = tuple(sorted({
                *self.limitations,
                (
                    "Ignored conflicting GlobalSymbol metadata for "
                    f"{len(conflicting_symbol_ids)} canonical subject(s)."
                ),
            }))
        simple_names: dict[str, str] = {}
        paths: dict[str, set[str]] = defaultdict(set)
        path_sources: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for node_id, item in by_symbol_id.items():
            name = str(item.get("name", "")).strip()
            if name and not contains_absolute_path_text(name):
                simple_names[node_id] = name
            source = _safe_relative_path(item.get("source"))
            if source:
                paths[node_id].add(source)
                path_sources[node_id][source].add(
                    "global_symbol.metadata:source"
                )

        for node in self._graph.nodes:
            metadata_path = _safe_relative_path(dict(node.metadata).get("path"))
            if metadata_path:
                paths[node.id].add(metadata_path)
                path_sources[node.id][metadata_path].add(
                    "semantic_graph.node.metadata:path"
                )

        project_scopes: dict[str, set[str]] = defaultdict(set)
        for node in self._graph.nodes:
            if node.project_id:
                project_scopes[node.id].add(node.project_id)
            if node.kind is KnowledgeKind.PROJECT:
                project_scopes[node.id].add(node.name)
        for edge in self._graph.edges:
            if edge.relation not in {KnowledgeRelation.DEPENDS_ON, KnowledgeRelation.OWNS}:
                continue
            source = self._graph.get(edge.source)
            if source is None:
                continue
            if source.kind is KnowledgeKind.PROJECT:
                if not contains_absolute_path_text(source.name):
                    project_scopes[edge.target].add(source.name)
            if edge.relation is KnowledgeRelation.DEPENDS_ON:
                for evidence in edge.evidence:
                    prefix = "declared_dependency.source:"
                    if evidence.startswith(prefix):
                        dependency_path = _safe_relative_path(evidence[len(prefix):])
                        if dependency_path:
                            paths[edge.target].add(dependency_path)
                            path_sources[edge.target][dependency_path].add(evidence)

        by_public_id: dict[str, list[KnowledgeNode]] = defaultdict(list)
        by_qualified: dict[str, list[KnowledgeNode]] = defaultdict(list)
        by_normalized: dict[str, list[KnowledgeNode]] = defaultdict(list)
        by_id = {node.id: node for node in self._graph.nodes}
        for node in self._graph.nodes:
            public_id = self._public_id(node)
            by_public_id[public_id].append(node)
            qualified = self._public_text(
                node.qualified_name or node.name,
                fallback=node.kind.value,
            )
            by_qualified[qualified].append(node)
            derived_names = self._derived_names(node, qualified)
            aliases = {
                qualified,
                self._public_text(node.name, fallback=node.kind.value),
                simple_names.get(node.id, ""),
                *derived_names,
            }
            if node.kind in {KnowledgeKind.REPOSITORY, KnowledgeKind.WORKSPACE}:
                aliases.add(node.kind.value)
            for alias in aliases:
                if alias:
                    by_normalized[_normalized_name(alias)].append(node)

        def freeze(values: Mapping[str, list[KnowledgeNode]]) -> Mapping[str, tuple[KnowledgeNode, ...]]:
            return MappingProxyType({
                key: tuple(sorted(set(items), key=self._node_sort_key))
                for key, items in values.items()
            })

        self._by_id = MappingProxyType(by_id)
        self._by_public_id = freeze(by_public_id)
        self._by_qualified = freeze(by_qualified)
        self._by_normalized = freeze(by_normalized)
        self._simple_names = MappingProxyType(simple_names)
        self._paths = MappingProxyType({
            key: tuple(sorted(values)) for key, values in paths.items()
        })
        self._path_sources = MappingProxyType({
            node_id: MappingProxyType({
                path: tuple(sorted(refs))
                for path, refs in sorted(values.items())
            })
            for node_id, values in sorted(path_sources.items())
        })
        by_path: dict[str, list[KnowledgeNode]] = defaultdict(list)
        projects_by_root: dict[str, list[KnowledgeNode]] = defaultdict(list)
        for node in self._graph.nodes:
            for path in self._paths.get(node.id, ()):
                if node.kind is KnowledgeKind.PROJECT:
                    projects_by_root[path].append(node)
                elif node.kind not in {
                    KnowledgeKind.REPOSITORY,
                    KnowledgeKind.WORKSPACE,
                }:
                    by_path[path].append(node)
        self._by_path = MappingProxyType({
            key: tuple(sorted(set(values), key=self._path_node_sort_key))
            for key, values in by_path.items()
        })
        self._projects_by_root = MappingProxyType({
            key: tuple(sorted(set(values), key=self._path_node_sort_key))
            for key, values in projects_by_root.items()
        })
        self._project_scopes = MappingProxyType({
            key: tuple(sorted(
                value for value in values
                if value and not contains_absolute_path_text(value)
            ))
            for key, values in project_scopes.items()
        })
        self._available_kinds = frozenset(node.kind for node in self._graph.nodes)

    def _matches(self, node: KnowledgeNode, query: SubjectQuery) -> bool:
        if query.kind is not None and node.kind is not query.kind:
            return False
        if query.language is not None and node.language.casefold() != query.language.casefold():
            return False
        if query.path is not None and query.path not in self._paths.get(node.id, ()):
            return False
        if query.project is not None:
            scopes = set(self._project_scopes.get(node.id, ()))
            if node.project_id:
                scopes.add(node.project_id)
            normalized_project = _normalized_name(query.project)
            if normalized_project not in {
                _normalized_name(scope) for scope in scopes
            }:
                return False
        return True

    def _candidate(
        self,
        node: KnowledgeNode,
        basis: SubjectMatchBasis,
    ) -> SubjectCandidate:
        qualified = self._public_text(
            node.qualified_name or node.name,
            fallback=node.kind.value,
        )
        derived = self._derived_names(node, qualified)
        derived_simple = next((item for item in derived if "(" not in item), None)
        name = self._simple_names.get(node.id) or derived_simple or (
            derived[0] if derived else self._public_text(node.name, fallback=qualified)
        )
        scopes = self._project_scopes.get(node.id, ())
        project = node.project_id or (scopes[0] if len(scopes) == 1 else None)
        if project and contains_absolute_path_text(project):
            project = None
        language = node.language or "unknown"
        if contains_absolute_path_text(language):
            language = "unknown"
        paths = self._paths.get(node.id, ())
        return SubjectCandidate(
            self._public_id(node),
            node.kind,
            name,
            qualified,
            project,
            language,
            paths[0] if len(paths) == 1 else None,
            scopes,
            basis,
            node.id,
        )

    def _resolved(
        self,
        query: SubjectQuery,
        node: KnowledgeNode,
        basis: SubjectMatchBasis,
    ) -> SubjectResolution:
        return SubjectResolution(
            query,
            ResolutionStatus.RESOLVED,
            self._candidate(node, basis),
            (),
            0,
            0,
            basis,
            self.graph_digest,
            self.limitations,
        )

    def _ambiguous(
        self,
        query: SubjectQuery,
        nodes: tuple[KnowledgeNode, ...],
        basis: SubjectMatchBasis,
    ) -> SubjectResolution:
        ordered = tuple(sorted(set(nodes), key=self._node_sort_key))
        included = tuple(
            self._candidate(node, basis) for node in ordered[: self.maximum_candidates]
        )
        return SubjectResolution(
            query,
            ResolutionStatus.AMBIGUOUS,
            None,
            included,
            len(ordered),
            len(ordered) - len(included),
            basis,
            self.graph_digest,
            (*self.limitations, "Multiple canonical subjects require disambiguation."),
        )

    def _result(
        self,
        query: SubjectQuery,
        status: ResolutionStatus,
        *,
        limitations: Iterable[str] = (),
    ) -> SubjectResolution:
        return SubjectResolution(
            query,
            status,
            None,
            (),
            0,
            0,
            SubjectMatchBasis.NONE,
            self.graph_digest,
            (*self.limitations, *tuple(limitations)),
        )

    @staticmethod
    def _node_sort_key(node: KnowledgeNode) -> tuple[str, str, str, str, str]:
        return (
            _normalized_name(node.qualified_name or node.name),
            node.project_id or "",
            node.kind.value,
            node.language,
            node.id,
        )

    @staticmethod
    def _path_node_sort_key(node: KnowledgeNode) -> tuple[str, str, str, str, str]:
        return (
            CanonicalSubjectResolver._public_id(node),
            node.kind.value,
            node.qualified_name or node.name,
            node.project_id or "",
            node.language,
        )

    def _candidate_path_sources(
        self,
        node: KnowledgeNode,
        path: str,
        *,
        project_fallback: bool,
    ) -> tuple[str, ...]:
        sources = self._path_sources.get(node.id, {})
        if not project_fallback:
            refs = sources.get(path, ())
            if not refs:
                raise RuntimeError("exact path candidate lacks resolver provenance")
            return tuple(refs)
        path_parts = PurePosixPath(path).parts
        deepest = -1
        retained: set[str] = set()
        for root, refs in sources.items():
            root_parts = () if root == "." else PurePosixPath(root).parts
            if len(root_parts) > len(path_parts):
                continue
            if root_parts and path_parts[:len(root_parts)] != root_parts:
                continue
            depth = len(root_parts)
            if depth > deepest:
                deepest = depth
                retained = set(refs)
            elif depth == deepest:
                retained.update(refs)
        if deepest < 0 or not retained:
            raise RuntimeError("project path fallback lacks resolver provenance")
        retained.add("canonical_subject_resolver:project_path_containment")
        return tuple(sorted(retained))

    def _containing_projects(self, path: str) -> tuple[KnowledgeNode, ...]:
        path_parts = PurePosixPath(path).parts
        deepest = -1
        matches: list[KnowledgeNode] = []
        for root, projects in self._projects_by_root.items():
            root_parts = () if root == "." else PurePosixPath(root).parts
            if len(root_parts) > len(path_parts):
                continue
            if root_parts and path_parts[:len(root_parts)] != root_parts:
                continue
            depth = len(root_parts)
            if depth > deepest:
                deepest = depth
                matches = list(projects)
            elif depth == deepest:
                matches.extend(projects)
        return tuple(sorted(set(matches), key=self._path_node_sort_key))

    @staticmethod
    def _public_text(value: str, *, fallback: str) -> str:
        text = value.strip()
        return fallback if not text or contains_absolute_path_text(text) else text

    @staticmethod
    def _public_id(node: KnowledgeNode) -> str:
        if node.kind in {KnowledgeKind.REPOSITORY, KnowledgeKind.WORKSPACE}:
            return node.kind.value
        if not contains_absolute_path_text(node.id):
            return node.id
        digest = hashlib.sha256(node.id.encode("utf-8")).hexdigest()
        return f"canonical-ref:{digest}"

    @staticmethod
    def _derived_names(node: KnowledgeNode, qualified: str) -> tuple[str, ...]:
        """Derive identifier aliases without fuzzy or semantic name inference."""

        values: set[str] = set()
        if node.kind is KnowledgeKind.METHOD and "#" in qualified:
            signature = qualified.rsplit("#", 1)[-1]
            values.add(signature)
            method_name = signature.partition("(")[0]
            if method_name:
                values.add(method_name)
        elif node.kind in {
            KnowledgeKind.PACKAGE,
            KnowledgeKind.TYPE,
            KnowledgeKind.FIELD,
        }:
            tail = qualified.rsplit(".", 1)[-1]
            if tail:
                values.add(tail)
        return tuple(sorted(values, key=lambda item: (_normalized_name(item), item)))


def _normalized_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value.strip()).casefold()


def _safe_relative_path(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if (
        not normalized
        or re.match(r"^[A-Za-z]:", normalized)
        or contains_absolute_path_text(normalized)
    ):
        return None
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


def _mapping_items(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _strict_mapping_items(
    value: object,
) -> tuple[Mapping[str, object], ...] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    items = tuple(value)
    if any(not isinstance(item, Mapping) for item in items):
        return None
    return tuple(item for item in items if isinstance(item, Mapping))
