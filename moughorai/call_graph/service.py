from __future__ import annotations

from .builder import CallGraphBuilder
from .models import BuildReport, CallSite, MethodSymbol, TypeSymbol


class CallGraphService:
    def __init__(self, builder: CallGraphBuilder | None = None) -> None:
        self._builder = builder or CallGraphBuilder()

    def build(
        self,
        types: tuple[TypeSymbol, ...] | list[TypeSymbol],
        methods: tuple[MethodSymbol, ...] | list[MethodSymbol],
        call_sites: tuple[CallSite, ...] | list[CallSite],
        *,
        include_external_targets: bool = True,
    ) -> BuildReport:
        return self._builder.build(
            types=types,
            methods=methods,
            call_sites=call_sites,
            include_external_targets=include_external_targets,
        )
