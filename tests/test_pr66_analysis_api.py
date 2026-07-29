from __future__ import annotations

import json
import pytest

from moughorai.api import AnalysisApiRouter, AnalysisApiService, AnalysisRequest, AnalysisResult, ApiError, JobStatus


def ids():
    value = 0
    def next_id():
        nonlocal value; value += 1; return f"job-{value}"
    return next_id


def analyzer(request):
    return {"findings":[{"message":request.project}], "metrics":{"targets":len(request.targets)}}


def test_request_requires_project():
    with pytest.raises(ValueError): AnalysisRequest("")

def test_request_rejects_empty_target():
    with pytest.raises(ValueError): AnalysisRequest("p", ("",))

def test_request_from_mapping():
    r=AnalysisRequest.from_mapping({"project":"p","targets":["a"],"options":{"b":2,"a":1}})
    assert r.options == (("a","1"),("b","2"))

def test_request_rejects_string_targets():
    with pytest.raises(ValueError): AnalysisRequest.from_mapping({"project":"p","targets":"a"})

def test_request_rejects_non_mapping_options():
    with pytest.raises(ValueError): AnalysisRequest.from_mapping({"project":"p","options":[]})

def test_submit_runs_by_default():
    job=AnalysisApiService(analyzer,id_factory=ids()).submit({"project":"p"})
    assert job.status == JobStatus.SUCCEEDED

def test_submit_pending():
    job=AnalysisApiService(analyzer,id_factory=ids()).submit({"project":"p"},run=False)
    assert job.status == JobStatus.PENDING

def test_run_pending():
    s=AnalysisApiService(analyzer,id_factory=ids()); job=s.submit({"project":"p"},run=False)
    assert s.run(job.id).result.metrics == (("targets",0),)

def test_result_object_passthrough():
    expected=AnalysisResult(metrics=(("x",1),))
    job=AnalysisApiService(lambda _: expected,id_factory=ids()).submit({"project":"p"})
    assert job.result is expected

def test_none_result():
    job=AnalysisApiService(lambda _: None,id_factory=ids()).submit({"project":"p"})
    assert job.result == AnalysisResult()

def test_iterable_result():
    job=AnalysisApiService(lambda _: ["a",{"message":"b"}],id_factory=ids()).submit({"project":"p"})
    assert job.result.findings[0] == {"message":"a"}

def test_failure_is_captured():
    def boom(_): raise RuntimeError("boom")
    job=AnalysisApiService(boom,id_factory=ids()).submit({"project":"p"})
    assert job.status == JobStatus.FAILED and job.error == "boom"

def test_get_missing():
    with pytest.raises(ApiError) as exc: AnalysisApiService(analyzer).get("x")
    assert exc.value.status_code == 404

def test_idempotent_request_id():
    s=AnalysisApiService(analyzer,id_factory=ids())
    a=s.submit({"project":"p","request_id":"r"}); b=s.submit({"project":"other","request_id":"r"})
    assert a is b

def test_duplicate_generated_id():
    s=AnalysisApiService(analyzer,id_factory=lambda:"x"); s.submit({"project":"p"})
    with pytest.raises(ApiError): s.submit({"project":"q"})

def test_list_sorted():
    values=iter(["b","a"]); s=AnalysisApiService(analyzer,id_factory=lambda:next(values))
    s.submit({"project":"p"}); s.submit({"project":"q"})
    assert [j.id for j in s.list()] == ["a","b"]

def test_list_filter():
    s=AnalysisApiService(analyzer,id_factory=ids()); s.submit({"project":"p"},run=False); s.submit({"project":"q"})
    assert len(s.list(status="pending")) == 1

def test_cancel_pending():
    s=AnalysisApiService(analyzer,id_factory=ids()); j=s.submit({"project":"p"},run=False)
    assert s.cancel(j.id).status == JobStatus.CANCELLED

def test_run_cancelled_rejected():
    s=AnalysisApiService(analyzer,id_factory=ids()); j=s.submit({"project":"p"},run=False); s.cancel(j.id)
    with pytest.raises(ApiError): s.run(j.id)

def test_cancel_completed_rejected():
    s=AnalysisApiService(analyzer,id_factory=ids()); j=s.submit({"project":"p"})
    with pytest.raises(ApiError): s.cancel(j.id)

def test_delete_job():
    s=AnalysisApiService(analyzer,id_factory=ids()); j=s.submit({"project":"p"}); s.delete(j.id)
    with pytest.raises(ApiError): s.get(j.id)

def test_delete_releases_request_id():
    s=AnalysisApiService(analyzer,id_factory=ids()); j=s.submit({"project":"p","request_id":"r"}); s.delete(j.id)
    assert s.submit({"project":"q","request_id":"r"}).request.project == "q"

def test_router_create():
    r=AnalysisApiRouter(AnalysisApiService(analyzer,id_factory=ids()))
    status,headers,body=r.handle("POST","/v1/analysis/jobs",json.dumps({"project":"p"}))
    assert status == 201 and headers["content-type"] == "application/json" and json.loads(body)["id"] == "job-1"

def test_router_create_pending():
    r=AnalysisApiRouter(AnalysisApiService(analyzer,id_factory=ids()))
    status,_,body=r.handle("POST","/v1/analysis/jobs",json.dumps({"project":"p","run":False}))
    assert json.loads(body)["status"] == "pending"

def test_router_get_and_run():
    r=AnalysisApiRouter(AnalysisApiService(analyzer,id_factory=ids()))
    r.handle("POST","/v1/analysis/jobs",json.dumps({"project":"p","run":False}))
    assert r.handle("POST","/v1/analysis/jobs/job-1/run")[0] == 200
    assert r.handle("GET","/v1/analysis/jobs/job-1")[0] == 200

def test_router_list():
    r=AnalysisApiRouter(AnalysisApiService(analyzer,id_factory=ids())); r.handle("POST","/v1/analysis/jobs",'{"project":"p"}')
    assert len(json.loads(r.handle("GET","/v1/analysis/jobs")[2])["jobs"]) == 1

def test_router_cancel():
    r=AnalysisApiRouter(AnalysisApiService(analyzer,id_factory=ids())); r.handle("POST","/v1/analysis/jobs",'{"project":"p","run":false}')
    assert json.loads(r.handle("POST","/v1/analysis/jobs/job-1/cancel")[2])["status"] == "cancelled"

def test_router_delete():
    r=AnalysisApiRouter(AnalysisApiService(analyzer,id_factory=ids())); r.handle("POST","/v1/analysis/jobs",'{"project":"p"}')
    assert r.handle("DELETE","/v1/analysis/jobs/job-1") == (204,{},"")

def test_router_invalid_json():
    assert AnalysisApiRouter(AnalysisApiService(analyzer)).handle("POST","/v1/analysis/jobs","{")[0] == 400

def test_router_unknown_route():
    assert AnalysisApiRouter(AnalysisApiService(analyzer)).handle("GET","/wat")[0] == 404

def test_job_to_dict_contains_result():
    job=AnalysisApiService(analyzer,id_factory=ids()).submit({"project":"p"})
    assert job.to_dict()["result"]["metrics"]["targets"] == 0
