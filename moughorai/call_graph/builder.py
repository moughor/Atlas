from __future__ import annotations

from .graph import CallGraph
from .hierarchy import TypeHierarchy
from .models import BuildReport, CallEdge, CallSite, MethodId, MethodSymbol, TypeSymbol
from .resolver import DispatchResolver


class CallGraphBuilder:
    """Builds a call graph from normalized method and call-site facts."""

    def build(
        self,
        *,
        types: tuple[TypeSymbol, ...] | list[TypeSymbol] = (),
        methods: tuple[MethodSymbol, ...] | list[MethodSymbol] = (),
        call_sites: tuple[CallSite, ...] | list[CallSite] = (),
        include_external_targets: bool = True,
    ) -> BuildReport:
        type_tuple = tuple(types)
        method_tuple = tuple(methods)
        self._validate_methods(method_tuple)
        hierarchy = TypeHierarchy(type_tuple)
        resolver = DispatchResolver(method_tuple, hierarchy)
        resolutions = tuple(resolver.resolve(site) for site in sorted(call_sites, key=lambda item: item.key))
        all_methods = {method.id: method for method in method_tuple}
        edges: list[CallEdge] = []
        warnings: list[str] = []
        for resolution in resolutions:
            site = resolution.call_site
            if not resolution.targets:
                warnings.append(f"unresolved call: {site.caller} -> {site.declared_target}")
                continue
            for target in resolution.targets:
                target_symbol = all_methods.get(target)
                if target_symbol is None:
                    if not include_external_targets:
                        continue
                    target_symbol = MethodSymbol(target, external=True)
                    all_methods[target] = target_symbol
                edges.append(CallEdge(
                    caller=site.caller,
                    callee=target,
                    dispatch=site.dispatch,
                    kind=site.kind,
                    status=resolution.status,
                    source_path=site.source_path,
                    line=site.line,
                    column=site.column,
                    declared_target=site.declared_target,
                ))
        callers = {site.caller for site in call_sites}
        missing_callers = sorted(callers - set(all_methods))
        for caller in missing_callers:
            warnings.append(f"call site caller missing from method index: {caller}")
            all_methods[caller] = MethodSymbol(caller, external=True)
        graph = CallGraph(all_methods.values(), edges, types=type_tuple, resolutions=resolutions)
        return BuildReport(graph, resolutions, tuple(sorted(set(warnings))))

    @staticmethod
    def _validate_methods(methods: tuple[MethodSymbol, ...]) -> None:
        seen: set[MethodId] = set()
        for method in methods:
            if method.id in seen:
                raise ValueError(f"duplicate method: {method.id}")
            seen.add(method.id)
