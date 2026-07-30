from pathlib import Path

from typer.testing import CliRunner

from moughorai.atlas_cli import app
from moughorai.repository_summary import RepositorySummaryService
from moughorai.semantic_snapshot import SemanticSnapshotStore
from moughorai.workspace import WorkspaceService


runner = CliRunner()


def _repository(root: Path) -> WorkspaceService:
    (root / "atlas.yaml").write_text(
        "projects:\n"
        "  - name: repository\n"
        "    path: .\n"
        "  - name: api\n"
        "    path: api\n",
        encoding="utf-8",
    )
    api = root / "api"
    (api / "tests").mkdir(parents=True)
    (api / "target" / "generated").mkdir(parents=True)
    (api / "requirements.txt").write_text("fastapi==0.115\n", encoding="utf-8")
    (api / "main.py").write_text(
        'if __name__ == "__main__":\n    print("start")\n',
        encoding="utf-8",
    )
    (api / "tests" / "test_main.py").write_text("def test_main(): pass\n", encoding="utf-8")
    (api / "target" / "generated" / "client.py").write_text("class Client: pass\n", encoding="utf-8")
    (root / "README.md").write_text("# Demo\n", encoding="utf-8")
    return WorkspaceService(root)


def test_summary_composes_existing_inventory_capabilities(tmp_path: Path) -> None:
    service = _repository(tmp_path)
    summary = RepositorySummaryService(service).build()
    payload = summary.to_dict()
    api = next(item for item in payload["projects"] if item["name"] == "api")
    root = next(item for item in payload["projects"] if item["name"] == "repository")
    assert api["languages"] == {"Python": 3}
    assert api["build_systems"] == ["Python Packaging"]
    assert api["frameworks"] == ["FastAPI"]
    assert api["entry_points"] == ["main.py"]
    assert (api["production_files"], api["test_files"], api["generated_files"]) == (1, 1, 1)
    assert payload["dependencies_by_ecosystem"] == {"pypi": 1}
    assert payload["declared_dependency_count_by_ecosystem"] == {"pypi": 1}
    assert payload["total_declared_dependencies"] == 1
    assert payload["dependency_manifest_count_by_ecosystem"] == {"pypi": 1}
    assert payload["total_dependency_manifests"] == 1
    assert payload["framework_evidence"] == [{
        "framework": "FastAPI",
        "project": "api",
        "scope": "project-local",
        "reference": "fastapi",
    }]
    assert payload["module_hierarchy"] == [
        {"project": "api", "parent": "repository"},
        {"project": "repository", "parent": None},
    ]
    assert root["files"] == 2


def test_nested_projects_are_not_double_counted(tmp_path: Path) -> None:
    summary = RepositorySummaryService(_repository(tmp_path)).build()
    by_name = {item.name: item for item in summary.projects}
    assert by_name["repository"].files == 2
    assert by_name["api"].files == 4
    assert sum(item.files for item in summary.projects) == 6


def test_summary_is_published_for_ai_without_raw_source(tmp_path: Path) -> None:
    service = _repository(tmp_path)
    result = runner.invoke(app, ["analyze", str(tmp_path), "--no-recover"])
    assert result.exit_code == 0
    snapshot = SemanticSnapshotStore(service.workspace).load()
    summary = snapshot.semantic_context["repository_summary"]
    assert summary["frameworks"] == ["FastAPI"]
    assert summary["entry_points"] == ["api:main.py"]
    serialized = str(summary)
    assert 'print("start")' not in serialized


def test_repository_summary_is_reproducible(tmp_path: Path) -> None:
    service = _repository(tmp_path)
    builder = RepositorySummaryService(service)
    assert builder.build().to_dict() == builder.build().to_dict()


def test_official_roadmap_records_junit_aggregator_and_consolidation() -> None:
    roadmap = Path("docs/roadmap/IMPLEMENTATION_ROADMAP.md").read_text(encoding="utf-8")
    normalized = " ".join(roadmap.split())
    assert "41 discovered projects" in roadmap
    assert "root `junit-team` aggregator" in roadmap
    assert "consolidations and integrations" in normalized
