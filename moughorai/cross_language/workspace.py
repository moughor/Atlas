from __future__ import annotations

from collections.abc import Mapping

from .models import CrossLanguageMetrics, CrossLanguageWorkspace, IRCallEdge, IRFunction, IRModule
from .parser import parse_source


def build_workspace(sources: Mapping[str, str]) -> CrossLanguageWorkspace:
    modules = tuple(sorted((parse_source(path, text) for path, text in sources.items()), key=lambda m: m.path))
    functions = tuple(f for module in modules for f in module.functions)
    by_name: dict[tuple[str, int], list[IRFunction]] = {}
    by_owner_name: dict[tuple[str, str, int], list[IRFunction]] = {}
    for function in functions:
        by_name.setdefault((function.name, function.arity), []).append(function)
        by_owner_name.setdefault((function.owner.split(".")[-1], function.name, function.arity), []).append(function)
    edges: list[IRCallEdge] = []
    unresolved: list[str] = []
    for caller in sorted(functions, key=lambda f: f.qualified_name):
        for call in caller.calls:
            candidates: list[IRFunction] = []
            if call.receiver:
                receiver = call.receiver.split(".")[-1]
                candidates.extend(by_owner_name.get((receiver[:1].upper() + receiver[1:], call.name, call.arity), ()))
                candidates.extend(by_owner_name.get((receiver, call.name, call.arity), ()))
            if not candidates:
                candidates.extend(by_name.get((call.name, call.arity), ()))
            candidates = sorted({c.qualified_name: c for c in candidates}.values(), key=lambda f: f.qualified_name)
            location = call.span
            if len(candidates) == 1:
                edges.append(IRCallEdge(caller.qualified_name, candidates[0].qualified_name, location.path if location else "", location.line if location else 0))
            elif len(candidates) > 1:
                # Deterministic conservative fan-out for ambiguous dynamic calls.
                for candidate in candidates:
                    edges.append(IRCallEdge(caller.qualified_name, candidate.qualified_name, location.path if location else "", location.line if location else 0))
            elif call.name not in {"println", "print", "toString", "hashCode", "equals", "listOf", "mapOf", "setOf"}:
                unresolved.append(f"{caller.qualified_name} -> {call.receiver + '.' if call.receiver else ''}{call.name}/{call.arity} at {(location.path if location else '')}:{(location.line if location else 0)}")
    edges_tuple = tuple(sorted(set(edges)))
    unresolved_tuple = tuple(sorted(set(unresolved)))
    languages = tuple(sorted({module.language.value for module in modules}))
    metrics = CrossLanguageMetrics(len(modules), sum(len(m.types) for m in modules), len(functions), len(edges_tuple), len(unresolved_tuple), languages)
    return CrossLanguageWorkspace(modules, edges_tuple, unresolved_tuple, metrics)
