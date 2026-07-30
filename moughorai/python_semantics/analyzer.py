from __future__ import annotations

import ast
from pathlib import Path

from moughorai.global_symbols import GlobalSymbol, GlobalSymbolKind
from moughorai.global_symbols.models import SymbolId
from moughorai.semantic import Diagnostic, DiagnosticSeverity
from moughorai.semantic.types import TypeRegistry, TypeTable

from .models import PythonAnalysisResult, PythonModule


class PythonSemanticAnalyzer:
    """Extract deterministic Python declarations using the standard-library AST."""

    def analyze(self, root: Path, paths: tuple[Path, ...]) -> PythonAnalysisResult:
        modules: list[PythonModule] = []
        symbols: list[GlobalSymbol] = []
        diagnostics: list[Diagnostic] = []
        type_builder = TypeTable().to_builder()
        registry = TypeRegistry()
        for path in sorted(paths, key=Path.as_posix):
            module_name = self._module_name(root, path)
            try:
                tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            except (OSError, UnicodeError, SyntaxError) as exc:
                diagnostics.append(
                    Diagnostic(
                        "ATLAS-PYTHON-PARSE",
                        str(exc),
                        DiagnosticSeverity.ERROR,
                        location=path,
                        pass_name="python-semantic-analyzer",
                    )
                )
                continue
            imports = self._imports(tree)
            module_doc = ast.get_docstring(tree, clean=False) or ""
            module_symbol = GlobalSymbol.create(
                GlobalSymbolKind.PACKAGE,
                module_name.rsplit(".", 1)[-1],
                module_name,
                source=path,
                metadata={"language": "python", "docstring": module_doc, "imports": ",".join(imports)},
            )
            symbols.append(module_symbol)
            modules.append(PythonModule(module_name, path, imports, module_doc))
            collector = _DeclarationCollector(path, module_name, module_symbol.id, registry, type_builder)
            collector.visit_statements(tree.body)
            symbols.extend(collector.symbols)
        unique_symbols: dict[str, GlobalSymbol] = {}
        for symbol in symbols:
            unique_symbols.setdefault(symbol.qualified_name, symbol)
        return PythonAnalysisResult(
            tuple(modules),
            tuple(sorted(unique_symbols.values(), key=lambda item: (item.qualified_name, item.kind.value))),
            type_builder.build(),
            tuple(sorted(diagnostics, key=lambda item: (str(item.location), item.message))),
        )

    @staticmethod
    def _module_name(root: Path, path: Path) -> str:
        relative = path.resolve().relative_to(root.resolve()).with_suffix("")
        parts = list(relative.parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts) or root.name

    @staticmethod
    def _imports(tree: ast.Module) -> tuple[str, ...]:
        values: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                values.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                prefix = "." * node.level + (node.module or "")
                separator = "" if not node.module else "."
                values.update(f"{prefix}{separator}{alias.name}" for alias in node.names)
        return tuple(sorted(values))


class _DeclarationCollector:
    def __init__(self, source, owner_name, owner_id, registry, type_builder) -> None:
        self.source = source
        self.owner_name = owner_name
        self.owner_id = owner_id
        self.registry = registry
        self.type_builder = type_builder
        self.symbols: list[GlobalSymbol] = []

    def visit_statements(self, statements: list[ast.stmt]) -> None:
        for node in statements:
            if isinstance(node, ast.ClassDef):
                self._class(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(node)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                self._assignment(node)

    def _class(self, node: ast.ClassDef) -> None:
        qualified = f"{self.owner_name}.{node.name}"
        decorators = self._expressions(node.decorator_list)
        bases = self._expressions(node.bases)
        metadata = {
            "language": "python",
            "decorators": ",".join(decorators),
            "bases": ",".join(bases),
            "docstring": ast.get_docstring(node, clean=False) or "",
            "dataclass": str(any(self._decorator_name(value) == "dataclass" for value in decorators)).lower(),
            "enum": str(any(value.rsplit(".", 1)[-1] in {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"} for value in bases)).lower(),
        }
        symbol = GlobalSymbol.create(
            GlobalSymbolKind.TYPE, node.name, qualified,
            owner_id=self.owner_id, source=self.source, metadata=metadata,
        )
        self.symbols.append(symbol)
        nested = _DeclarationCollector(self.source, qualified, symbol.id, self.registry, self.type_builder)
        nested.visit_statements(node.body)
        self.symbols.extend(nested.symbols)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualified = f"{self.owner_name}.{node.name}"
        parameters = []
        all_args = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
        for argument in all_args:
            annotation = self._expression(argument.annotation)
            parameters.append(f"{argument.arg}:{annotation}" if annotation else argument.arg)
        return_type = self._expression(node.returns)
        symbol = GlobalSymbol.create(
            GlobalSymbolKind.METHOD,
            node.name,
            qualified,
            owner_id=self.owner_id,
            source=self.source,
            metadata={
                "language": "python",
                "async": str(isinstance(node, ast.AsyncFunctionDef)).lower(),
                "decorators": ",".join(self._expressions(node.decorator_list)),
                "parameters": ",".join(parameters),
                "return_type": return_type,
                "docstring": ast.get_docstring(node, clean=False) or "",
            },
        )
        self.symbols.append(symbol)
        if return_type:
            self.type_builder.set(qualified, self.registry.class_type(return_type))
        nested = _DeclarationCollector(self.source, qualified, symbol.id, self.registry, self.type_builder)
        nested.visit_nested(node.body)
        self.symbols.extend(nested.symbols)

    def _assignment(self, node: ast.Assign | ast.AnnAssign) -> None:
        annotation = self._expression(node.annotation) if isinstance(node, ast.AnnAssign) else ""
        targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
        for target in targets:
            for name in self._target_names(target):
                qualified = f"{self.owner_name}.{name}"
                self.symbols.append(
                    GlobalSymbol.create(
                        GlobalSymbolKind.FIELD,
                        name,
                        qualified,
                        owner_id=self.owner_id,
                        source=self.source,
                        metadata={"language": "python", "annotation": annotation},
                    )
                )
                if annotation:
                    self.type_builder.set(qualified, self.registry.class_type(annotation))

    @staticmethod
    def _target_names(node: ast.expr) -> tuple[str, ...]:
        if isinstance(node, ast.Name):
            return (node.id,)
        if isinstance(node, (ast.Tuple, ast.List)):
            return tuple(name for item in node.elts for name in _DeclarationCollector._target_names(item))
        return ()

    @classmethod
    def _expressions(cls, nodes: list[ast.expr]) -> tuple[str, ...]:
        return tuple(cls._expression(node) for node in nodes)

    @staticmethod
    def _expression(node: ast.expr | None) -> str:
        return "" if node is None else ast.unparse(node)

    def visit_nested(self, statements: list[ast.stmt]) -> None:
        for node in statements:
            if isinstance(node, ast.ClassDef):
                self._class(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._function(node)

    @staticmethod
    def _decorator_name(value: str) -> str:
        return value.split("(", 1)[0].rsplit(".", 1)[-1]
