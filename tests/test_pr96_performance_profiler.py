from __future__ import annotations

import json
from pathlib import Path
from threading import Thread

import pytest
from typer.testing import CliRunner

from moughorai.atlas_cli import app
from moughorai.profiling import PerformanceProfiler
from moughorai.workspace import Project


runner = CliRunner()


class Clock:
    def __init__(self, values: list[int]) -> None:
        self.values = iter(values)

    def __call__(self) -> int:
        return next(self.values)


def test_measure_aggregates_deterministically() -> None:
    profiler = PerformanceProfiler(clock=Clock([0, 2_000_000, 10_000_000, 14_000_000]))
    with profiler.measure("parse"):
        pass
    with profiler.measure("parse"):
        pass
    metric = profiler.report().metrics[0]
    assert metric.to_dict() == {
        "name": "parse",
        "calls": 2,
        "total_ms": 6.0,
        "minimum_ms": 2.0,
        "maximum_ms": 4.0,
        "average_ms": 3.0,
    }


def test_report_is_sorted_and_json_is_stable() -> None:
    profiler = PerformanceProfiler(clock=Clock([0, 1, 2, 3]))
    with profiler.measure("z"):
        pass
    with profiler.measure("a"):
        pass
    assert [item.name for item in profiler.report().metrics] == ["a", "z"]
    assert profiler.report().to_json() == profiler.report().to_json()


def test_measure_records_failed_operation() -> None:
    profiler = PerformanceProfiler(clock=Clock([0, 1_000_000]))
    with pytest.raises(RuntimeError):
        with profiler.measure("failure"):
            raise RuntimeError("boom")
    assert profiler.report().metrics[0].calls == 1


def test_empty_metric_name_is_rejected() -> None:
    profiler = PerformanceProfiler()
    with pytest.raises(ValueError, match="must not be empty"):
        with profiler.measure(" "):
            pass


def test_wrap_analyzer_preserves_value() -> None:
    profiler = PerformanceProfiler(clock=Clock([0, 1]))
    project = Project("core", Path("."))
    wrapped = profiler.wrap_analyzer(lambda item, dependencies: (item.name, dict(dependencies)))
    assert wrapped(project, {"api": 1}) == ("core", {"api": 1})
    assert profiler.report().metrics[0].name == "project:core"


def test_collection_is_thread_safe() -> None:
    profiler = PerformanceProfiler()
    def collect() -> None:
        for _ in range(20):
            with profiler.measure("work"):
                pass
    threads = [Thread(target=collect) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert profiler.report().metrics[0].calls == 80


def test_clear_returns_sample_count() -> None:
    profiler = PerformanceProfiler(clock=Clock([0, 1]))
    with profiler.measure("x"):
        pass
    assert profiler.clear() == 1
    assert profiler.report().metrics == ()


def test_profile_cli_reports_workspace_and_projects(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "atlas.yaml").write_text("projects:\n  - name: core\n    path: core\n", encoding="utf-8")
    result = runner.invoke(app, ["profile", str(tmp_path), "--workers", "2"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert [item["name"] for item in payload["metrics"]] == ["project:core", "workspace"]
