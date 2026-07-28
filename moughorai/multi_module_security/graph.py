from __future__ import annotations
from collections import defaultdict
from .models import ModuleDescriptor, ModuleGraph

class ModuleGraphBuilder:
    def build(self, modules: tuple[ModuleDescriptor,...]) -> ModuleGraph:
        ordered=tuple(sorted(modules,key=lambda m:m.name.casefold()))
        names={m.name for m in ordered}; edges=[]; unresolved=[]
        for m in ordered:
            for dep in sorted(set(m.dependencies),key=str.casefold):
                if dep in names and dep!=m.name: edges.append((m.name,dep))
                elif dep==m.name: edges.append((m.name,dep))
                else: unresolved.append((m.name,dep))
        edges=tuple(sorted(set(edges),key=lambda e:(e[0].casefold(),e[1].casefold())))
        return ModuleGraph(ordered,edges,tuple(sorted(unresolved)),self._cycles(names,edges))
    def _cycles(self,names,edges):
        adjacency=defaultdict(list)
        for a,b in edges: adjacency[a].append(b)
        index=0; stack=[]; on=set(); indices={}; low={}; comps=[]
        def visit(v):
            nonlocal index
            indices[v]=low[v]=index; index+=1; stack.append(v); on.add(v)
            for w in sorted(adjacency[v],key=str.casefold):
                if w not in indices: visit(w); low[v]=min(low[v],low[w])
                elif w in on: low[v]=min(low[v],indices[w])
            if low[v]==indices[v]:
                comp=[]
                while True:
                    w=stack.pop(); on.remove(w); comp.append(w)
                    if w==v: break
                if len(comp)>1 or (len(comp)==1 and (v,v) in edges): comps.append(tuple(sorted(comp,key=str.casefold)))
        for n in sorted(names,key=str.casefold):
            if n not in indices: visit(n)
        return tuple(sorted(comps,key=lambda c:tuple(x.casefold() for x in c)))
    def scan_order(self, graph: ModuleGraph) -> tuple[str,...]:
        # dependencies before consumers; deterministic SCC-tolerant fallback
        deps={m.name:set(graph.dependencies_of(m.name)) for m in graph.modules}
        remaining=set(deps); order=[]
        while remaining:
            ready=sorted((n for n in remaining if not (deps[n]&remaining)),key=str.casefold)
            if not ready: ready=[sorted(remaining,key=str.casefold)[0]]
            for n in ready: order.append(n); remaining.remove(n)
        return tuple(order)
    def transitive_dependencies(self, graph: ModuleGraph, name: str) -> tuple[str,...]:
        seen=set(); stack=list(graph.dependencies_of(name))
        while stack:
            item=stack.pop()
            if item in seen: continue
            seen.add(item); stack.extend(graph.dependencies_of(item))
        seen.discard(name)
        return tuple(sorted(seen,key=str.casefold))
    def impacted_modules(self, graph: ModuleGraph, changed: tuple[str,...]) -> tuple[str,...]:
        impacted=set(changed); queue=list(changed)
        while queue:
            item=queue.pop(0)
            for dep in graph.dependents_of(item):
                if dep not in impacted: impacted.add(dep); queue.append(dep)
        return tuple(sorted(impacted,key=str.casefold))
