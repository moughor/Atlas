"""Deterministic Spring semantic analyzer over Java AST nodes."""
from __future__ import annotations
from pathlib import Path
from moughorai.java_ast.ast_nodes import Annotation, CompilationUnit, TypeDeclaration
from moughorai.java_resolution.models import ResolutionStatus
from moughorai.java_resolution.resolver import JavaTypeResolver
from moughorai.java_symbols.index import JavaSymbolIndex
from moughorai.java_spring.models import (
    InjectionKind, InjectionPoint, SpringAnalysisReport, SpringBean,
    SpringBeanKind, SpringEndpoint,
)

_BEAN_ANNOTATIONS = {
    "Component": SpringBeanKind.COMPONENT,
    "Service": SpringBeanKind.SERVICE,
    "Repository": SpringBeanKind.REPOSITORY,
    "Controller": SpringBeanKind.CONTROLLER,
    "RestController": SpringBeanKind.REST_CONTROLLER,
    "Configuration": SpringBeanKind.CONFIGURATION,
}
_MAPPING_ANNOTATIONS = {
    "GetMapping": ("GET",), "PostMapping": ("POST",),
    "PutMapping": ("PUT",), "PatchMapping": ("PATCH",),
    "DeleteMapping": ("DELETE",), "RequestMapping": ("ANY",),
}
_INJECTION_ANNOTATIONS = {"Autowired", "Inject", "Resource"}


def _simple(annotation: str) -> str:
    return annotation.rsplit(".", 1)[-1]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
        return value[1:-1]
    return value


def _paths(annotation: Annotation) -> tuple[str, ...]:
    raw = annotation.argument("path") or annotation.argument("value")
    if raw is None:
        return ()
    value = raw.strip()
    if value.startswith("{") and value.endswith("}"):
        value = value[1:-1]
        return tuple(_unquote(part.strip()) for part in value.split(",") if part.strip())
    return (_unquote(value),)

class SpringAnalyzer:
    def analyze(
        self,
        units: tuple[CompilationUnit, ...],
        index: JavaSymbolIndex,
        sources: tuple[Path | None, ...] | None = None,
    ) -> SpringAnalysisReport:
        if sources is not None and len(sources) != len(units):
            raise ValueError("sources must have the same length as units")
        resolver = JavaTypeResolver(index)
        beans: list[SpringBean] = []
        injections: list[InjectionPoint] = []
        endpoints: list[SpringEndpoint] = []
        for i, unit in enumerate(units):
            source = sources[i] if sources is not None else None
            package = unit.package.name if unit.package else ""
            for declaration in unit.types:
                owner = f"{package}.{declaration.name}" if package else declaration.name
                self._analyze_type(unit, declaration, owner, source, resolver, beans, injections, endpoints)
        return SpringAnalysisReport(tuple(beans), tuple(injections), tuple(endpoints))

    def _analyze_type(self, unit, declaration, owner, source, resolver, beans, injections, endpoints):
        annotation_names = tuple(_simple(a) for a in declaration.annotations)
        for annotation in annotation_names:
            kind = _BEAN_ANNOTATIONS.get(annotation)
            if kind:
                beans.append(SpringBean(owner, kind, declaration.annotations, source))
                break

        for field in declaration.fields:
            field_annotations = {_simple(a) for a in field.annotations}
            if field_annotations & _INJECTION_ANNOTATIONS:
                injections.append(self._injection(unit, resolver, owner, field.type_name, InjectionKind.FIELD, field.name))

        constructor_injection = len(declaration.constructors) == 1
        for constructor in declaration.constructors:
            annotations = {_simple(a) for a in constructor.annotations}
            active = constructor_injection or bool(annotations & _INJECTION_ANNOTATIONS)
            if active:
                for parameter in constructor.parameters:
                    injections.append(self._injection(unit, resolver, owner, parameter.type_name, InjectionKind.CONSTRUCTOR, constructor.name))

        class_paths: tuple[str, ...] = ()
        for annotation in declaration.annotation_nodes:
            if _simple(annotation.name) == "RequestMapping":
                class_paths = _paths(annotation)

        for method in declaration.methods:
            mapped = []
            method_paths: tuple[str, ...] = ()
            for annotation in method.annotation_nodes:
                mapped.extend(_MAPPING_ANNOTATIONS.get(_simple(annotation.name), ()))
                if _simple(annotation.name) in _MAPPING_ANNOTATIONS:
                    method_paths = _paths(annotation)
            if mapped:
                combined = self._combine_paths(class_paths, method_paths)
                endpoints.append(SpringEndpoint(owner, method.name, tuple(dict.fromkeys(mapped)), method.annotations, combined))

        for nested in declaration.nested_types:
            self._analyze_type(unit, nested, f"{owner}.{nested.name}", source, resolver, beans, injections, endpoints)

    @staticmethod
    def _combine_paths(class_paths: tuple[str, ...], method_paths: tuple[str, ...]) -> tuple[str, ...]:
        if not class_paths:
            return method_paths
        if not method_paths:
            return class_paths
        return tuple(
            f"/{left.strip('/')}/{right.strip('/')}".replace("//", "/")
            for left in class_paths
            for right in method_paths
        )

    @staticmethod
    def _injection(unit, resolver, owner, target_name, kind, member_name):
        resolution = resolver.resolve(target_name, unit)
        target = resolution.qualified_name if resolution.status is ResolutionStatus.RESOLVED else None
        return InjectionPoint(owner, target_name, target, kind, member_name)
