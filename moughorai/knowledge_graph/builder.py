from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import quote

from moughorai.dependency_graph import DependencyGraph
from moughorai.global_symbols import GlobalSymbolDatabase, SymbolId

from .graph import KnowledgeGraph
from .models import KnowledgeEdge, KnowledgeKind, KnowledgeNode, KnowledgeRelation


class KnowledgeGraphBuilder:
    """Build the existing queryable graph from symbols or published Atlas facts."""

    _SYMBOL_KINDS = {
        "package": KnowledgeKind.PACKAGE,
        "type": KnowledgeKind.TYPE,
        "annotation": KnowledgeKind.TYPE,
        "method": KnowledgeKind.METHOD,
        "constructor": KnowledgeKind.METHOD,
        "field": KnowledgeKind.FIELD,
    }
    _RELATIONS = {
        "imports": KnowledgeRelation.IMPORTS,
        "member_of": KnowledgeRelation.MEMBER_OF,
        "extends": KnowledgeRelation.INHERITS,
        "implements": KnowledgeRelation.INHERITS,
        "inheritance": KnowledgeRelation.INHERITS,
        "composition": KnowledgeRelation.COMPOSES,
        "calls": KnowledgeRelation.CALLS,
        "overrides": KnowledgeRelation.OVERRIDES,
        "dependencies": KnowledgeRelation.DEPENDS_ON,
        "depends_on": KnowledgeRelation.DEPENDS_ON,
        "ownership": KnowledgeRelation.OWNS,
    }

    def build(
        self,
        symbols: GlobalSymbolDatabase,
        dependencies: DependencyGraph,
    ) -> KnowledgeGraph:
        """Preserve the original PR27 symbol/dependency graph contract."""
        graph = KnowledgeGraph()
        for symbol in symbols.symbols:
            graph.add_node(KnowledgeNode(
                str(symbol.id),
                KnowledgeKind.SYMBOL,
                symbol.qualified_name,
                symbol.id,
                symbol.metadata,
            ))
            for key, value in symbol.metadata:
                if key not in {"domain", "capability"}:
                    continue
                kind = KnowledgeKind.DOMAIN if key == "domain" else KnowledgeKind.CAPABILITY
                node_id = f"{key}:{value.casefold()}"
                graph.add_node(KnowledgeNode(node_id, kind, value))
                relation = (
                    KnowledgeRelation.BELONGS_TO
                    if key == "domain"
                    else KnowledgeRelation.PROVIDES
                )
                graph.add_edge(KnowledgeEdge(
                    str(symbol.id),
                    node_id,
                    relation,
                    (f"metadata:{key}",),
                ))
        for edge in dependencies.edges:
            if graph.get(str(edge.source)) and graph.get(str(edge.target)):
                graph.add_edge(KnowledgeEdge(
                    str(edge.source),
                    str(edge.target),
                    KnowledgeRelation.DEPENDS_ON,
                    (edge.kind.value,),
                ))
        return graph

    def build_context(self, context: Mapping[str, object]) -> KnowledgeGraph:
        """Consolidate PR125/PR127 facts without parsing or source inspection."""
        graph = KnowledgeGraph()
        summary = self._mapping(context.get("repository_summary"))
        workspace = self._mapping(context.get("workspace"))
        root = str(summary.get("root") or workspace.get("root") or "")
        repository_id = self._id("repository", root)
        workspace_id = self._id("workspace", root)
        graph.add_node(self._node(repository_id, KnowledgeKind.REPOSITORY, root or "repository"))
        graph.add_node(self._node(workspace_id, KnowledgeKind.WORKSPACE, root or "workspace"))
        graph.add_edge(KnowledgeEdge(
            repository_id, workspace_id, KnowledgeRelation.OWNS,
            ("workspace.root",),
        ))

        workspace_projects = {
            str(item.get("name", "")): item
            for item in workspace.get("projects", ())
            if isinstance(item, Mapping)
        }
        projects = tuple(
            item for item in summary.get("projects", ())
            if isinstance(item, Mapping)
        )
        if not projects:
            projects = tuple(
                item for item in workspace.get("projects", ())
                if isinstance(item, Mapping)
            )
        project_ids: dict[str, str] = {}
        module_ids: dict[str, str] = {}
        for project in sorted(projects, key=lambda item: str(item.get("name", ""))):
            name = str(project.get("name", ""))
            project_id = self._id("project", name)
            module_id = self._id("module", name)
            project_ids[name] = project_id
            module_ids[name] = module_id
            graph.add_node(self._node(
                project_id,
                KnowledgeKind.PROJECT,
                name,
                path=str(project.get("path", "")),
            ))
            graph.add_node(self._node(module_id, KnowledgeKind.MODULE, name, project_id=name))
            graph.add_edge(KnowledgeEdge(
                workspace_id, project_id, KnowledgeRelation.OWNS,
                ("workspace.projects",),
            ))
            graph.add_edge(KnowledgeEdge(
                project_id, module_id, KnowledgeRelation.OWNS,
                ("repository_summary.projects",),
            ))
            self._add_build_systems(graph, project, project_id)

        for name, project in sorted(workspace_projects.items()):
            source_id = project_ids.get(name)
            if source_id is None:
                continue
            for dependency in sorted(map(str, project.get("dependencies", ()))):
                target_id = project_ids.get(dependency)
                if target_id is not None:
                    graph.add_edge(KnowledgeEdge(
                        source_id,
                        target_id,
                        KnowledgeRelation.DEPENDS_ON,
                        (f"workspace.projects:{name}:dependencies:{dependency}",),
                    ))

        for item in summary.get("module_hierarchy", ()):
            if not isinstance(item, Mapping):
                continue
            child = module_ids.get(str(item.get("project", "")))
            parent = module_ids.get(str(item.get("parent", "")))
            if child and parent:
                graph.add_edge(KnowledgeEdge(
                    parent, child, KnowledgeRelation.OWNS,
                    ("repository_summary.module_hierarchy",),
                ))

        raw_graph = self._mapping(context.get("semantic_graph"))
        symbol_ids: set[str] = set()
        for item in raw_graph.get("nodes", ()):
            if not isinstance(item, Mapping):
                continue
            node_id = str(item.get("id", ""))
            kind = self._SYMBOL_KINDS.get(str(item.get("kind", "")), KnowledgeKind.SYMBOL)
            qualified_name = str(item.get("qualified_name") or item.get("name") or node_id)
            project = str(item.get("project_id") or "")
            graph.add_node(self._node(
                node_id,
                kind,
                qualified_name,
                symbol_id=SymbolId(node_id),
                qualified_name=qualified_name,
                project_id=project,
                language=str(item.get("language") or "unknown"),
            ))
            symbol_ids.add(node_id)

        owned_symbols: set[str] = set()
        for item in raw_graph.get("edges", ()):
            if not isinstance(item, Mapping):
                continue
            source = str(item.get("source", ""))
            target = str(item.get("target", ""))
            relation = self._RELATIONS.get(str(item.get("kind", "")))
            if relation is None or graph.get(source) is None or graph.get(target) is None:
                continue
            raw_evidence = item.get("evidence", ())
            evidence = (
                tuple(sorted(map(str, raw_evidence)))
                if isinstance(raw_evidence, (list, tuple))
                else ()
            )
            graph.add_edge(KnowledgeEdge(
                source, target, relation,
                evidence or (f"semantic_graph:{item.get('kind')}",),
            ))
            if relation is KnowledgeRelation.MEMBER_OF:
                owned_symbols.add(source)

        for node_id in sorted(symbol_ids.difference(owned_symbols)):
            node = graph.get(node_id)
            if node is None:
                continue
            project = node.project_id or ""
            owner = module_ids.get(project, workspace_id)
            graph.add_edge(KnowledgeEdge(
                owner, node_id, KnowledgeRelation.OWNS,
                ("semantic_graph.project_id",),
            ))

        self._add_dependencies(graph, context, projects, project_ids, workspace_id)
        self._add_frameworks(graph, summary, project_ids, workspace_id)
        return graph

    def _add_build_systems(
        self,
        graph: KnowledgeGraph,
        project: Mapping[str, object],
        project_id: str,
    ) -> None:
        name = str(project.get("name", ""))
        for build_system in sorted(map(str, project.get("build_systems", ()))):
            target_id = self._id("build_system", name, build_system)
            graph.add_node(self._node(
                target_id,
                KnowledgeKind.BUILD_SYSTEM,
                build_system,
                project_id=name,
                representation="detected-build-system",
            ))
            graph.add_edge(KnowledgeEdge(
                project_id, target_id, KnowledgeRelation.OWNS,
                ("repository_summary.build_systems",),
            ))

    def _add_dependencies(
        self,
        graph: KnowledgeGraph,
        context: Mapping[str, object],
        projects: tuple[Mapping[str, object], ...],
        project_ids: Mapping[str, str],
        workspace_id: str,
    ) -> None:
        for item in context.get("dependencies", ()):
            if not isinstance(item, Mapping):
                continue
            ecosystem = str(item.get("ecosystem", "unknown"))
            name = str(item.get("name", ""))
            version = str(item.get("version") or "unversioned")
            scope = str(item.get("scope") or "unspecified")
            dependency_id = self._id(
                "dependency",
                ecosystem,
                name,
                version,
                scope,
            )
            graph.add_node(self._node(
                dependency_id,
                KnowledgeKind.DEPENDENCY,
                name,
                ecosystem=ecosystem,
                version=version,
                scope=scope,
                optional=str(bool(item.get("optional", False))).lower(),
            ))
            source = str(item.get("source", ""))
            project = self._project_for_source(source, projects)
            owner = project_ids.get(project, workspace_id)
            graph.add_edge(KnowledgeEdge(
                owner, dependency_id, KnowledgeRelation.DEPENDS_ON,
                (
                    f"declared_dependency:{ecosystem}:{name}:{version}:{scope}",
                    f"declared_dependency.source:{source}",
                ),
            ))

    def _add_frameworks(
        self,
        graph: KnowledgeGraph,
        summary: Mapping[str, object],
        project_ids: Mapping[str, str],
        workspace_id: str,
    ) -> None:
        evidence = tuple(
            item for item in summary.get("framework_evidence", ())
            if isinstance(item, Mapping)
        )
        names = set(map(str, summary.get("frameworks", ())))
        names.update(str(item.get("framework", "")) for item in evidence)
        for name in sorted(filter(None, names)):
            framework_id = self._id("framework", name)
            graph.add_node(self._node(framework_id, KnowledgeKind.FRAMEWORK, name))
            related = [item for item in evidence if str(item.get("framework", "")) == name]
            owners = {
                project_ids.get(str(item.get("project", "")), workspace_id)
                for item in related
            } or {workspace_id}
            for owner in sorted(owners):
                graph.add_edge(KnowledgeEdge(
                    owner, framework_id, KnowledgeRelation.DEPENDS_ON,
                    tuple(sorted({
                        f"{item.get('scope', 'unscoped')}:{item.get('reference', '')}"
                        for item in related
                    })) or ("repository_summary.frameworks",),
                ))

    @staticmethod
    def _project_for_source(
        source: str,
        projects: tuple[Mapping[str, object], ...],
    ) -> str:
        source = source.replace("\\", "/").lstrip("./")
        candidates: list[tuple[int, str]] = []
        for project in projects:
            path = str(project.get("path", "")).replace("\\", "/").strip("/")
            if path in {"", "."} or source == path or source.startswith(f"{path}/"):
                candidates.append((len(path.split("/")) if path not in {"", "."} else 0, str(project.get("name", ""))))
        return max(candidates, default=(0, ""))[1]

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _id(prefix: str, *parts: str) -> str:
        return ":".join((prefix, *(quote(str(part), safe="._-") for part in parts)))

    @staticmethod
    def _node(
        node_id: str,
        kind: KnowledgeKind,
        name: str,
        *,
        symbol_id: SymbolId | None = None,
        **metadata: str,
    ) -> KnowledgeNode:
        qualified_name = metadata.pop("qualified_name", None)
        project_id = metadata.pop("project_id", None)
        language = metadata.pop("language", "unknown")
        return KnowledgeNode(
            node_id,
            kind,
            name,
            symbol_id,
            tuple(sorted((key, value) for key, value in metadata.items() if value)),
            qualified_name,
            project_id,
            language,
        )
