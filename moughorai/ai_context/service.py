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
    ) -> WorkspaceSemanticContext:
        selected = tuple(projects) if projects is not None else workspace.projects
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
                (self._symbol(symbol, workspace.root) for symbol in symbols),
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
        }
        return WorkspaceSemanticContext(payload)

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
