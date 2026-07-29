"""Deterministic SARIF 2.1.0 export for Atlas workspace reports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import hashlib
import json
from typing import Any

from .rule_sdk import RuleCatalog
from .version import __version__
from .workspace import ProjectRun, WorkspaceRunReport


SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"


class SarifValidationError(ValueError):
    pass


class SarifExporter:
    def to_dict(
        self,
        report: WorkspaceRunReport,
        *,
        catalog: RuleCatalog | None = None,
        automation_id: str | None = None,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        observed: dict[str, Mapping[str, Any]] = {}
        for run in report.runs:
            for finding in _findings(run):
                rule_id = str(finding.get("rule_id", finding.get("ruleId", "atlas.finding")))
                observed.setdefault(rule_id, finding)
                results.append(self._result(run.project, rule_id, finding))
        results.sort(key=_result_key)
        metadata = {entry.rule_id: entry for entry in catalog.entries()} if catalog is not None else {}
        rule_ids = sorted(set(observed) | set(metadata))
        rules = [
            _rule_descriptor(rule_id, observed.get(rule_id), metadata.get(rule_id))
            for rule_id in rule_ids
        ]
        run_value: dict[str, Any] = {
            "tool": {
                "driver": {
                    "name": "Atlas",
                    "version": __version__,
                    "informationUri": "https://github.com/moughor/Atlas",
                    "rules": rules,
                }
            },
            "columnKind": "unicodeCodePoints",
            "invocations": [{"executionSuccessful": report.succeeded}],
            "results": results,
            "properties": {
                "analysisOrder": list(report.analysis_order),
                "requested": list(report.requested),
                "succeeded": report.succeeded,
            },
        }
        if automation_id:
            run_value["automationDetails"] = {"id": automation_id}
        payload = {"$schema": SARIF_SCHEMA, "version": SARIF_VERSION, "runs": [run_value]}
        validate_sarif(payload)
        return payload

    def to_json(
        self,
        report: WorkspaceRunReport,
        *,
        catalog: RuleCatalog | None = None,
        automation_id: str | None = None,
        pretty: bool = True,
    ) -> str:
        return json.dumps(
            self.to_dict(report, catalog=catalog, automation_id=automation_id),
            sort_keys=True,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            ensure_ascii=False,
        )

    def _result(self, project: str, rule_id: str, finding: Mapping[str, Any]) -> dict[str, Any]:
        message = str(finding.get("message", finding.get("description", rule_id)))
        result: dict[str, Any] = {
            "ruleId": rule_id,
            "level": _level(finding.get("level", finding.get("severity", "warning"))),
            "message": {"text": message},
            "partialFingerprints": {
                "atlasFinding/v1": _fingerprint(project, rule_id, finding),
            },
            "properties": {"project": project, **_properties(finding)},
        }
        location = _location(finding)
        if location is not None:
            result["locations"] = [location]
        fixes = _fixes(finding)
        if fixes:
            result["fixes"] = fixes
        return result


def validate_sarif(value: Mapping[str, Any]) -> None:
    if value.get("version") != SARIF_VERSION:
        raise SarifValidationError("unsupported SARIF version")
    if value.get("$schema") != SARIF_SCHEMA:
        raise SarifValidationError("SARIF schema URI is invalid")
    runs = value.get("runs")
    if not isinstance(runs, list) or not runs:
        raise SarifValidationError("SARIF runs must be a non-empty list")
    for run in runs:
        if not isinstance(run, Mapping):
            raise SarifValidationError("SARIF run must be an object")
        driver = ((run.get("tool") or {}).get("driver") or {})
        if not isinstance(driver, Mapping) or not str(driver.get("name", "")).strip():
            raise SarifValidationError("SARIF tool driver is missing")
        results = run.get("results", [])
        if not isinstance(results, list):
            raise SarifValidationError("SARIF results must be a list")
        for result in results:
            if not isinstance(result, Mapping) or not str(result.get("ruleId", "")).strip():
                raise SarifValidationError("SARIF result ruleId is missing")
            message = result.get("message")
            if not isinstance(message, Mapping) or not str(message.get("text", "")).strip():
                raise SarifValidationError("SARIF result message is missing")


def _findings(run: ProjectRun) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(run.value, Mapping):
        return ()
    raw = run.value.get("findings", ())
    if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Iterable):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _rule_descriptor(rule_id: str, finding: Mapping[str, Any] | None, metadata: Any) -> dict[str, Any]:
    if metadata is not None:
        descriptor: dict[str, Any] = {
            "id": rule_id,
            "name": metadata.title,
            "shortDescription": {"text": metadata.title},
            "fullDescription": {"text": metadata.description},
            "defaultConfiguration": {"level": _level(metadata.default_severity.value)},
            "properties": {
                "category": metadata.category,
                "tags": list(metadata.tags),
                "languages": list(metadata.languages),
                "enabledByDefault": metadata.enabled_by_default,
                "deprecated": metadata.deprecated,
            },
        }
        if metadata.documentation_url:
            descriptor["helpUri"] = metadata.documentation_url
        return descriptor
    title = str((finding or {}).get("title", rule_id))
    return {"id": rule_id, "shortDescription": {"text": title}}


def _location(finding: Mapping[str, Any]) -> dict[str, Any] | None:
    nested = finding.get("location")
    source = nested if isinstance(nested, Mapping) else finding
    path = source.get("path", source.get("file"))
    if path is None:
        return None
    region: dict[str, int] = {}
    for names, target in (
        (("line", "start_line"), "startLine"),
        (("column", "start_column"), "startColumn"),
        (("end_line",), "endLine"),
        (("end_column",), "endColumn"),
    ):
        raw = next((source[name] for name in names if name in source), None)
        try:
            parsed = int(raw) if raw is not None else 0
        except (TypeError, ValueError):
            parsed = 0
        if parsed > 0:
            region[target] = parsed
    physical: dict[str, Any] = {
        "artifactLocation": {"uri": str(path).replace("\\", "/")},
    }
    if region:
        physical["region"] = region
    return {"physicalLocation": physical}


def _fixes(finding: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = finding.get("fixes", ())
    if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Iterable):
        return []
    fixes = []
    for value in raw:
        if not isinstance(value, Mapping):
            continue
        path = value.get("path", value.get("file"))
        replacement = value.get("replacement")
        if path is None or not isinstance(replacement, str):
            continue
        region = {}
        for source, target in (
            ("start_line", "startLine"),
            ("start_column", "startColumn"),
            ("end_line", "endLine"),
            ("end_column", "endColumn"),
        ):
            try:
                number = int(value.get(source, 0))
            except (TypeError, ValueError):
                number = 0
            if number > 0:
                region[target] = number
        fixes.append({
            "description": {"text": str(value.get("description", "Apply Atlas fix"))},
            "artifactChanges": [{
                "artifactLocation": {"uri": str(path).replace("\\", "/")},
                "replacements": [{"deletedRegion": region, "insertedContent": {"text": replacement}}],
            }],
        })
    return sorted(fixes, key=lambda item: json.dumps(item, sort_keys=True))


def _properties(finding: Mapping[str, Any]) -> dict[str, Any]:
    raw = finding.get("properties", finding.get("metadata", {}))
    return _normalize(raw) if isinstance(raw, Mapping) else {}


def _fingerprint(project: str, rule_id: str, finding: Mapping[str, Any]) -> str:
    explicit = finding.get("fingerprint")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    identity = {
        "project": project,
        "ruleId": rule_id,
        "message": finding.get("message", finding.get("description", "")),
        "location": _location(finding),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _level(value: Any) -> str:
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
