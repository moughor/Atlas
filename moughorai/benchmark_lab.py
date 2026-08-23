"""Local-only Atlas AI OC Benchmark Lab V0 web adapter."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import html
import json
import re
import secrets
import threading
import webbrowser

from moughorai.benchmark_lab_page import PAGE_CSS, PAGE_HTML, PAGE_JS, TOKEN_PLACEHOLDER
from moughorai.domains.benchmark import (
    CapturedSourceV1,
    FireStrikeSubmissionV1,
    calculate_fire_strike_score,
    canonical_json_bytes,
    compare_fire_strike_sources,
    parse_hwbot_fire_strike_submission,
    parse_ul_3dmark_fire_strike_submission,
)


BENCHMARK_LAB_SCHEMA_VERSION = 1
BENCHMARK_LAB_HOST = "127.0.0.1"
BENCHMARK_LAB_DEFAULT_PORT = 8765
MAX_CAPTURE_BYTES = 32 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024
MAX_SCORE_DIGITS = 1000
_CONTENT_LENGTH = re.compile(r"^(?:0|[1-9][0-9]*)$")
_REQUEST_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")
_SCORE_FIELDS = {"graphics_score", "physics_score", "combined_score"}


class BenchmarkLabRequestError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _source_projection(submission: FireStrikeSubmissionV1) -> dict[str, object]:
    if submission.source_identifier == "source:hwbot":
        open_original = (
            "https://hwbot.org/benchmarks/3dmark_-_fire_strike/submissions/"
            f"{submission.native_submission_identifier}"
        )
    elif submission.source_identifier == "source:ul-3dmark-results":
        open_original = (
            f"https://www.3dmark.com/fs/{submission.native_submission_identifier}"
        )
    else:  # Defensive: only the two source-specific parsers feed the V0 lab.
        raise ValueError("unsupported Benchmark Lab source")
    return {
        "benchmark_id": submission.benchmark_id,
        "canonical_sha256": submission.canonical_sha256,
        "capture_sha256": submission.overall_score.capture_sha256,
        "native_submission_identifier": submission.native_submission_identifier,
        "open_original_url": open_original,
        "scores": {
            "combined_score": submission.combined_score.to_dict(),
            "graphics_score": submission.graphics_score.to_dict(),
            "overall_score": submission.overall_score.to_dict(),
            "physics_score": submission.physics_score.to_dict(),
        },
        "source_identifier": submission.source_identifier,
        "submission_id": submission.submission_id,
    }


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BenchmarkLabRequestError(400, "JSON contains a duplicate field")
        result[key] = value
    return result


def _json_mapping(payload: bytes) -> Mapping[str, object]:
    try:
        decoded = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_json_object)
    except BenchmarkLabRequestError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BenchmarkLabRequestError(400, "request body must be valid UTF-8 JSON") from error
    if not isinstance(decoded, Mapping):
        raise BenchmarkLabRequestError(400, "request JSON must be an object")
    return decoded


def _score_set(value: object, label: str) -> tuple[str, str, str]:
    if not isinstance(value, Mapping):
        raise BenchmarkLabRequestError(400, f"{label} must be an object")
    fields = set(value)
    if fields != _SCORE_FIELDS:
        raise BenchmarkLabRequestError(
            400,
            f"{label} must contain exactly graphics_score, physics_score, combined_score",
        )
    result: list[str] = []
    for field in ("graphics_score", "physics_score", "combined_score"):
        item = value[field]
        if not isinstance(item, str):
            raise BenchmarkLabRequestError(400, f"{label} {field} must be a string")
        if len(item) > MAX_SCORE_DIGITS:
            raise BenchmarkLabRequestError(413, f"{label} component score is too large")
        result.append(item)
    return result[0], result[1], result[2]


def _percentage_text(delta: int, baseline: int) -> str:
    sign = "-" if delta < 0 else ""
    quotient, remainder = divmod(abs(delta) * 10_000, baseline)
    if remainder * 2 >= baseline:
        quotient += 1
    whole, fraction = divmod(quotient, 100)
    return f"{sign}{whole}.{fraction:02d}"


@dataclass(slots=True)
class BenchmarkLabState:
    """Bounded in-memory parsed state; raw capture bytes are never retained."""

    _hwbot: FireStrikeSubmissionV1 | None = None
    _ul: FireStrikeSubmissionV1 | None = None
    _lock: threading.RLock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = threading.RLock()

    def ingest_hwbot(self, payload: bytes) -> dict[str, object]:
        capture = CapturedSourceV1(
            payload=payload,
            source_identifier="source:hwbot",
            media_type="text/html",
        )
        parsed = parse_hwbot_fire_strike_submission(capture)
        with self._lock:
            self._hwbot = parsed
            return self.to_dict()

    def ingest_ul(self, payload: bytes) -> dict[str, object]:
        capture = CapturedSourceV1(
            payload=payload,
            source_identifier="source:ul-3dmark-results",
            media_type="text/html",
        )
        parsed = parse_ul_3dmark_fire_strike_submission(capture)
        with self._lock:
            self._ul = parsed
            return self.to_dict()

    def reset(self) -> dict[str, object]:
        with self._lock:
            self._hwbot = None
            self._ul = None
            return self.to_dict()

    def to_dict(self) -> dict[str, object]:
        with self._lock:
            comparison = (
                compare_fire_strike_sources(self._hwbot, self._ul).to_dict()
                if self._hwbot is not None and self._ul is not None
                else None
            )
            return {
                "comparison": comparison,
                "schema_version": BENCHMARK_LAB_SCHEMA_VERSION,
                "sources": {
                    "hwbot": (
                        _source_projection(self._hwbot)
                        if self._hwbot is not None
                        else None
                    ),
                    "ul_3dmark": (
                        _source_projection(self._ul) if self._ul is not None else None
                    ),
                },
            }

    def calculate(self, payload: bytes) -> dict[str, object]:
        request = _json_mapping(payload)
        if set(request) != {"baseline", "candidate"}:
            raise BenchmarkLabRequestError(
                400, "calculation must contain exactly baseline and candidate"
            )
        baseline_values = _score_set(request["baseline"], "baseline")
        candidate_values = _score_set(request["candidate"], "candidate")
        try:
            baseline = calculate_fire_strike_score(*baseline_values)
            candidate = calculate_fire_strike_score(*candidate_values)
        except (TypeError, ValueError) as error:
            raise BenchmarkLabRequestError(422, str(error)) from error
        delta = candidate.overall_score - baseline.overall_score
        return {
            "baseline": baseline.to_dict(),
            "candidate": candidate.to_dict(),
            "delta_score": str(delta),
            "percentage_delta": _percentage_text(delta, baseline.overall_score),
            "percentage_rounding": "nearest-hundredth-half-up",
            "schema_version": BENCHMARK_LAB_SCHEMA_VERSION,
        }


class BenchmarkLabApplication:
    def __init__(self, *, token: str | None = None) -> None:
        self.token = token if token is not None else secrets.token_urlsafe(32)
        if (
            not isinstance(self.token, str)
            or _REQUEST_TOKEN.fullmatch(self.token) is None
        ):
            raise ValueError("Benchmark Lab token must be non-empty URL-safe ASCII text")
        self.state = BenchmarkLabState()

    @property
    def page(self) -> bytes:
        safe_token = html.escape(self.token, quote=True)
        return PAGE_HTML.replace(TOKEN_PLACEHOLDER, safe_token).encode("utf-8")


class _BenchmarkLabServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class BenchmarkLabHandler(BaseHTTPRequestHandler):
    application: BenchmarkLabApplication
    server_version = "AtlasBenchmarkLab/0"
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:
        return

    def _security_headers(self) -> None:
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")

    def _send(self, status: int, content_type: str, payload: bytes) -> None:
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, status: int, value: object) -> None:
        self._send(status, "application/json; charset=utf-8", canonical_json_bytes(value))

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message, "schema_version": BENCHMARK_LAB_SCHEMA_VERSION})

    def _expected_hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _singleton_header(
        self,
        name: str,
        *,
        required: bool,
    ) -> str | None:
        values = self.headers.get_all(name, failobj=[])
        if len(values) > 1:
            raise BenchmarkLabRequestError(400, f"duplicate {name} header is unsupported")
        if not values:
            if required:
                raise BenchmarkLabRequestError(400, f"one {name} header is required")
            return None
        return values[0]

    def _request_boundary_valid(self) -> bool:
        try:
            host = self._singleton_header("Host", required=True)
            origin = self._singleton_header("Origin", required=False)
        except BenchmarkLabRequestError as error:
            self._error(error.status, str(error))
            return False
        assert host is not None
        if host not in self._expected_hosts():
            self._error(400, "request Host must be the Benchmark Lab loopback origin")
            return False
        if origin is not None and origin != f"http://{host}":
            self._error(403, "request Origin does not match the Benchmark Lab origin")
            return False
        return True

    def _authorized(self) -> bool:
        try:
            supplied = self._singleton_header("X-Atlas-Lab-Token", required=False)
        except BenchmarkLabRequestError as error:
            self._error(error.status, str(error))
            return False
        if supplied is None or _REQUEST_TOKEN.fullmatch(supplied) is None:
            self._error(403, "Benchmark Lab request token is invalid")
            return False
        if not secrets.compare_digest(supplied, self.application.token):
            self._error(403, "Benchmark Lab request token is invalid")
            return False
        return True

    def _read_body(self, maximum: int) -> bytes:
        transfer_encoding = self._singleton_header(
            "Transfer-Encoding",
            required=False,
        )
        if transfer_encoding is not None:
            raise BenchmarkLabRequestError(400, "transfer encoding is unsupported")
        lengths = self.headers.get_all("Content-Length", failobj=[])
        if len(lengths) != 1 or _CONTENT_LENGTH.fullmatch(lengths[0]) is None:
            raise BenchmarkLabRequestError(411, "one canonical Content-Length is required")
        length = int(lengths[0])
        if length > maximum:
            raise BenchmarkLabRequestError(413, "request body is too large")
        return self.rfile.read(length)

    def do_GET(self) -> None:
        if not self._request_boundary_valid():
            return
        if self.path == "/":
            self._send(200, "text/html; charset=utf-8", self.application.page)
        elif self.path == "/app.css":
            self._send(200, "text/css; charset=utf-8", PAGE_CSS.encode("utf-8"))
        elif self.path == "/app.js":
            self._send(
                200,
                "application/javascript; charset=utf-8",
                PAGE_JS.encode("utf-8"),
            )
        elif self.path == "/api/v1/state":
            self._json(200, self.application.state.to_dict())
        else:
            self._error(404, "route not found")

    def do_POST(self) -> None:
        if not self._request_boundary_valid() or not self._authorized():
            return
        try:
            if self.path == "/api/v1/captures/hwbot":
                self._require_content_type("text/html")
                payload = self._read_body(MAX_CAPTURE_BYTES)
                result = self.application.state.ingest_hwbot(payload)
            elif self.path == "/api/v1/captures/ul-3dmark":
                self._require_content_type("text/html")
                payload = self._read_body(MAX_CAPTURE_BYTES)
                result = self.application.state.ingest_ul(payload)
            elif self.path == "/api/v1/calculations/fire-strike":
                self._require_content_type("application/json")
                result = self.application.state.calculate(self._read_body(MAX_JSON_BYTES))
            elif self.path == "/api/v1/reset":
                self._require_content_type("application/json")
                request = _json_mapping(self._read_body(MAX_JSON_BYTES))
                if request:
                    raise BenchmarkLabRequestError(400, "reset JSON must be empty")
                result = self.application.state.reset()
            else:
                self._error(404, "route not found")
                return
        except BenchmarkLabRequestError as error:
            self._error(error.status, str(error))
            return
        except (TypeError, ValueError):
            self._error(422, "capture does not satisfy the supported source contract")
            return
        self._json(200, result)

    def _require_content_type(self, expected: str) -> None:
        content_type = self._singleton_header("Content-Type", required=False)
        if content_type != expected:
            raise BenchmarkLabRequestError(415, f"Content-Type must be {expected}")

    def _method_not_allowed(self) -> None:
        payload = canonical_json_bytes(
            {"error": "method not allowed", "schema_version": BENCHMARK_LAB_SCHEMA_VERSION}
        )
        self.send_response(405)
        self._security_headers()
        self.send_header("Allow", "GET, POST")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_DELETE = _method_not_allowed
    do_HEAD = _method_not_allowed
    do_OPTIONS = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_PUT = _method_not_allowed


def create_benchmark_lab_server(
    *,
    port: int = 0,
    token: str | None = None,
) -> _BenchmarkLabServer:
    if isinstance(port, bool) or not isinstance(port, int):
        raise TypeError("Benchmark Lab port must be an integer")
    if not 0 <= port <= 65535:
        raise ValueError("Benchmark Lab port must be between 0 and 65535")
    application = BenchmarkLabApplication(token=token)
    handler = type("BoundBenchmarkLabHandler", (BenchmarkLabHandler,), {})
    handler.application = application
    return _BenchmarkLabServer((BENCHMARK_LAB_HOST, port), handler)


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local Atlas Benchmark Lab")
    parser.add_argument("--port", type=_port, default=BENCHMARK_LAB_DEFAULT_PORT)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open the local page in the default browser",
    )
    arguments = parser.parse_args(argv)
    server = create_benchmark_lab_server(port=arguments.port)
    url = f"http://{BENCHMARK_LAB_HOST}:{server.server_address[1]}/"
    print(f"Atlas Benchmark Lab: {url}")
    print("Local saved HTML only; source URLs are never fetched.")
    if not arguments.no_browser:
        webbrowser.open(url, new=2)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
