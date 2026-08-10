from __future__ import annotations

import ast
from pathlib import Path
import sys

from moughorai.ai_context import WorkspaceSemanticContext as LegacyWorkspaceSemanticContext
from moughorai.ai_context.models import (
    WorkspaceSemanticContext as LegacyModelsWorkspaceSemanticContext,
)
from moughorai.platform.safety import (
    contains_absolute_path,
    contains_absolute_path_text,
)
from moughorai.repository_report.safety import (
    contains_absolute_path as legacy_contains_absolute_path,
)
from moughorai.repository_report.safety import (
    contains_absolute_path_text as legacy_contains_absolute_path_text,
)
from moughorai.semantic_snapshot import (
    WorkspaceSemanticContext as SnapshotWorkspaceSemanticContext,
)
from moughorai.semantic_snapshot.context import WorkspaceSemanticContext


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "moughorai"


def _imports(path: Path) -> tuple[ast.Import | ast.ImportFrom, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    )


def test_legacy_safety_exports_are_identical_platform_functions() -> None:
    assert legacy_contains_absolute_path is contains_absolute_path
    assert legacy_contains_absolute_path_text is contains_absolute_path_text

    values = (
        "",
        "src/main.py",
        "C:/Users/example/repository",
        {"nested": ["safe", "file:///tmp/private"]},
        "evidence:" + ("a" * 64),
    )
    for value in values:
        assert legacy_contains_absolute_path(value) == contains_absolute_path(value)


def test_legacy_context_exports_are_identical_snapshot_class() -> None:
    assert LegacyWorkspaceSemanticContext is WorkspaceSemanticContext
    assert LegacyModelsWorkspaceSemanticContext is WorkspaceSemanticContext
    assert SnapshotWorkspaceSemanticContext is WorkspaceSemanticContext


def test_platform_is_minimal_and_imports_only_domain_neutral_dependencies() -> None:
    platform = PACKAGE / "platform"
    assert sorted(path.name for path in platform.glob("*.py")) == [
        "__init__.py",
        "safety.py",
    ]

    invalid: list[str] = []
    for path in platform.glob("*.py"):
        for statement in _imports(path):
            if isinstance(statement, ast.Import):
                modules = tuple(alias.name for alias in statement.names)
            elif statement.level:
                continue
            else:
                modules = (statement.module or "",)
            for module in modules:
                root = module.partition(".")[0]
                if root in sys.stdlib_module_names:
                    continue
                if module == "moughorai.platform" or module.startswith(
                    "moughorai.platform."
                ):
                    continue
                invalid.append(f"{path.relative_to(ROOT)}: {module}")

    assert invalid == []


def test_production_consumers_use_platform_safety_boundary() -> None:
    forbidden: list[str] = []
    compatibility_module = PACKAGE / "repository_report" / "safety.py"
    for path in PACKAGE.rglob("*.py"):
        if path == compatibility_module:
            continue
        for statement in _imports(path):
            if (
                isinstance(statement, ast.ImportFrom)
                and statement.module == "moughorai.repository_report.safety"
            ):
                forbidden.append(str(path.relative_to(ROOT)))
            if (
                isinstance(statement, ast.ImportFrom)
                and statement.level
                and statement.module == "safety"
                and path.parent.name == "repository_report"
            ):
                forbidden.append(str(path.relative_to(ROOT)))

    assert forbidden == []


def test_semantic_snapshot_does_not_depend_on_ai_context() -> None:
    forbidden: list[str] = []
    for path in (PACKAGE / "semantic_snapshot").rglob("*.py"):
        for statement in _imports(path):
            if isinstance(statement, ast.Import):
                modules = tuple(alias.name for alias in statement.names)
            else:
                modules = (statement.module or "",)
            if any(
                module == "moughorai.ai_context"
                or module.startswith("moughorai.ai_context.")
                for module in modules
            ):
                forbidden.append(str(path.relative_to(ROOT)))

    assert forbidden == []
