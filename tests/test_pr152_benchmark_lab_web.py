from __future__ import annotations

import ast
from http.client import HTTPConnection
import json
from pathlib import Path
import threading

import pytest

import moughorai.benchmark_lab as lab_module
from moughorai.benchmark_lab import create_benchmark_lab_server


ROOT = Path(__file__).parents[1]
SERVER_MODULE = ROOT / "moughorai" / "benchmark_lab.py"
PAGE_MODULE = ROOT / "moughorai" / "benchmark_lab_page.py"
WORKSPACE_MODULE = ROOT / "moughorai" / "benchmark_lab_workspace.py"
FIXTURES = Path(__file__).parent / "fixtures" / "benchmark_intelligence"
HWBOT = FIXTURES / "hwbot_fire_strike_submission_v1.html"
UL = FIXTURES / "ul_3dmark_fire_strike_result_v1.html"
TOKEN = "test-only-pr152-token"


@pytest.fixture
def running_server():
    server = create_benchmark_lab_server(port=0, token=TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def _request(
    server,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    content_type: str | None = None,
    token: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    connection = HTTPConnection(*server.server_address, timeout=5)
    request_headers = dict(headers or {})
    if content_type is not None:
        request_headers["Content-Type"] = content_type
    if token is not None:
        request_headers["X-Atlas-Lab-Token"] = token
    connection.request(method, path, body=body, headers=request_headers)
    response = connection.getresponse()
    payload = response.read()
    result = response.status, dict(response.getheaders()), payload
    connection.close()
    return result


def _json_request(*args, **kwargs) -> tuple[int, dict[str, str], dict[str, object]]:
    status, headers, payload = _request(*args, **kwargs)
    return status, headers, json.loads(payload)


def _post_json(server, path: str, value: object, *, token: str | None = TOKEN):
    return _json_request(
        server,
        "POST",
        path,
        body=json.dumps(value, separators=(",", ":")).encode(),
        content_type="application/json",
        token=token,
    )


def test_page_is_hwbot_first_companion_workspace(running_server) -> None:
    status, _, payload = _request(running_server, "GET", "/")
    page = payload.decode()

    assert status == 200
    assert page.index("HWBOT WORKSPACE") < page.index("ATLAS INTELLIGENCE")
    assert "ATLAS SOURCE VIEW — NOT LIVE HWBOT" in page
    assert "HWBOT reference URL" in page
    assert "Current browser page" not in page
    assert "HWBOT framing is blocked" in page
    assert "Atlas does not fetch source URLs" in page


def test_page_has_dual_search_and_fixed_hwbot_actions(running_server) -> None:
    page = _request(running_server, "GET", "/")[2].decode()

    assert "HWBOT Search" in page
    assert "Atlas Search — Current session" in page
    for href in (
        "https://hwbot.org/",
        "https://hwbot.org/benchmarks/3dmark_-_fire_strike",
        "https://hwbot.org/benchmarks/3dmark_-_fire_strike/rankings",
        "https://hwbot.org/submissions",
        "https://hwbot.org/users",
    ):
        assert f'href="{href}"' in page
    assert page.count('rel="noopener noreferrer"') >= 8


def test_external_hwbot_search_is_safe_top_level_navigation() -> None:
    source = PAGE_MODULE.read_text(encoding="utf-8")

    assert 'new URL("/search", "https://hwbot.org")' in source
    assert 'searchParams.set("query"' in source
    assert 'window.open(url.href, "_blank", "noopener,noreferrer")' in source
    assert "local redirect" not in source.casefold()


def test_four_compact_sidecar_tabs_and_calculator_are_present() -> None:
    source = PAGE_MODULE.read_text(encoding="utf-8")

    for tab in ("ATLAS", "3DMARK", "COMPARE", "EVIDENCE"):
        assert f">{tab}</button>" in source
    for label in ("CURRENT", "WHAT IF", "+1% SENSITIVITY"):
        assert label in source
    assert "Largest modeled component-score effect" in source
    assert "+1% sensitivity, rounded up to a whole mark" in source
    assert "target score" not in source.casefold()


def test_page_never_frames_or_renders_third_party_html() -> None:
    source = PAGE_MODULE.read_text(encoding="utf-8")

    assert "<iframe" not in source.casefold()
    assert "innerHTML" not in source
    assert "document.write" not in source
    assert "textContent" in source
    assert "Raw captured HTML is never returned" in source
    assert "Open Elmor reference" in source


def test_navigation_detection_endpoint_is_nonsemantic(running_server) -> None:
    status, _, value = _post_json(
        running_server,
        "/api/v1/navigation/hwbot/detect",
        {
            "url": (
                "https://hwbot.org/benchmarks/3dmark_-_fire_strike/"
                "submissions/6026699?submission=1#2"
            )
        },
    )

    assert status == 200
    assert value["detection"]["authority"] == "navigation_only"
    assert value["detection"]["path_submission_segment"] == "6026699"
    assert value["detection"]["semantic_evidence"] is False
    assert "capture_sha256" not in value["detection"]
    state = _json_request(running_server, "GET", "/api/v1/state")[2]
    assert state["sources"]["hwbot"] is None


@pytest.mark.parametrize(
    "url",
    [
        "http://hwbot.org/",
        "https://user@hwbot.org/",
        "https://hwbot.org:8443/",
        "https://evil.example/",
        "https://hwbot.org/%2f%2fevil.example/",
    ],
)
def test_navigation_endpoint_rejects_hostile_urls(running_server, url: str) -> None:
    status, _, value = _post_json(
        running_server,
        "/api/v1/navigation/hwbot/detect",
        {"url": url},
    )

    assert status == 422
    assert len(value["error"]) < 160


def test_url_capture_mismatch_warns_without_mutating_evidence(running_server) -> None:
    status, _, state = _request(
        running_server,
        "POST",
        "/api/v1/captures/hwbot",
        body=HWBOT.read_bytes(),
        content_type="text/html",
        token=TOKEN,
    )
    assert status == 200
    assert json.loads(state)["sources"]["hwbot"]["native_submission_identifier"] == "1480001"

    status, _, detected = _post_json(
        running_server,
        "/api/v1/navigation/hwbot/detect",
        {
            "url": (
                "https://hwbot.org/benchmarks/3dmark_-_fire_strike/"
                "submissions/6026699"
            )
        },
    )

    assert status == 200
    assert detected["capture_comparison"]["matches_parsed_capture"] is False
    assert detected["capture_comparison"]["parsed_native_submission_identifier"] == "1480001"
    assert "differs" in detected["capture_comparison"]["warning"]


def test_current_session_search_endpoint_is_bounded_and_ordered(running_server) -> None:
    for route, fixture in (
        ("/api/v1/captures/hwbot", HWBOT),
        ("/api/v1/captures/ul-3dmark", UL),
    ):
        assert _request(
            running_server,
            "POST",
            route,
            body=fixture.read_bytes(),
            content_type="text/html",
            token=TOKEN,
        )[0] == 200

    status, _, value = _post_json(
        running_server,
        "/api/v1/search/current-session",
        {"query": "fire-strike-standard"},
    )

    assert status == 200
    assert [item["source_key"] for item in value["results"]] == ["hwbot", "ul_3dmark"]
    assert len(value["results"]) == 2
    assert value["scope"] == "current_session"


def test_empty_search_state_and_oversized_query_are_explicit(running_server) -> None:
    status, _, empty = _post_json(
        running_server,
        "/api/v1/search/current-session",
        {"query": "fire strike"},
    )
    assert status == 200
    assert empty["results"] == []

    status, _, oversized = _post_json(
        running_server,
        "/api/v1/search/current-session",
        {"query": "x" * 129},
    )
    assert status == 422
    assert "128" in oversized["error"]


def test_calculation_returns_atomic_pr150_and_sensitivity_result(running_server) -> None:
    payload = {
        "baseline": {
            "graphics_score": "22447",
            "physics_score": "56270",
            "combined_score": "7668",
        },
        "candidate": {
            "graphics_score": "23000",
            "physics_score": "56270",
            "combined_score": "7668",
        },
    }

    status, _, value = _post_json(
        running_server,
        "/api/v1/calculations/fire-strike",
        payload,
    )

    assert status == 200
    assert value["baseline"]["overall_score"] == "20358"
    assert value["sensitivity"]["baseline"] == value["baseline"]
    assert [item["overall_delta"] for item in value["sensitivity"]["scenarios"]] == [
        "139",
        "11",
        "54",
    ]
    assert value["sensitivity"]["largest_delta_components"] == ["graphics_score"]


def test_rounded_negative_zero_is_presented_as_zero(running_server) -> None:
    payload = {
        "baseline": {
            "graphics_score": "1000000",
            "physics_score": "1000000",
            "combined_score": "1000000",
        },
        "candidate": {
            "graphics_score": "999990",
            "physics_score": "1000000",
            "combined_score": "1000000",
        },
    }

    status, _, value = _post_json(
        running_server,
        "/api/v1/calculations/fire-strike",
        payload,
    )

    assert status == 200
    assert int(value["delta_score"]) < 0
    assert value["percentage_delta"] == "0.00"


def test_client_has_stale_response_suppression_and_atomic_snapshot() -> None:
    source = PAGE_MODULE.read_text(encoding="utf-8")

    assert "AbortController" in source
    assert "generation" in source
    assert "isCurrent(request)" in source
    assert 'beginRequest("state")' in source
    assert 'beginRequest("search")' in source
    assert 'beginRequest("detect")' in source
    assert 'beginRequest("calculation")' in source
    assert "const snapshot = Object.freeze" in source
    assert 'signal: request.controller.signal' in source
    assert 'addEventListener("input", clearCalculation)' in source


@pytest.mark.parametrize(
    ("source", "parser_name", "first", "second", "expected"),
    [
        (
            "hwbot",
            "parse_hwbot_fire_strike_submission",
            HWBOT.read_bytes(),
            HWBOT.read_bytes().replace(b"1480001", b"1480002"),
            "1480002",
        ),
        (
            "ul",
            "parse_ul_3dmark_fire_strike_submission",
            UL.read_bytes(),
            UL.read_bytes().replace(b"90000001", b"90000002"),
            "90000002",
        ),
    ],
)
def test_older_upload_cannot_overwrite_newer_source_intent(
    monkeypatch,
    source: str,
    parser_name: str,
    first: bytes,
    second: bytes,
    expected: str,
) -> None:
    state = lab_module.BenchmarkLabState()
    original = getattr(lab_module, parser_name)
    started = threading.Event()
    release = threading.Event()
    responses: list[dict[str, object]] = []

    def delayed(capture):
        if capture.payload == first:
            started.set()
            assert release.wait(timeout=5)
        return original(capture)

    monkeypatch.setattr(lab_module, parser_name, delayed)
    ingest = state.ingest_hwbot if source == "hwbot" else state.ingest_ul
    thread = threading.Thread(target=lambda: responses.append(ingest(first)))
    thread.start()
    assert started.wait(timeout=5)

    newer = ingest(second)
    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()

    key = "hwbot" if source == "hwbot" else "ul_3dmark"
    assert newer["sources"][key]["native_submission_identifier"] == expected
    assert responses[0]["sources"][key]["native_submission_identifier"] == expected
    assert state.to_dict()["sources"][key]["native_submission_identifier"] == expected


@pytest.mark.parametrize(
    ("source", "parser_name", "payload"),
    [
        ("hwbot", "parse_hwbot_fire_strike_submission", HWBOT.read_bytes()),
        ("ul", "parse_ul_3dmark_fire_strike_submission", UL.read_bytes()),
    ],
)
def test_reset_invalidates_inflight_upload(
    monkeypatch,
    source: str,
    parser_name: str,
    payload: bytes,
) -> None:
    state = lab_module.BenchmarkLabState()
    original = getattr(lab_module, parser_name)
    started = threading.Event()
    release = threading.Event()
    responses: list[dict[str, object]] = []

    def delayed(capture):
        started.set()
        assert release.wait(timeout=5)
        return original(capture)

    monkeypatch.setattr(lab_module, parser_name, delayed)
    ingest = state.ingest_hwbot if source == "hwbot" else state.ingest_ul
    thread = threading.Thread(target=lambda: responses.append(ingest(payload)))
    thread.start()
    assert started.wait(timeout=5)

    assert state.reset()["sources"] == {"hwbot": None, "ul_3dmark": None}
    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()

    assert responses[0]["sources"] == {"hwbot": None, "ul_3dmark": None}
    assert state.to_dict()["sources"] == {"hwbot": None, "ul_3dmark": None}


def test_new_routes_preserve_token_origin_content_type_and_host_boundaries(
    running_server,
) -> None:
    route = "/api/v1/search/current-session"
    payload = b'{"query":"x"}'

    assert _request(
        running_server,
        "POST",
        route,
        body=payload,
        content_type="application/json",
    )[0] == 403
    assert _request(
        running_server,
        "POST",
        route,
        body=payload,
        content_type="text/plain",
        token=TOKEN,
    )[0] == 415
    assert _request(
        running_server,
        "POST",
        route,
        body=payload,
        content_type="application/json",
        token=TOKEN,
        headers={"Origin": "https://evil.example"},
    )[0] == 403
    assert _request(
        running_server,
        "POST",
        route,
        body=payload,
        content_type="application/json",
        token=TOKEN,
        headers={"Host": "evil.example"},
    )[0] == 400


def test_new_endpoints_have_no_cors_proxy_redirect_or_network_acquisition() -> None:
    server = SERVER_MODULE.read_text(encoding="utf-8")
    workspace = WORKSPACE_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(workspace)

    assert "/proxy" not in server
    assert "Access-Control-Allow-Origin" not in server
    assert "Location" not in server
    assert "urlopen" not in server + workspace
    assert "requests" not in server + workspace
    assert "httpx" not in server + workspace
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) and "socket" in ast.unparse(node) for node in ast.walk(tree))


def test_security_headers_remain_singleton_on_new_routes(running_server) -> None:
    status, headers, _ = _post_json(
        running_server,
        "/api/v1/search/current-session",
        {"query": "x"},
    )

    assert status == 200
    for name in (
        "Content-Security-Policy",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Cache-Control",
        "Cross-Origin-Opener-Policy",
    ):
        assert name in headers
    assert headers["X-Frame-Options"] == "DENY"


def test_comparison_wording_does_not_claim_run_linkage() -> None:
    source = PAGE_MODULE.read_text(encoding="utf-8")

    assert "Run linkage unknown" in source
    assert "Equal scores mean agreement only" in source
    assert "same physical run" not in source.casefold()


def test_no_scoring_formula_is_copied_into_client() -> None:
    source = PAGE_MODULE.read_text(encoding="utf-8")

    for forbidden in ("0.75", "0.15", "0.10", "15 * physics", "weighted-harmonic"):
        assert forbidden not in source
    assert "/api/v1/calculations/fire-strike" in source
