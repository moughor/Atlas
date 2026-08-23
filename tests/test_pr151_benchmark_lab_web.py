from __future__ import annotations

import ast
from http.client import HTTPConnection
import json
from pathlib import Path
import socket
import threading

import pytest

from moughorai.benchmark_lab import (
    BENCHMARK_LAB_HOST,
    MAX_CAPTURE_BYTES,
    BenchmarkLabState,
    create_benchmark_lab_server,
    main,
)


ROOT = Path(__file__).parents[1]
MODULE = ROOT / "moughorai" / "benchmark_lab.py"
PAGE_MODULE = ROOT / "moughorai" / "benchmark_lab_page.py"
FIXTURES = Path(__file__).parent / "fixtures" / "benchmark_intelligence"
HWBOT = FIXTURES / "hwbot_fire_strike_submission_v1.html"
UL = FIXTURES / "ul_3dmark_fire_strike_result_v1.html"
TOKEN = "test-only-benchmark-lab-token"


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
    result = response.status, {key: value for key, value in response.getheaders()}, payload
    connection.close()
    return result


def _json_request(*args, **kwargs) -> tuple[int, dict[str, str], dict[str, object]]:
    status, headers, payload = _request(*args, **kwargs)
    return status, headers, json.loads(payload)


def _calculation_body() -> bytes:
    return json.dumps(
        {
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
        },
        separators=(",", ":"),
    ).encode()


def _raw_request(server, lines: list[bytes]) -> tuple[int, bytes]:
    with socket.create_connection(server.server_address, timeout=5) as client:
        client.sendall(b"\r\n".join(lines) + b"\r\n\r\n")
        response = b""
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            response += chunk
    status = int(response.split(b" ", 2)[1])
    return status, response


def test_server_binds_only_to_ipv4_loopback(running_server) -> None:
    assert running_server.server_address[0] == BENCHMARK_LAB_HOST == "127.0.0.1"
    assert running_server.server_address[1] > 0


def test_page_assets_and_initial_state_are_served(running_server) -> None:
    status, _, page = _request(running_server, "GET", "/")
    css_status, _, css = _request(running_server, "GET", "/app.css")
    js_status, _, javascript = _request(running_server, "GET", "/app.js")
    state_status, _, state = _json_request(running_server, "GET", "/api/v1/state")

    assert (status, css_status, js_status, state_status) == (200, 200, 200, 200)
    assert b"Atlas AI OC" in page
    assert b"Benchmark Lab" in page
    assert TOKEN.encode() in page
    assert b"--cyan" in css
    assert b"File.arrayBuffer" not in javascript
    assert b"arrayBuffer" in javascript
    assert state == {
        "comparison": None,
        "schema_version": 1,
        "sources": {"hwbot": None, "ul_3dmark": None},
    }


@pytest.mark.parametrize("path", ["/", "/app.css", "/app.js", "/api/v1/state"])
def test_every_get_response_has_local_security_headers(running_server, path: str) -> None:
    status, headers, _ = _request(running_server, "GET", path)

    assert status == 200
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["Cache-Control"] == "no-store"
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    assert "Access-Control-Allow-Origin" not in headers


def test_post_requires_process_token(running_server) -> None:
    status, _, value = _json_request(
        running_server,
        "POST",
        "/api/v1/reset",
        body=b"{}",
        content_type="application/json",
    )

    assert status == 403
    assert value["error"] == "Benchmark Lab request token is invalid"


def test_post_rejects_mismatched_origin(running_server) -> None:
    status, _, value = _json_request(
        running_server,
        "POST",
        "/api/v1/reset",
        body=b"{}",
        content_type="application/json",
        token=TOKEN,
        headers={"Origin": "https://attacker.example"},
    )

    assert status == 403
    assert "Origin" in value["error"]


@pytest.mark.parametrize(
    "duplicate_headers",
    [
        [b"Host: localhost", b"Host: attacker.example"],
        [b"Origin: http://localhost", b"Origin: https://attacker.example"],
        [
            b"X-Atlas-Lab-Token: " + TOKEN.encode(),
            b"X-Atlas-Lab-Token: attacker",
        ],
        [b"Content-Type: application/json", b"Content-Type: text/html"],
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_boundary_headers_are_rejected_independent_of_order(
    running_server,
    duplicate_headers: list[bytes],
    reverse: bool,
) -> None:
    headers = list(reversed(duplicate_headers)) if reverse else duplicate_headers
    defaults = [
        b"Host: localhost:" + str(running_server.server_address[1]).encode(),
        b"Origin: http://localhost:" + str(running_server.server_address[1]).encode(),
        b"X-Atlas-Lab-Token: " + TOKEN.encode(),
        b"Content-Type: application/json",
    ]
    duplicate_name = headers[0].split(b":", 1)[0].lower()
    defaults = [line for line in defaults if line.split(b":", 1)[0].lower() != duplicate_name]
    status, _ = _raw_request(
        running_server,
        [
            b"POST /api/v1/reset HTTP/1.1",
            *defaults,
            *headers,
            b"Content-Length: 2",
            b"Connection: close",
            b"",
            b"{}",
        ],
    )

    assert status in {400, 403}


def test_non_ascii_token_header_is_bounded_rejection(running_server, capfd) -> None:
    status, response = _raw_request(
        running_server,
        [
            b"POST /api/v1/reset HTTP/1.1",
            b"Host: localhost:" + str(running_server.server_address[1]).encode(),
            b"Content-Type: application/json",
            b"X-Atlas-Lab-Token: \xff",
            b"Content-Length: 2",
            b"Connection: close",
            b"",
            b"{}",
        ],
    )

    assert status == 403
    assert b"request token is invalid" in response
    assert "Traceback" not in capfd.readouterr().err


def test_get_rejects_non_loopback_host_header(running_server) -> None:
    connection = HTTPConnection(*running_server.server_address, timeout=5)
    connection.putrequest("GET", "/api/v1/state", skip_host=True)
    connection.putheader("Host", "attacker.example")
    connection.endheaders()
    response = connection.getresponse()
    value = json.loads(response.read())
    connection.close()

    assert response.status == 400
    assert "loopback" in value["error"]


@pytest.mark.parametrize(
    ("route", "fixture", "source_key", "native_id"),
    [
        ("hwbot", HWBOT, "hwbot", "1480001"),
        ("ul-3dmark", UL, "ul_3dmark", "90000001"),
    ],
)
def test_raw_capture_upload_uses_exact_bytes(
    running_server,
    route: str,
    fixture: Path,
    source_key: str,
    native_id: str,
) -> None:
    payload = fixture.read_bytes()
    status, _, value = _json_request(
        running_server,
        "POST",
        f"/api/v1/captures/{route}",
        body=payload,
        content_type="text/html",
        token=TOKEN,
    )

    assert status == 200
    assert value["sources"][source_key]["native_submission_identifier"] == native_id
    assert len(value["sources"][source_key]["capture_sha256"]) == 64
    assert payload.decode() not in json.dumps(value)


def test_loading_both_sources_returns_comparison(running_server) -> None:
    for route, fixture in (("hwbot", HWBOT), ("ul-3dmark", UL)):
        status, _, _ = _json_request(
            running_server,
            "POST",
            f"/api/v1/captures/{route}",
            body=fixture.read_bytes(),
            content_type="text/html",
            token=TOKEN,
        )
        assert status == 200

    _, _, state = _json_request(running_server, "GET", "/api/v1/state")
    assert state["comparison"]["fields"]["overall_score"]["state"] == "agreement"
    assert state["comparison"]["run_linkage"] == "unknown"


def test_failed_upload_does_not_replace_previous_evidence(running_server) -> None:
    valid_status, _, valid = _json_request(
        running_server,
        "POST",
        "/api/v1/captures/ul-3dmark",
        body=UL.read_bytes(),
        content_type="text/html",
        token=TOKEN,
    )
    failed_status, _, failure = _json_request(
        running_server,
        "POST",
        "/api/v1/captures/ul-3dmark",
        body=b"<script>secret-source-content</script>",
        content_type="text/html",
        token=TOKEN,
    )
    _, _, after = _json_request(running_server, "GET", "/api/v1/state")

    assert valid_status == 200
    assert failed_status == 422
    assert failure["error"] == "capture does not satisfy the supported source contract"
    assert "secret-source-content" not in json.dumps(failure)
    assert after == valid


def test_calculator_route_delegates_to_pr150(running_server) -> None:
    status, _, value = _json_request(
        running_server,
        "POST",
        "/api/v1/calculations/fire-strike",
        body=_calculation_body(),
        content_type="application/json",
        token=TOKEN,
    )

    assert status == 200
    assert value["baseline"]["overall_score"] == "20358"
    assert value["baseline"]["method_id"].endswith("integral-components-v1")
    assert value["candidate"]["overall_score"] != "20358"
    assert value["delta_score"] != "0"


def test_calculator_error_is_bounded_and_does_not_echo_input(running_server) -> None:
    payload = _calculation_body().replace(b'"22447"', b'"secret-invalid"')
    status, _, value = _json_request(
        running_server,
        "POST",
        "/api/v1/calculations/fire-strike",
        body=payload,
        content_type="application/json",
        token=TOKEN,
    )

    assert status == 422
    assert "secret-invalid" not in json.dumps(value)
    assert len(value["error"]) < 160


def test_reset_route_clears_state(running_server) -> None:
    _json_request(
        running_server,
        "POST",
        "/api/v1/captures/ul-3dmark",
        body=UL.read_bytes(),
        content_type="text/html",
        token=TOKEN,
    )
    status, _, state = _json_request(
        running_server,
        "POST",
        "/api/v1/reset",
        body=b"{}",
        content_type="application/json",
        token=TOKEN,
    )

    assert status == 200
    assert state["sources"] == {"hwbot": None, "ul_3dmark": None}


def test_exact_content_types_are_required(running_server) -> None:
    status, _, value = _json_request(
        running_server,
        "POST",
        "/api/v1/captures/hwbot",
        body=HWBOT.read_bytes(),
        content_type="text/html; charset=utf-8",
        token=TOKEN,
    )

    assert status == 415
    assert value["error"] == "Content-Type must be text/html"


def test_transfer_encoding_is_rejected(running_server) -> None:
    status, _, value = _json_request(
        running_server,
        "POST",
        "/api/v1/reset",
        body=b"{}",
        content_type="application/json",
        token=TOKEN,
        headers={"Transfer-Encoding": "chunked"},
    )

    assert status == 400
    assert value["error"] == "transfer encoding is unsupported"


def test_missing_content_length_is_rejected(running_server) -> None:
    connection = HTTPConnection(*running_server.server_address, timeout=5)
    connection.putrequest("POST", "/api/v1/reset")
    connection.putheader("Content-Type", "application/json")
    connection.putheader("X-Atlas-Lab-Token", TOKEN)
    connection.endheaders()
    response = connection.getresponse()
    value = json.loads(response.read())
    connection.close()

    assert response.status == 411
    assert "Content-Length" in value["error"]


def test_oversized_body_is_rejected_before_read(running_server) -> None:
    connection = HTTPConnection(*running_server.server_address, timeout=5)
    connection.putrequest("POST", "/api/v1/captures/hwbot")
    connection.putheader("Content-Type", "text/html")
    connection.putheader("X-Atlas-Lab-Token", TOKEN)
    connection.putheader("Content-Length", str(MAX_CAPTURE_BYTES + 1))
    connection.endheaders()
    response = connection.getresponse()
    value = json.loads(response.read())
    connection.close()

    assert response.status == 413
    assert value["error"] == "request body is too large"


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
def test_unsupported_methods_return_405(running_server, method: str) -> None:
    status, headers, _ = _request(running_server, method, "/api/v1/state")

    assert status == 405
    assert headers["Allow"] == "GET, POST"


def test_unknown_routes_return_404_without_filesystem_fallback(running_server) -> None:
    status, _, value = _json_request(running_server, "GET", "/../../pyproject.toml")

    assert status == 404
    assert value["error"] == "route not found"


def test_page_never_frames_or_renders_third_party_html() -> None:
    page = PAGE_MODULE.read_text(encoding="utf-8")

    assert "<iframe" not in page.casefold()
    assert "innerHTML" not in page
    assert "document.write" not in page
    assert "Open Elmor reference" in page
    assert "Atlas does not fetch source URLs" in page
    assert 'rel="noopener noreferrer"' in page
    assert "textContent" in page


def test_web_adapter_has_no_external_dependency_or_acquisition_client() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
    )

    assert imports <= {
        "__future__",
        "argparse",
        "collections",
        "dataclasses",
        "http",
        "html",
        "json",
        "re",
        "secrets",
        "threading",
        "webbrowser",
        "moughorai",
    }
    source = MODULE.read_text(encoding="utf-8")
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "open"
        for node in ast.walk(tree)
    )
    for prohibited in (
        "SimpleHTTPRequestHandler",
        "httpx",
        "requests",
        "urlopen",
        "Path(",
        "0.0.0.0",
    ):
        assert prohibited not in source


def test_cli_help_exposes_port_and_no_browser_without_starting_server(capsys) -> None:
    with pytest.raises(SystemExit) as captured:
        main(["--help"])

    assert captured.value.code == 0
    output = capsys.readouterr().out
    assert "--port" in output
    assert "--no-browser" in output
    assert "--host" not in output


@pytest.mark.parametrize("port", [-1, 65536, True, "8765"])
def test_server_factory_rejects_unsafe_or_ambiguous_ports(port: object) -> None:
    expected = TypeError if isinstance(port, (bool, str)) else ValueError
    with pytest.raises(expected):
        create_benchmark_lab_server(port=port, token=TOKEN)  # type: ignore[arg-type]


def test_server_state_does_not_retain_raw_payload_attribute() -> None:
    state = BenchmarkLabState()
    state.ingest_ul(UL.read_bytes())

    assert not hasattr(state, "payload")
    assert not hasattr(state, "capture")
    assert UL.read_bytes() not in repr(state).encode()
