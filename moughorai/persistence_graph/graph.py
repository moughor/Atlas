from __future__ import annotations
from collections import defaultdict,deque
from .models import EntityNode,RepositoryNode,PersistenceImpact,PersistenceRelation,CascadeType
class PersistenceGraph:
    def __init__(self,entities=(),repositories=(),relations=()):
        self._entities={e.qualified_name:e for e in entities};self._repositories=tuple(sorted(set(repositories)));self._relations=tuple(sorted(set(relations)));self._out=defaultdict(set);self._in=defaultdict(set)
        for r in self._relations:self._out[r.owner].add(r);self._in[r.target].add(r)
    @property
    def entities(self): return tuple(sorted(self._entities.values()))
    @property
    def repositories(self): return self._repositories
    @property
    def relations(self): return self._relations
    def entity(self,name): return self._entities.get(name)
    def relations_for(self,owner): return tuple(sorted(self._out.get(owner,())))
    def incoming(self,target): return tuple(sorted(self._in.get(target,())))
    def repositories_for(self,entity): return tuple(r for r in self._repositories if r.entity_name==entity)
    def related(self,entity,transitive=False):
        seen=set();q=deque([entity])
        while q:
            cur=q.popleft()
            neighbors={r.target for r in self._out.get(cur,())}|{r.owner for r in self._in.get(cur,())}
            for nxt in neighbors:
                if nxt not in seen and nxt!=entity:
                    seen.add(nxt)
                    if transitive:q.append(nxt)
        return tuple(sorted(seen))
    def cascade_targets(self,entity,cascade=CascadeType.REMOVE,transitive=True):
        seen=set();q=deque([entity])
        while q:
            cur=q.popleft()
            for r in self._out.get(cur,()):
                if CascadeType.ALL not in r.cascades and cascade not in r.cascades: continue
                if r.target not in seen: seen.add(r.target); q.append(r.target) if transitive else None
        return tuple(sorted(seen))
    def impact(self,entity): return PersistenceImpact(entity,self.related(entity,True),tuple(r.qualified_name for r in self.repositories_for(entity)))
    def orphan_relations(self): return tuple(r for r in self._relations if r.owner not in self._entities or r.target not in self._entities)
