from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "moughorai"
PROMPT_MODULE = PACKAGE / "prompts" / "semantic.py"


@dataclass(frozen=True, slots=True)
class _DependencyGraph:
    modules: tuple[str, ...]
    runtime_edges: frozenset[tuple[str, str]]
    type_only_edges: frozenset[tuple[str, str]]


def _module_inventory() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(ROOT).with_suffix('')
        module = ".".join(relative.parts)
        if module.endswith(".__init__"):
            module = module[: -len(".__init__")]
        modules[module] = path
    return modules


def _is_type_checking_guard(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING") or (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "typing"
        and node.attr == "TYPE_CHECKING"
    )


def _resolve_from_module(
    current: str,
    *,
    current_is_package: bool,
    level: int,
    imported: str | None,
) -> str:
    if level == 0:
        return imported or ""

    package = current if current_is_package else current.rpartition(".")[0]
    parts = package.split(".") if package else []
    retained = len(parts) - (level - 1)
    prefix = ".".join(parts[: max(retained, 0)])
    return ".".join(part for part in (prefix, imported or "") if part)


def _literal_dynamic_import(node: ast.Call) -> str | None:
    function = node.func
    is_import = isinstance(function, ast.Name) and function.id == "__import__"
    is_import_module = (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id == "importlib"
        and function.attr == "import_module"
    )
    if not (is_import or is_import_module) or not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _local_target(target: str, modules: set[str]) -> str | None:
    candidate = target
    while candidate and candidate not in modules:
        candidate = candidate.rpartition(".")[0]
    return candidate if candidate in modules else None


def _statement_targets(
    node: ast.AST,
    *,
    current: str,
    current_is_package: bool,
    modules: set[str],
) -> tuple[str, ...]:
    targets: list[str] = []
    if isinstance(node, ast.Import):
        targets.extend(alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
        base = _resolve_from_module(
            current,
            current_is_package=current_is_package,
            level=node.level,
            imported=node.module,
        )
        if base:
            targets.append(base)
        for alias in node.names:
            child = f"{base}.{alias.name}" if base else alias.name
            if child in modules:
                targets.append(child)
    elif isinstance(node, ast.Call):
        dynamic = _literal_dynamic_import(node)
        if dynamic:
            targets.append(dynamic)
    return tuple(targets)


def _edges_from_tree(
    tree: ast.AST,
    *,
    current: str,
    current_is_package: bool,
    modules: set[str],
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    runtime: set[tuple[str, str]] = set()
    type_only: set[tuple[str, str]] = set()

    def visit(node: ast.AST, *, under_type_checking: bool = False) -> None:
        if isinstance(node, ast.If) and _is_type_checking_guard(node.test):
            for child in node.body:
                visit(child, under_type_checking=True)
            for child in node.orelse:
                visit(child, under_type_checking=under_type_checking)
            return

        destination = type_only if under_type_checking else runtime
        for target in _statement_targets(
            node,
            current=current,
            current_is_package=current_is_package,
            modules=modules,
        ):
            local = _local_target(target, modules)
            if local is not None and local != current:
                destination.add((current, local))

        for child in ast.iter_child_nodes(node):
            visit(child, under_type_checking=under_type_checking)

    visit(tree)
    return runtime, type_only


def _dependency_graph() -> _DependencyGraph:
    inventory = _module_inventory()
    modules = set(inventory)
    runtime_edges: set[tuple[str, str]] = set()
    type_only_edges: set[tuple[str, str]] = set()

    for current, path in sorted(inventory.items()):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        runtime, type_only = _edges_from_tree(
            tree,
            current=current,
            current_is_package=path.name == "__init__.py",
            modules=modules,
        )
        runtime_edges.update(runtime)
        type_only_edges.update(type_only)

    return _DependencyGraph(
        tuple(sorted(modules)),
        frozenset(runtime_edges),
        frozenset(type_only_edges),
    )


def _cyclic_components(
    modules: Iterable[str], edges: Iterable[tuple[str, str]]
) -> tuple[tuple[str, ...], ...]:
    graph = {module: set() for module in modules}
    for source, target in edges:
        graph[source].add(target)

    next_index = 0
    indices: dict[str, int] = {}
    low_links: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def connect(module: str) -> None:
        nonlocal next_index
        indices[module] = next_index
        low_links[module] = next_index
        next_index += 1
        stack.append(module)
        on_stack.add(module)

        for target in sorted(graph[module]):
            if target not in indices:
                connect(target)
                low_links[module] = min(low_links[module], low_links[target])
            elif target in on_stack:
                low_links[module] = min(low_links[module], indices[target])

        if low_links[module] != indices[module]:
            return

        component: list[str] = []
        while True:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == module:
                break
        if len(component) > 1:
            components.append(tuple(sorted(component)))

    for module in sorted(graph):
        if module not in indices:
            connect(module)

    return tuple(sorted(components, key=lambda item: (-len(item), item)))


def test_runtime_import_graph_has_no_cycles() -> None:
    dependencies = _dependency_graph()
    assert _cyclic_components(
        dependencies.modules, dependencies.runtime_edges
    ) == ()


def test_type_checking_imports_are_classified_as_non_runtime() -> None:
    source = (
        'from typing import TYPE_CHECKING\n'
        'from moughorai.runtime_target import RuntimeValue\n'
        'if TYPE_CHECKING:\n'
        '    from moughorai.type_target import TypeValue\n'
    )
    modules = {
        'moughorai.fixture',
        'moughorai.runtime_target',
        'moughorai.type_target',
    }
    runtime, type_only = _edges_from_tree(
        ast.parse(source),
        current='moughorai.fixture',
        current_is_package=False,
        modules=modules,
    )

    assert runtime == {('moughorai.fixture', 'moughorai.runtime_target')}
    assert type_only == {('moughorai.fixture', 'moughorai.type_target')}


def test_semantic_prompt_imports_context_from_canonical_owner() -> None:
    tree = ast.parse(
        PROMPT_MODULE.read_text(encoding='utf-8-sig'), filename=str(PROMPT_MODULE)
    )
    imports = tuple(
        node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    )

    assert any(
        statement.module == 'moughorai.semantic_snapshot.context'
        and any(alias.name == 'WorkspaceSemanticContext' for alias in statement.names)
        for statement in imports
    )
    assert not any(
        statement.module == 'moughorai.ai_context'
        or (statement.module or '').startswith('moughorai.ai_context.')
        for statement in imports
    )


def test_semantic_prompt_clean_import_does_not_load_legacy_facades() -> None:
    script = '''
import sys
from moughorai.prompts.semantic import WorkspaceSemanticContext as PromptContext
from moughorai.semantic_snapshot.context import WorkspaceSemanticContext

assert PromptContext is WorkspaceSemanticContext
for module in (
    'moughorai.ai_context',
    'moughorai.ai_context.collector',
    'moughorai.repository_report',
):
    assert module not in sys.modules, module
'''
    environment = dict(os.environ)
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run(
        [sys.executable, '-B', '-c', script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_semantic_prompt_context_identity_is_preserved() -> None:
    from moughorai.ai_context import WorkspaceSemanticContext as LegacyContext
    from moughorai.prompts.semantic import WorkspaceSemanticContext as PromptContext
    from moughorai.semantic_snapshot.context import WorkspaceSemanticContext

    assert PromptContext is WorkspaceSemanticContext
    assert LegacyContext is WorkspaceSemanticContext
