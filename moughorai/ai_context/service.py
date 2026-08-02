from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from moughorai.global_symbols import GlobalSymbol
from moughorai.history import HistoricalRun
from moughorai.profiling import ProfileMetric, ProfileReport
from moughorai.semantic import Diagnostic
from moughorai.semantic.types import TypeTable
from moughorai.semantic.types.serialization import type_to_dict
from moughorai.workspace import Project, Workspace
from moughorai.dependency_intelligence import DeclaredDependency
from moughorai.knowledge_graph import KnowledgeGraphBuilder

from .models import WorkspaceSemanticContext


class WorkspaceContextBuilder:
    """Build stable semantic JSON while keeping Atlas analysis authoritative."""

    SCHEMA_VERSION = 1

    @staticmethod
    def from_snapshot(snapshot: object) -> WorkspaceSemanticContext:
        """Restore deterministic context without re-running workspace analysis."""
        converter = getattr(snapshot, "to_context", None)
        if not callable(converter):
            raise TypeError("snapshot must provide to_context()")
        context = converter()
        if not isinstance(context, WorkspaceSemanticContext):
            raise TypeError("snapshot did not produce WorkspaceSemanticContext")
        return context

    def build(
        self,
        workspace: Workspace,
        *,
        projects: Iterable[Project] | None = None,
        diagnostics: Mapping[str, Iterable[Diagnostic]] | Iterable[Diagnostic] = (),
        history: Iterable[HistoricalRun] = (),
        symbols: Iterable[GlobalSymbol] = (),
        types: Mapping[str, TypeTable] | TypeTable | None = None,
        metrics: ProfileReport | Iterable[ProfileMetric] = (),
        declared_dependencies: Iterable[DeclaredDependency] = (),
        repository_summary: object | None = None,
    ) -> WorkspaceSemanticContext:
        selected = tuple(projects) if projects is not None else workspace.projects
        semantic_symbols = tuple(symbols)
        names = {project.name for project in selected}
        unknown = names.difference(workspace.names())
        if unknown:
            raise ValueError(f"projects are not members of workspace: {sorted(unknown)}")

        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "workspace": {
                "root": workspace.root.as_posix(),
                "projects": [
                    project.to_dict(root=workspace.root)
                    for project in sorted(selected, key=lambda item: item.name)
                ],
            },
            "diagnostics": self._diagnostics(diagnostics),
            "history": sorted(
                (self._history(run) for run in history),
                key=lambda item: (item["created_at"], item["run_id"]),
            ),
            "symbols": sorted(
                (self._symbol(symbol, workspace.root) for symbol in semantic_symbols),
                key=lambda item: (
                    item["qualified_name"],
                    item.get("project_id") or "",
                    item["kind"],
                    item["id"],
                ),
            ),
            "types": self._types(types),
            "metrics": sorted(
                (self._metric(metric) for metric in self._metrics(metrics)),
                key=lambda item: item["name"],
            ),
            "semantic_graph": self._semantic_graph(semantic_symbols),
            "dependencies": [
                item.to_dict(root=workspace.root)
                for item in sorted(
                    set(declared_dependencies),
                    key=DeclaredDependency.deterministic_sort_key,
                )
            ],
            "repository_summary": (
                {}
                if repository_summary is None
                else self._value(repository_summary.to_dict())
            ),
        }
        payload["semantic_graph"] = KnowledgeGraphBuilder().build_context(payload).to_dict()
        return WorkspaceSemanticContext(payload)

    @staticmethod
    def _semantic_graph(symbols: tuple[GlobalSymbol, ...]) -> dict[str, Any]:
        ordered = tuple(sorted(symbols, key=lambda item: str(item.id)))
        nodes = []
        edges: dict[tuple[str, str, str], set[str]] = {}
        by_name: dict[str, list[GlobalSymbol]] = {}
        by_suffix: dict[str, list[GlobalSymbol]] = {}
        by_scoped: dict[
            tuple[str | None, str | None, str], list[GlobalSymbol]
        ] = {}
        for symbol in ordered:
            by_name.setdefault(symbol.qualified_name, []).append(symbol)
            by_scoped.setdefault(
                (symbol.project_id, symbol.scope_id, symbol.qualified_name),
                [],
            ).append(symbol)
            by_suffix.setdefault(
                symbol.qualified_name.rsplit(".", 1)[-1],
                [],
            ).append(symbol)

        def add_edge(
            source: str,
            target: str,
            kind: str,
            evidence: str,
        ) -> None:
            edges.setdefault((source, target, kind), set()).add(evidence)

        def resolve(
            reference: str,
            source: GlobalSymbol,
        ) -> GlobalSymbol | None:
            scoped = by_scoped.get(
                (source.project_id, source.scope_id, reference),
                (),
            )
            if len(scoped) == 1:
                return scoped[0]
            if source.scope_id is not None:
                return None
            exact = by_name.get(reference, ())
            project_exact = tuple(
                item for item in exact if item.project_id == source.project_id
            )
            if len(project_exact) == 1:
                return project_exact[0]
            if len(project_exact) > 1:
                return None
            if len(exact) == 1:
                return exact[0]
            suffix = by_suffix.get(reference.rsplit(".", 1)[-1], ())
            scoped_suffix = tuple(
                item
                for item in suffix
                if item.project_id == source.project_id
                and item.scope_id == source.scope_id
            )
            if len(scoped_suffix) == 1:
                return scoped_suffix[0]
            project_suffix = tuple(
                item for item in suffix if item.project_id == source.project_id
            )
            if len(project_suffix) == 1:
                return project_suffix[0]
            if len(project_suffix) > 1:
                return None
            return suffix[0] if len(suffix) == 1 else None

        for symbol in ordered:
            metadata = dict(symbol.metadata)
            language = metadata.get("language")
            if language is None and symbol.source is not None:
                language = {
                    ".java": "java", ".py": "python", ".pyi": "python",
                    ".ts": "typescript", ".tsx": "typescript",
                }.get(symbol.source.suffix.casefold(), "unknown")
            node = {
                "id": str(symbol.id),
                "project_id": symbol.project_id,
                "language": language or "unknown",
                "kind": symbol.kind.value,
                "qualified_name": symbol.qualified_name,
            }
            if symbol.scope_id is not None:
                node["scope_id"] = symbol.scope_id
            nodes.append(node)
            if symbol.owner_id is not None:
                add_edge(
                    str(symbol.id),
                    str(symbol.owner_id),
                    "member_of",
                    "global_symbol.owner_id",
                )
            for imported in filter(None, metadata.get("imports", "").split(",")):
                normalized = imported.lstrip(".").replace("/", ".")
                target = resolve(normalized, symbol)
                if target is not None:
                    add_edge(
                        str(symbol.id),
                        str(target.id),
                        "imports",
                        f"global_symbol.metadata:imports:{normalized}",
                    )
            for key, kind in (
                ("inherits", "inheritance"),
                ("bases", "inheritance"),
                ("overrides", "overrides"),
            ):
                for reference in filter(None, metadata.get(key, "").split(",")):
                    target = resolve(reference, symbol)
                    if target is not None:
                        add_edge(
                            str(symbol.id),
                            str(target.id),
                            kind,
                            f"global_symbol.metadata:{key}:{reference}",
                        )
        return {
            "nodes": nodes,
            "edges": [
                {
                    "source": source,
                    "target": target,
                    "kind": kind,
                    "evidence": sorted(evidence),
                }
                for (source, target, kind), evidence in sorted(edges.items())
            ],
        }

    def _diagnostics(
        self,
        values: Mapping[str, Iterable[Diagnostic]] | Iterable[Diagnostic],
    ) -> list[dict[str, Any]]:
        pairs = (
            ((project, diagnostic) for project, items in values.items() for diagnostic in items)
            if isinstance(values, Mapping)
            else (("", diagnostic) for diagnostic in values)
        )
        result = []
        for project, diagnostic in pairs:
            result.append(
                {
                    "project": project,
                    "code": diagnostic.code,
                    "message": diagnostic.message,
                    "severity": diagnostic.severity.value,
                    "location": self._value(diagnostic.location),
                    "rule": diagnostic.rule,
                    "pass_name": diagnostic.pass_name,
                }
            )
        return sorted(
            result,
            key=lambda item: (
                item["project"],
                item["severity"],
                item["code"],
                item["message"],
                repr(item["location"]),
            ),
        )

    def _history(self, run: HistoricalRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "created_at": run.created_at,
            "succeeded": run.succeeded,
            "requested": sorted(run.requested),
            "analysis_order": list(run.analysis_order),
            "projects": [
                {
                    "project": item.project,
                    "status": item.status.value,
                    "value": self._value(item.value),
                    "error": item.error,
                    "blocked_by": sorted(item.blocked_by),
                    "duration_ms": item.duration_ms,
                }
                for item in run.runs
            ],
        }

    def _symbol(self, symbol: GlobalSymbol, root: Path) -> dict[str, Any]:
        source = symbol.source
        if source is not None:
            try:
                source = source.resolve().relative_to(root)
            except ValueError:
                pass
        result = {
            "id": str(symbol.id),
            "kind": symbol.kind.value,
            "name": symbol.name,
            "qualified_name": symbol.qualified_name,
            "owner_id": None if symbol.owner_id is None else str(symbol.owner_id),
            "source": None if source is None else source.as_posix(),
            "metadata": dict(symbol.metadata),
        }
        if symbol.project_id is not None:
            result["project_id"] = symbol.project_id
        if symbol.scope_id is not None:
            result["scope_id"] = symbol.scope_id
        return result

    def _types(self, values: Mapping[str, TypeTable] | TypeTable | None) -> dict[str, Any]:
        if values is None:
            return {}
        tables = {"": values} if isinstance(values, TypeTable) else values
        return {
            project: [
                {"node": self._stable_key(key), "type": type_to_dict(value)}
                for key, value in sorted(table.entries.items(), key=lambda item: self._stable_key(item[0]))
            ]
            for project, table in sorted(tables.items())
        }

    @staticmethod
    def _metrics(values: ProfileReport | Iterable[ProfileMetric]) -> Iterable[ProfileMetric]:
        return values.metrics if isinstance(values, ProfileReport) else values

    @staticmethod
    def _metric(metric: ProfileMetric) -> dict[str, Any]:
        return metric.to_dict()

    @classmethod
    def _stable_key(cls, value: object) -> str:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return str(value)
        if isinstance(value, tuple):
            return "/".join(cls._stable_key(item) for item in value)
        raise TypeError(f"semantic type key is not deterministic: {value!r}")

    @classmethod
    def _value(cls, value: object) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Path):
            return value.as_posix()
        if is_dataclass(value):
            return cls._value(asdict(value))
        if isinstance(value, Mapping):
            return {
                str(key): cls._value(item)
                for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            }
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [cls._value(item) for item in value]
        raise TypeError(f"value is not deterministic JSON data: {value!r}")
