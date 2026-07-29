from pathlib import Path

import pytest

from moughorai.lsp import WorkDoneProgressReporter, WorkspaceLanguageServer


def workspace(tmp_path: Path) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "atlas.yaml").write_text("projects:\n- name: app\n  path: app\n")
    return tmp_path


def test_reporter_emits_create_begin_report_end() -> None:
    events = []
    task = WorkDoneProgressReporter(events.append).begin("Analyze", total=2)
    task.advance("one")
    task.advance("two")
    task.end("done")
    assert [item["method"] for item in events] == [
        "window/workDoneProgress/create", "$/progress", "$/progress", "$/progress", "$/progress"
    ]
    values = [item["params"]["value"] for item in events if item["method"] == "$/progress"]
    assert [value["kind"] for value in values] == ["begin", "report", "report", "end"]
    assert [value.get("percentage") for value in values] == [0, 50, 100, None]


def test_tokens_are_deterministic_and_active_sorted() -> None:
    reporter = WorkDoneProgressReporter(lambda event: None)
    first = reporter.begin("one", total=1)
    second = reporter.begin("two", total=1)
    assert (first.token, second.token) == ("atlas-1", "atlas-2")
    assert reporter.active_tokens == ("atlas-1", "atlas-2")
    first.end()
    assert reporter.active_tokens == ("atlas-2",)


def test_cancel_marks_active_task() -> None:
    reporter = WorkDoneProgressReporter(lambda event: None)
    task = reporter.begin("one", total=1)
    assert reporter.cancel(task.token)
    assert task.cancelled
    assert not reporter.cancel("missing")


def test_task_end_is_idempotent_and_advance_after_end_fails() -> None:
    events = []
    task = WorkDoneProgressReporter(events.append).begin("one", total=1)
    task.end()
    task.end()
    with pytest.raises(ValueError, match="ended"):
        task.advance()
    assert sum(item.get("params", {}).get("value", {}).get("kind") == "end" for item in events) == 1


def test_progress_validation() -> None:
    reporter = WorkDoneProgressReporter(lambda event: None)
    with pytest.raises(ValueError, match="title"):
        reporter.begin("", total=1)
    with pytest.raises(ValueError, match="total"):
        reporter.begin("x", total=-1)
    task = reporter.begin("x", total=1)
    with pytest.raises(ValueError, match="amount"):
        task.advance(amount=-1)


def test_zero_total_omits_report_percentage() -> None:
    events = []
    task = WorkDoneProgressReporter(events.append).begin("empty", total=0)
    task.advance(amount=0)
    report = events[-1]["params"]["value"]
    assert report == {"kind": "report"}


def test_workspace_initialize_advertises_progress(tmp_path: Path) -> None:
    server = WorkspaceLanguageServer(workspace(tmp_path), lambda document, project, config: ())
    result = server.handle({"id": 1, "method": "initialize", "params": {}})
    assert result["result"]["capabilities"]["window"]["workDoneProgress"] is True


def test_workspace_diagnostics_emits_progress_in_uri_order(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    server = WorkspaceLanguageServer(root, lambda document, project, config: ())
    for name in ("z.py", "a.py"):
        server.handle({
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": (root / "app" / name).as_uri(), "text": "x", "version": 1}},
        })
    response = server.handle({"id": 3, "method": "workspace/diagnostic", "params": {}})
    events = server.drain_notifications()
    reports = [
        item["params"]["value"] for item in events
        if item["method"] == "$/progress" and item["params"]["value"]["kind"] == "report"
    ]
    assert len(response["result"]["items"]) == 2
    assert [item["message"] for item in reports] == sorted(item["message"] for item in reports)
    assert [item["percentage"] for item in reports] == [50, 100]


def test_cancel_request_for_unknown_token_is_safe(tmp_path: Path) -> None:
    server = WorkspaceLanguageServer(workspace(tmp_path), lambda document, project, config: ())
    assert server.handle({
        "method": "window/workDoneProgress/cancel",
        "params": {"token": "missing"},
    }) is None
