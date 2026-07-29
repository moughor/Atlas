from __future__ import annotations

from pathlib import Path

import pytest

from moughorai.workspace import (
    DependencyGraph,
    Project,
    Workspace,
    WorkspaceCache,
    WorkspaceConfigError,
    WorkspaceDependencyError,
    WorkspaceDiscovery,
    WorkspaceLoader,
    WorkspaceService,
)


def write(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def make_workspace(tmp_path: Path) -> Workspace:
    api = tmp_path / "api"
    core = tmp_path / "core"
    ui = tmp_path / "ui"
    for path in (api, core, ui):
        path.mkdir()
    return Workspace(
        root=tmp_path,
        projects=(
            Project("core", core),
            Project("api", api, dependencies=("core",)),
            Project("ui", ui, dependencies=("api",)),
        ),
    )


def test_project_rejects_empty_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="name"):
        Project(" ", tmp_path)


def test_project_rejects_self_dependency(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="itself"):
        Project("api", tmp_path, dependencies=("api",))


def test_project_serialization_relative_path(tmp_path: Path) -> None:
    project = Project("api", tmp_path / "apps" / "api", options=(("language", "python"),))
    assert project.to_dict(root=tmp_path)["path"] == "apps/api"
    assert project.option_map == {"language": "python"}


def test_workspace_rejects_duplicate_names(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        Workspace(tmp_path, (Project("x", tmp_path / "a"), Project("x", tmp_path / "b")))


def test_workspace_get_and_names(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    assert workspace.names() == ("api", "core", "ui")
    assert workspace.get("api").path == tmp_path / "api"


def test_workspace_unknown_project(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="unknown project"):
        make_workspace(tmp_path).get("missing")


def test_loader_finds_atlas_yaml(tmp_path: Path) -> None:
    config = write(tmp_path / "atlas.yaml", "projects: []\n")
    assert WorkspaceLoader().find_config(tmp_path) == config


def test_loader_accepts_directory(tmp_path: Path) -> None:
    write(tmp_path / "atlas.yaml", "projects:\n  - path: apps/api\n")
    workspace = WorkspaceLoader().load(tmp_path)
    assert workspace.names() == ("api",)
    assert workspace.config_path == tmp_path / "atlas.yaml"


def test_loader_accepts_string_project(tmp_path: Path) -> None:
    workspace = WorkspaceLoader().load_mapping({"projects": ["services/core"]}, root=tmp_path)
    assert workspace.projects[0].name == "core"


def test_loader_parses_complete_project(tmp_path: Path) -> None:
    workspace = WorkspaceLoader().load_mapping(
        {"projects": [{"name": "api", "path": "src/api", "dependencies": ["core"], "include": ["**/*.py"], "exclude": ["**/test_*"], "options": {"strict": True}}]},
        root=tmp_path,
    )
    project = workspace.get("api")
    assert project.dependencies == ("core",)
    assert project.include == ("**/*.py",)
    assert project.exclude == ("**/test_*",)
    assert project.option_map == {"strict": "True"}


def test_loader_rejects_non_object_root(tmp_path: Path) -> None:
    write(tmp_path / "atlas.yaml", "- invalid\n")
    with pytest.raises(WorkspaceConfigError, match="root"):
        WorkspaceLoader().load(tmp_path)


def test_loader_rejects_non_array_projects(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceConfigError, match="array"):
        WorkspaceLoader().load_mapping({"projects": {}}, root=tmp_path)


def test_loader_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceConfigError, match="escapes"):
        WorkspaceLoader().load_mapping({"projects": ["../outside"]}, root=tmp_path)


def test_loader_rejects_invalid_yaml(tmp_path: Path) -> None:
    write(tmp_path / "atlas.yaml", "projects: [\n")
    with pytest.raises(WorkspaceConfigError, match="YAML"):
        WorkspaceLoader().load(tmp_path)


def test_graph_topological_order(tmp_path: Path) -> None:
    assert DependencyGraph(make_workspace(tmp_path)).order() == ("core", "api", "ui")


def test_graph_direct_dependents(tmp_path: Path) -> None:
    graph = DependencyGraph(make_workspace(tmp_path))
    assert graph.dependents("core", transitive=False) == ("api",)


def test_graph_transitive_dependents(tmp_path: Path) -> None:
    graph = DependencyGraph(make_workspace(tmp_path))
    assert graph.dependents("core") == ("api", "ui")


def test_graph_transitive_dependencies(tmp_path: Path) -> None:
    graph = DependencyGraph(make_workspace(tmp_path))
    assert graph.dependencies_of("ui") == ("core", "api")


def test_graph_filtered_order(tmp_path: Path) -> None:
    graph = DependencyGraph(make_workspace(tmp_path))
    assert graph.order(("ui", "core")) == ("core", "ui")


def test_graph_rejects_missing_dependency(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path, (Project("api", tmp_path / "api", dependencies=("core",)),))
    with pytest.raises(WorkspaceDependencyError, match="unknown"):
        DependencyGraph(workspace)


def test_graph_rejects_cycle(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path, (Project("a", tmp_path / "a", dependencies=("b",)), Project("b", tmp_path / "b", dependencies=("a",))))
    with pytest.raises(WorkspaceDependencyError, match="cycle"):
        DependencyGraph(workspace)


def test_discovery_prefers_configuration(tmp_path: Path) -> None:
    write(tmp_path / "atlas.yaml", "projects:\n  - name: configured\n    path: app\n")
    write(tmp_path / "other" / "pyproject.toml")
    workspace = WorkspaceDiscovery().discover(tmp_path)
    assert workspace.names() == ("configured",)


def test_discovery_finds_marker_projects(tmp_path: Path) -> None:
    write(tmp_path / "services" / "api" / "pyproject.toml")
    write(tmp_path / "services" / "ui" / "package.json")
    workspace = WorkspaceDiscovery().discover(tmp_path)
    assert workspace.names() == ("services-api", "services-ui")


def test_discovery_honors_depth(tmp_path: Path) -> None:
    write(tmp_path / "one" / "two" / "three" / "pyproject.toml")
    assert WorkspaceDiscovery().discover(tmp_path, max_depth=2).projects == ()


def test_discovery_ignores_node_modules(tmp_path: Path) -> None:
    write(tmp_path / "node_modules" / "package" / "package.json")
    assert WorkspaceDiscovery().discover(tmp_path).projects == ()


def test_discovery_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        WorkspaceDiscovery().discover(tmp_path / "missing")


def test_cache_fingerprint_changes_with_content(tmp_path: Path) -> None:
    project_path = tmp_path / "api"
    source = write(project_path / "main.py", "one")
    cache = WorkspaceCache()
    project = Project("api", project_path)
    first = cache.fingerprint(project)
    source.write_text("two", encoding="utf-8")
    assert cache.fingerprint(project) != first


def test_cache_respects_excludes(tmp_path: Path) -> None:
    project_path = tmp_path / "api"
    write(project_path / "main.py", "one")
    ignored = write(project_path / "build" / "generated.py", "one")
    cache = WorkspaceCache()
    project = Project("api", project_path, exclude=("build/**/*",))
    first = cache.fingerprint(project)
    ignored.write_text("two", encoding="utf-8")
    assert cache.fingerprint(project) == first


def test_cache_initial_snapshot_marks_all_changed(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    snapshot = WorkspaceCache().snapshot(workspace)
    assert WorkspaceCache().changed(None, snapshot) == ("api", "core", "ui")


def test_cache_reports_only_changed_project(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    write(tmp_path / "core" / "main.py", "one")
    cache = WorkspaceCache()
    before = cache.snapshot(workspace)
    write(tmp_path / "core" / "main.py", "two")
    after = cache.snapshot(workspace)
    assert cache.changed(before, after) == ("core",)


def test_service_analysis_order_includes_dependencies(tmp_path: Path) -> None:
    write(tmp_path / "atlas.yaml", "projects:\n  - name: core\n    path: core\n  - name: api\n    path: api\n    dependencies: [core]\n  - name: ui\n    path: ui\n    dependencies: [api]\n")
    service = WorkspaceService(tmp_path)
    assert tuple(project.name for project in service.analysis_order(("ui",))) == ("core", "api", "ui")


def test_service_analysis_order_can_exclude_dependencies(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    write(tmp_path / "atlas.yaml", "projects:\n  - name: core\n    path: core\n  - name: api\n    path: api\n    dependencies: [core]\n  - name: ui\n    path: ui\n    dependencies: [api]\n")
    service = WorkspaceService(tmp_path)
    assert tuple(project.name for project in service.analysis_order(("ui",), include_dependencies=False)) == ("ui",)


def test_service_impacted_projects(tmp_path: Path) -> None:
    write(tmp_path / "atlas.yaml", "projects:\n  - name: core\n    path: core\n  - name: api\n    path: api\n    dependencies: [core]\n  - name: ui\n    path: ui\n    dependencies: [api]\n")
    service = WorkspaceService(tmp_path)
    assert tuple(project.name for project in service.impacted_projects(("core",))) == ("core", "api", "ui")


def test_workspace_serialization_is_deterministic(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    assert [item["name"] for item in workspace.to_dict()["projects"]] == ["api", "core", "ui"]
