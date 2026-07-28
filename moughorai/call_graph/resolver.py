from __future__ import annotations

from collections import defaultdict

from .hierarchy import TypeHierarchy
from .models import (
    CallSite,
    DispatchKind,
    MethodId,
    MethodSymbol,
    Resolution,
    ResolutionStatus,
)


class DispatchResolver:
    """Resolves JVM-style call sites against known methods and hierarchy."""

    def __init__(self, methods: tuple[MethodSymbol, ...], hierarchy: TypeHierarchy) -> None:
        self._hierarchy = hierarchy
        self._methods = {method.id: method for method in methods}
        self._by_signature: dict[tuple[str, str], set[MethodId]] = defaultdict(set)
        for method in methods:
            self._by_signature[(method.id.name, method.id.descriptor)].add(method.id)

    def resolve(self, call_site: CallSite) -> Resolution:
        declared = call_site.declared_target
        if call_site.dispatch in (DispatchKind.STATIC, DispatchKind.SPECIAL):
            return self._resolve_exact(call_site, declared)
        if call_site.dispatch in (DispatchKind.VIRTUAL, DispatchKind.INTERFACE):
            return self._resolve_polymorphic(call_site)
        return self._resolve_dynamic(call_site)

    def _resolve_exact(self, call_site: CallSite, target: MethodId) -> Resolution:
        method = self._methods.get(target)
        if method is not None:
            status = ResolutionStatus.EXTERNAL if method.external else ResolutionStatus.RESOLVED
            return Resolution(call_site, (target,), status)
        inherited = self._lookup_nearest(target.owner, target.name, target.descriptor)
        if inherited is not None:
            method = self._methods[inherited]
            status = ResolutionStatus.EXTERNAL if method.external else ResolutionStatus.RESOLVED
            return Resolution(call_site, (inherited,), status, "resolved on supertype")
        if self._is_external_owner(target.owner):
            return Resolution(call_site, (target,), ResolutionStatus.EXTERNAL, "external owner")
        return Resolution(call_site, (), ResolutionStatus.UNRESOLVED, "target method not found")

    def _resolve_polymorphic(self, call_site: CallSite) -> Resolution:
        candidates: set[MethodId] = set()
        runtime_types = self._hierarchy.concrete_subtypes(call_site.declared_owner, include_self=True)
        if not runtime_types and self._hierarchy.get(call_site.declared_owner) is None:
            declared = call_site.declared_target
            if declared in self._methods:
                return self._resolve_exact(call_site, declared)
            return Resolution(call_site, (declared,), ResolutionStatus.EXTERNAL, "unknown external receiver type")
        for runtime_type in runtime_types:
            target = self._lookup_nearest(runtime_type, call_site.method_name, call_site.descriptor)
            if target is not None:
                candidates.add(target)
        declared = self._lookup_nearest(call_site.declared_owner, call_site.method_name, call_site.descriptor)
        if declared is not None and not self._methods[declared].abstract:
            candidates.add(declared)
        targets = tuple(sorted(candidates))
        if not targets:
            return Resolution(call_site, (), ResolutionStatus.UNRESOLVED, "no compatible implementation")
        external_only = all(self._methods[target].external for target in targets)
        if external_only:
            status = ResolutionStatus.EXTERNAL
        elif len(targets) > 1:
            status = ResolutionStatus.POLYMORPHIC
        else:
            status = ResolutionStatus.RESOLVED
        return Resolution(call_site, targets, status)

    def _resolve_dynamic(self, call_site: CallSite) -> Resolution:
        exact = call_site.declared_target
        if exact in self._methods:
            method = self._methods[exact]
            status = ResolutionStatus.EXTERNAL if method.external else ResolutionStatus.RESOLVED
            return Resolution(call_site, (exact,), status, "dynamic target supplied")
        matches = tuple(sorted(self._by_signature.get((call_site.method_name, call_site.descriptor), ())))
        if len(matches) == 1:
            return Resolution(call_site, matches, ResolutionStatus.RESOLVED, "unique dynamic signature")
        if len(matches) > 1:
            return Resolution(call_site, matches, ResolutionStatus.POLYMORPHIC, "ambiguous dynamic signature")
        return Resolution(call_site, (), ResolutionStatus.UNRESOLVED, "dynamic target unavailable")

    def _lookup_nearest(self, owner: str, name: str, descriptor: str) -> MethodId | None:
        direct = MethodId(owner, name, descriptor)
        if direct in self._methods:
            return direct
        for parent in self._hierarchy.supertypes(owner):
            candidate = MethodId(parent, name, descriptor)
            if candidate in self._methods:
                return candidate
        return None

    def _is_external_owner(self, owner: str) -> bool:
        symbol = self._hierarchy.get(owner)
        return symbol is None or symbol.external
