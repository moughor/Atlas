"""Deterministic Atlas CLI output formats."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
import json
from typing import Any

from .workspace import ProjectRun, WorkspaceRunReport
from .sarif import SarifExporter


class OutputFormat(str, Enum):
    TEXT = "text"
    JSON = "json"
    JSONL = "jsonl"
    SARIF = "sarif"


def report_payload(report: WorkspaceRunReport) -> dict[str, Any]:
    """Return a stable CLI representation without timing-dependent fields."""
    return {
        "type": "workspace-analysis",
        "succeeded": report.succeeded,
        "requested": list(report.requested),
        "analysis_order": list(report.analysis_order),
        "runs": [_run_payload(run) for run in report.runs],
    }


def render_report(report: WorkspaceRunReport, output_format: OutputFormat | str) -> str:
    selected = OutputFormat(output_format)
    payload = report_payload(report)
    if selected is OutputFormat.TEXT:
        lines = [f"{run.project}: {run.status.value}" for run in report.runs]
        lines.extend((f"projects: {len(report.runs)}", f"succeeded: {'yes' if report.succeeded else 'no'}"))
        return "\n".join(lines)
    if selected is OutputFormat.JSON:
        return _json(payload, pretty=True)
    if selected is OutputFormat.JSONL:
        records = (
            [{"type": "project", **run} for run in payload["runs"]]
            + [{
                "type": "summary",
                "succeeded": payload["succeeded"],
                "requested": payload["requested"],
                "analysis_order": payload["analysis_order"],
                "projects": len(report.runs),
            }]
        )
        return "\n".join(_json(record) for record in records)
    return _json(_sarif(report), pretty=True)


def _run_payload(run: ProjectRun) -> dict[str, Any]:
    data: dict[str, Any] = {"project": run.project, "status": run.status.value}
    if run.value is not None:
        data["value"] = _normalize(run.value)
    if run.error is not None:
        data["error"] = run.error
    if run.blocked_by:
        data["blocked_by"] = list(run.blocked_by)
    return data


def _sarif(report: WorkspaceRunReport) -> dict[str, Any]:
    return SarifExporter().to_dict(report)


def _findings(run: ProjectRun) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(run.value, Mapping):
        return ()
    raw = run.value.get("findings", ())
    if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Iterable):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _location(finding: Mapping[str, Any]) -> dict[str, Any] | None:
    path = finding.get("path", finding.get("file"))
    if path is None:
        return None
    region: dict[str, int] = {}
    for source, target in (("line", "startLine"), ("column", "startColumn"), ("end_line", "endLine"), ("end_column", "endColumn")):
        value = finding.get(source)
        if value is not None:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                region[target] = parsed
    physical: dict[str, Any] = {"artifactLocation": {"uri": str(path).replace("\\", "/")}}
    if region:
        physical["region"] = region
    return {"physicalLocation": physical}


def _sarif_level(value: Any) -> str:
    normalized = str(value).lower()
    if normalized in {"error", "high", "critical"}:
        return "error"
    if normalized in {"note", "info", "information", "low"}:
        return "note"
    if normalized in {"none", "off"}:
        return "none"
    return "warning"


def _result_key(result: Mapping[str, Any]) -> tuple[str, str, int, int, str]:
    physical = ((result.get("locations") or [{}])[0].get("physicalLocation") or {})
    artifact = physical.get("artifactLocation") or {}
    region = physical.get("region") or {}
    return (
        str(artifact.get("uri", "")),
        str(result.get("ruleId", "")),
        int(region.get("startLine", 0)),
        int(region.get("startColumn", 0)),
        str((result.get("message") or {}).get("text", "")),
    )


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _json(value: Any, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
