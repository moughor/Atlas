from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping
import uuid


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    project: str
    targets: tuple[str, ...] = ()
    options: tuple[tuple[str, str], ...] = ()
    request_id: str = ""

    def __post_init__(self) -> None:
        if not self.project.strip():
            raise ValueError("project must not be empty")
        if any(not target.strip() for target in self.targets):
            raise ValueError("targets must not contain empty values")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AnalysisRequest":
        options = value.get("options", {})
        if options is None:
            options = {}
        if not isinstance(options, Mapping):
            raise ValueError("options must be an object")
        targets = value.get("targets", ()) or ()
        if isinstance(targets, str):
            raise ValueError("targets must be an array")
        return cls(
            project=str(value.get("project", "")),
            targets=tuple(str(item) for item in targets),
            options=tuple(sorted((str(k), str(v)) for k, v in options.items())),
            request_id=str(value.get("request_id", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {"project": self.project, "targets": list(self.targets), "options": dict(self.options)}
        if self.request_id:
            result["request_id"] = self.request_id
        return result


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    findings: tuple[Mapping[str, Any], ...] = ()
    metrics: tuple[tuple[str, int | float | str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"findings": [dict(item) for item in self.findings], "metrics": dict(self.metrics)}


@dataclass(slots=True)
class AnalysisJob:
    request: AnalysisRequest
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: JobStatus = JobStatus.PENDING
    result: AnalysisResult | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id, "status": self.status.value, "request": self.request.to_dict()}
        if self.result is not None:
            payload["result"] = self.result.to_dict()
        if self.error:
            payload["error"] = self.error
        return payload
