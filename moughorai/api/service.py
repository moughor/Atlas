from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Mapping

from .models import AnalysisJob, AnalysisRequest, AnalysisResult, JobStatus


class ApiError(ValueError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class AnalysisApiService:
    def __init__(self, analyzer: Callable[[AnalysisRequest], Any], *, id_factory: Callable[[], str] | None = None) -> None:
        self._analyzer = analyzer
        self._id_factory = id_factory
        self._jobs: dict[str, AnalysisJob] = {}
        self._request_ids: dict[str, str] = {}

    def submit(self, request: AnalysisRequest | Mapping[str, Any], *, run: bool = True) -> AnalysisJob:
        parsed = request if isinstance(request, AnalysisRequest) else AnalysisRequest.from_mapping(request)
        if parsed.request_id and parsed.request_id in self._request_ids:
            return self._jobs[self._request_ids[parsed.request_id]]
        job = AnalysisJob(parsed)
        if self._id_factory is not None:
            job.id = self._id_factory()
        if job.id in self._jobs:
            raise ApiError(409, f"duplicate job id: {job.id}")
        self._jobs[job.id] = job
        if parsed.request_id:
            self._request_ids[parsed.request_id] = job.id
        if run:
            self.run(job.id)
        return job

    def run(self, job_id: str) -> AnalysisJob:
        job = self.get(job_id)
        if job.status == JobStatus.CANCELLED:
            raise ApiError(409, "cancelled jobs cannot be run")
        if job.status in {JobStatus.RUNNING, JobStatus.SUCCEEDED}:
            return job
        job.status = JobStatus.RUNNING
        try:
            raw = self._analyzer(job.request)
            job.result = self._normalize_result(raw)
            job.status = JobStatus.SUCCEEDED
            job.error = ""
        except Exception as exc:
            job.status = JobStatus.FAILED
            job.error = str(exc) or exc.__class__.__name__
        return job

    def get(self, job_id: str) -> AnalysisJob:
        try:
            return self._jobs[job_id]
        except KeyError as exc:
            raise ApiError(404, f"job not found: {job_id}") from exc

    def list(self, *, status: JobStatus | str | None = None) -> tuple[AnalysisJob, ...]:
        expected = JobStatus(status) if status is not None else None
        jobs = (job for job in self._jobs.values() if expected is None or job.status == expected)
        return tuple(sorted(jobs, key=lambda job: job.id))

    def cancel(self, job_id: str) -> AnalysisJob:
        job = self.get(job_id)
        if job.status == JobStatus.RUNNING:
            raise ApiError(409, "running jobs cannot be cancelled synchronously")
        if job.status == JobStatus.SUCCEEDED:
            raise ApiError(409, "completed jobs cannot be cancelled")
        job.status = JobStatus.CANCELLED
        return job

    def delete(self, job_id: str) -> None:
        job = self.get(job_id)
        if job.status == JobStatus.RUNNING:
            raise ApiError(409, "running jobs cannot be deleted")
        del self._jobs[job_id]
        if job.request.request_id:
            self._request_ids.pop(job.request.request_id, None)

    @staticmethod
    def _normalize_result(raw: Any) -> AnalysisResult:
        if isinstance(raw, AnalysisResult):
            return raw
        if raw is None:
            return AnalysisResult()
        if isinstance(raw, Mapping):
            findings = raw.get("findings", ()) or ()
            metrics = raw.get("metrics", {}) or {}
            if not isinstance(metrics, Mapping):
                raise ValueError("result metrics must be an object")
            return AnalysisResult(tuple(dict(item) for item in findings), tuple(sorted(metrics.items())))
        return AnalysisResult(tuple(dict(item) if isinstance(item, Mapping) else {"message": str(item)} for item in raw))


class AnalysisApiRouter:
    def __init__(self, service: AnalysisApiService) -> None:
        self.service = service

    def handle(self, method: str, path: str, body: str = "") -> tuple[int, dict[str, str], str]:
        try:
            payload = json.loads(body) if body else {}
            if method == "POST" and path == "/v1/analysis/jobs":
                job = self.service.submit(payload, run=bool(payload.pop("run", True)))
                return self._json(201, job.to_dict())
            if method == "GET" and path == "/v1/analysis/jobs":
                return self._json(200, {"jobs": [job.to_dict() for job in self.service.list()]})
            prefix = "/v1/analysis/jobs/"
            if path.startswith(prefix):
                suffix = path[len(prefix):]
                job_id, _, action = suffix.partition("/")
                if method == "GET" and not action:
                    return self._json(200, self.service.get(job_id).to_dict())
                if method == "POST" and action == "run":
                    return self._json(200, self.service.run(job_id).to_dict())
                if method == "POST" and action == "cancel":
                    return self._json(200, self.service.cancel(job_id).to_dict())
                if method == "DELETE" and not action:
                    self.service.delete(job_id)
                    return 204, {}, ""
            raise ApiError(404, f"route not found: {method} {path}")
        except json.JSONDecodeError as exc:
            return self._json(400, {"error": f"invalid JSON: {exc.msg}"})
        except ApiError as exc:
            return self._json(exc.status_code, {"error": exc.message})
        except (TypeError, ValueError, KeyError) as exc:
            return self._json(400, {"error": str(exc)})

    @staticmethod
    def _json(status: int, payload: Mapping[str, Any]) -> tuple[int, dict[str, str], str]:
        return status, {"content-type": "application/json"}, json.dumps(payload, sort_keys=True, separators=(",", ":"))
