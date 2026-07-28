from __future__ import annotations
from moughorai.java_jpa import JpaAnalysisReport
from .graph import PersistenceGraph
from .models import EntityNode,FetchType,PersistenceRelation,RepositoryNode
class PersistenceGraphBuilder:
    def build(self,report:JpaAnalysisReport,repositories=(),relation_options=None):
        relation_options=relation_options or {}
        entities=[EntityNode(e.qualified_name,e.table_name) for e in report.entities]
        relations=[]
        for r in report.relations:
            target=r.target_qualified_name or r.target_name
            options=relation_options.get((r.owner,r.field_name),{})
            relations.append(PersistenceRelation(r.owner,target,r.field_name,r.kind.value,options.get('fetch',FetchType.LAZY),tuple(options.get('cascades',())),options.get('optional',True)))
        repos=[x if isinstance(x,RepositoryNode) else RepositoryNode(*x) for x in repositories]
        return PersistenceGraph(entities,repos,relations)
