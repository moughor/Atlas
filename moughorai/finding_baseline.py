"""Cross-language finding baselines for Atlas workspace reports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .workspace import ProjectRun, WorkspaceRunReport


FINDING_BASELINE_SCHEMA_VERSION = 1


class FindingBaselineError(ValueError):
    """Raised when a finding baseline is corrupt or incompatible."""


@dataclass(frozen=True, slots=True)
class FindingBaseline:
    schema_version: int
    fingerprints: tuple[str, ...]
    created_at: str

    def __post_init__(self) -> None:
        if self.schema_version != FINDING_BASELINE_SCHEMA_VERSION:
            raise FindingBaselineError(f"unsupported finding baseline schema: {self.schema_version}")
        if self.fingerprints != tuple(sorted(set(self.fingerprints))):
            raise FindingBaselineError("finding baseline fingerprints must be unique and sorted")

    def contains(self, fingerprint: str) -> bool:
        return fingerprint in self.fingerprints

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "fingerprints": list(self.fingerprints),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FindingBaseline":
        try:
            schema = int(value["schema_version"])
            raw = value["fingerprints"]
            created_at = str(value["created_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FindingBaselineError("finding baseline is missing required fields") from exc
        if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
            raise FindingBaselineError("finding baseline fingerprints must be non-empty strings")
        try:
            timestamp = datetime.fromisoformat(created_at)
        except ValueError as exc:
            raise FindingBaselineError("finding baseline timestamp is invalid") from exc
        if timestamp.tzinfo is None:
            raise FindingBaselineError("finding baseline timestamp must include a timezone")
        return cls(schema, tuple(raw), created_at)


@dataclass(frozen=True, slots=True)
class FindingBaselineComparison:
    new_fingerprints: tuple[str, ...]
    existing_fingerprints: tuple[str, ...]

    @property
    def new_count(self) -> int:
        return len(self.new_fingerprints)

    @property
    def existing_count(self) -> int:
        return len(self.existing_fingerprints)

    def to_dict(self) -> dict[str, Any]:
        return {
            "new": list(self.new_fingerprints),
            "existing": list(self.existing_fingerprints),
            "new_count": self.new_count,
            "existing_count": self.existing_count,
        }


class FindingBaselineStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, baseline: FindingBaseline) -> Path:
        payload = baseline.to_dict()
        canonical = _canonical(payload)
        envelope = {
            "checksum": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "baseline": payload,
        }
        text = json.dumps(envelope, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        return self.path

    def load(self) -> FindingBaseline:
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise FindingBaselineError(f"cannot read finding baseline: {exc}") from exc
        if not isinstance(envelope, Mapping) or not isinstance(envelope.get("baseline"), Mapping):
            raise FindingBaselineError("finding baseline envelope is invalid")
        payload = envelope["baseline"]
        expected = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
        if envelope.get("checksum") != expected:
            raise FindingBaselineError("finding baseline checksum mismatch")
        return FindingBaseline.from_dict(payload)


class FindingBaselineService:
    def capture(self, report: WorkspaceRunReport, *, created_at: str | None = None) -> FindingBaseline:
        fingerprints = tuple(sorted({fingerprint for _, _, fingerprint in self._report_findings(report)}))
        timestamp = created_at or datetime.now(timezone.utc).isoformat()
        return FindingBaseline(FINDING_BASELINE_SCHEMA_VERSION, fingerprints, timestamp)

    def compare(self, report: WorkspaceRunReport, baseline: FindingBaseline) -> FindingBaselineComparison:
        current = {fingerprint for _, _, fingerprint in self._report_findings(report)}
        existing = tuple(sorted(current.intersection(baseline.fingerprints)))
        new = tuple(sorted(current.difference(baseline.fingerprints)))
        return FindingBaselineComparison(new, existing)

    def filter(self, report: WorkspaceRunReport, baseline: FindingBaseline) -> tuple[WorkspaceRunReport, FindingBaselineComparison]:
        comparison = self.compare(report, baseline)
        existing = set(comparison.existing_fingerprints)
        runs = tuple(self._filter_run(run, existing) for run in report.runs)
        return replace(report, runs=runs), comparison

    @staticmethod
    def fingerprint(project: str, finding: Mapping[str, Any]) -> str:
        explicit = finding.get("fingerprint")
        if isinstance(explicit, str) and explicit.strip():
            identity: Any = {"project": project, "fingerprint": explicit.strip()}
        else:
            identity = {
                "project": project,
                "rule_id": finding.get("rule_id", finding.get("ruleId", "")),
                "path": str(finding.get("path", finding.get("file", ""))).replace("\\", "/"),
                "line": finding.get("line", 0),
                "column": finding.get("column", 0),
                "message": finding.get("message", finding.get("description", "")),
            }
        return hashlib.sha256(_canonical(_normalize(identity)).encode("utf-8")).hexdigest()

    def _report_findings(self, report: WorkspaceRunReport) -> tuple[tuple[str, Mapping[str, Any], str], ...]:
        items = []
        for run in report.runs:
            for finding in _findings(run):
                items.append((run.project, finding, self.fingerprint(run.project, finding)))
        return tuple(items)

    def _filter_run(self, run: ProjectRun, existing: set[str]) -> ProjectRun:
        if not isinstance(run.value, Mapping) or "findings" not in run.value:
            return run
        findings = [
            dict(finding)
            for finding in _findings(run)
            if self.fingerprint(run.project, finding) not in existing
        ]
        value = dict(run.value)
        value["findings"] = findings
        value["baseline"] = {
            "new_count": len(findings),
            "existing_count": len(_findings(run)) - len(findings),
        }
        return replace(run, value=value)


def _findings(run: ProjectRun) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(run.value, Mapping):
        return ()
    raw = run.value.get("findings", ())
    if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Iterable):
        return ()
    return tuple(item for item in raw if isinstance(item, Mapping))


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
