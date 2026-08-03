from __future__ import annotations
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping
import heapq
import hashlib
import json
from moughorai.global_symbols import SymbolId
from .models import (
    KnowledgeDegreeSummary,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeRelation,
    KnowledgeRelationDegree,
)
from .models import KnowledgeKind

class KnowledgeGraph:
    def __init__(self, nodes=(), edges=()):
        self._nodes={n.id:n for n in nodes}; self._edges=set(); self._out=defaultdict(set); self._in=defaultdict(set)
        self._sorted_nodes = None; self._sorted_edges = None; self._stable_digest = None
        for e in edges: self.add_edge(e)
    @property
    def nodes(self):
        if self._sorted_nodes is None: self._sorted_nodes=tuple(sorted(self._nodes.values()))
        return self._sorted_nodes
    @property
    def edges(self):
        if self._sorted_edges is None: self._sorted_edges=tuple(sorted(self._edges))
        return self._sorted_edges
    def add_node(self,node): self._nodes[node.id]=node; self._sorted_nodes=None; self._stable_digest=None
    def get(self,node_id): return self._nodes.get(node_id)
    def add_edge(self,edge):
        self._edges.add(edge); self._out[edge.source].add(edge); self._in[edge.target].add(edge); self._sorted_edges=None; self._stable_digest=None
    def outgoing(self,node_id,relation=None): return tuple(sorted(e for e in self._out.get(node_id,()) if relation is None or e.relation is relation))
    def incoming(self,node_id,relation=None): return tuple(sorted(e for e in self._in.get(node_id,()) if relation is None or e.relation is relation))
    def bounded_outgoing(
        self,
        node_id: str,
        *,
        limit: int,
        relation: KnowledgeRelation | None = None,
        target_id: str | None = None,
        target_ids: frozenset[str] | None = None,
        target_predicate: Callable[[str], bool] | None = None,
    ) -> tuple[tuple[KnowledgeEdge, ...], int]:
        """Return the first canonical outgoing edges and the exact match count.

        The query scans the selected adjacency once and retains at most
        ``limit`` edges.  It therefore avoids materializing and sorting a
        high-degree node's complete adjacency while preserving the ordering of
        :meth:`outgoing` for the retained prefix.
        """

        return self._bounded_edges(
            self._out.get(node_id, ()),
            limit=limit,
            relation=relation,
            endpoint_id=target_id,
            endpoint_ids=target_ids,
            endpoint_predicate=target_predicate,
            endpoint="target",
        )

    def bounded_incoming(
        self,
        node_id: str,
        *,
        limit: int,
        relation: KnowledgeRelation | None = None,
        source_id: str | None = None,
        source_ids: frozenset[str] | None = None,
        source_predicate: Callable[[str], bool] | None = None,
    ) -> tuple[tuple[KnowledgeEdge, ...], int]:
        """Return the first canonical incoming edges and the exact match count."""

        return self._bounded_edges(
            self._in.get(node_id, ()),
            limit=limit,
            relation=relation,
            endpoint_id=source_id,
            endpoint_ids=source_ids,
            endpoint_predicate=source_predicate,
            endpoint="source",
        )

    def bounded_incident(
        self,
        node_id: str,
        *,
        limit: int,
        relation: KnowledgeRelation | None = None,
    ) -> tuple[tuple[tuple[str, KnowledgeEdge], ...], int]:
        """Return a bounded deterministic incident-edge prefix and exact count.

        Self-loops are reported once for each direction, matching a combined
        call to :meth:`incoming` and :meth:`outgoing`.  Ordering is by relation,
        direction, neighbouring node identity, and evidence, which is the
        canonical direct-relationship order used by PR134 explanations.
        """

        if limit < 1:
            raise ValueError("bounded knowledge graph query limit must be positive")

        def eligible():
            nonlocal total
            for direction, edges in (
                ("incoming", self._in.get(node_id, ())),
                ("outgoing", self._out.get(node_id, ())),
            ):
                for edge in edges:
                    if relation is not None and edge.relation is not relation:
                        continue
                    total += 1
                    yield direction, edge

        def sort_key(item: tuple[str, KnowledgeEdge]):
            direction, edge = item
            neighbor_id = edge.source if direction == "incoming" else edge.target
            return (
                edge.relation.value,
                direction,
                neighbor_id,
                edge.evidence,
                edge.source,
                edge.target,
            )

        total = 0
        selected = tuple(heapq.nsmallest(limit, eligible(), key=sort_key))
        return selected, total

    @staticmethod
    def _bounded_edges(
        edges,
        *,
        limit: int,
        relation: KnowledgeRelation | None,
        endpoint_id: str | None,
        endpoint_ids: frozenset[str] | None,
        endpoint_predicate: Callable[[str], bool] | None,
        endpoint: str,
    ) -> tuple[tuple[KnowledgeEdge, ...], int]:
        if limit < 1:
            raise ValueError("bounded knowledge graph query limit must be positive")

        def eligible():
            nonlocal total
            for edge in edges:
                if relation is not None and edge.relation is not relation:
                    continue
                if endpoint_id is not None and getattr(edge, endpoint) != endpoint_id:
                    continue
                if endpoint_ids is not None and getattr(edge, endpoint) not in endpoint_ids:
                    continue
                if (
                    endpoint_predicate is not None
                    and not endpoint_predicate(getattr(edge, endpoint))
                ):
                    continue
                total += 1
                yield edge

        total = 0
        selected = tuple(heapq.nsmallest(limit, eligible()))
        return selected, total
    def by_kind(self,kind): return tuple(node for node in self.nodes if node.kind is kind)
    def find(self,name): return tuple(node for node in self.nodes if node.name==name)
    def neighborhood(self,node_id,depth=1):
        seen={node_id}; q=deque([(node_id,0)])
        while q:
            cur,d=q.popleft()
            if d>=depth: continue
            for e in (*self._out.get(cur,()),*self._in.get(cur,())):
                nxt=e.target if e.source==cur else e.source
                if nxt not in seen: seen.add(nxt); q.append((nxt,d+1))
        return tuple(self._nodes[x] for x in sorted(seen) if x in self._nodes)

    def degree_summaries(
        self,
        *,
        relations: Iterable[KnowledgeRelation] | None = None,
        subject_kinds: Iterable[KnowledgeKind] | None = None,
        neighbor_kinds: Iterable[KnowledgeKind] | None = None,
        subject_ids: Iterable[str] | None = None,
        include_zero: bool = True,
    ) -> tuple[KnowledgeDegreeSummary, ...]:
        """Collect distinct-neighbour degrees in one ``O(V + E)`` pass.

        Relationship and endpoint-kind filters make the meaning of a degree
        explicit.  Multiple canonical edges with different evidence do not
        inflate the count for the same neighbour and relationship. Deterministic
        result materialization sorts only the selected subject identifiers.
        """

        selected_relations = None if relations is None else frozenset(relations)
        selected_subjects = None if subject_kinds is None else frozenset(subject_kinds)
        selected_neighbors = None if neighbor_kinds is None else frozenset(neighbor_kinds)
        selected_ids = None if subject_ids is None else frozenset(subject_ids)
        node_ids = {
            node.id
            for node in self._nodes.values()
            if selected_subjects is None or node.kind in selected_subjects
            if selected_ids is None or node.id in selected_ids
        }
        incoming: dict[str, set[str]] = defaultdict(set)
        outgoing: dict[str, set[str]] = defaultdict(set)
        incoming_by_relation: dict[tuple[str, KnowledgeRelation], set[str]] = defaultdict(set)
        outgoing_by_relation: dict[tuple[str, KnowledgeRelation], set[str]] = defaultdict(set)

        for edge in self._edges:
            if selected_relations is not None and edge.relation not in selected_relations:
                continue
            source = self._nodes.get(edge.source)
            target = self._nodes.get(edge.target)
            if source is None or target is None:
                continue
            if edge.source in node_ids and (
                selected_neighbors is None or target.kind in selected_neighbors
            ):
                outgoing[edge.source].add(edge.target)
                outgoing_by_relation[(edge.source, edge.relation)].add(edge.target)
            if edge.target in node_ids and (
                selected_neighbors is None or source.kind in selected_neighbors
            ):
                incoming[edge.target].add(edge.source)
                incoming_by_relation[(edge.target, edge.relation)].add(edge.source)

        result = []
        relation_order = tuple(sorted(selected_relations or tuple(KnowledgeRelation), key=lambda item: item.value))
        selected_ids = (
            node_ids
            if include_zero
            else set(incoming).union(outgoing)
        )
        for node_id in sorted(selected_ids):
            breakdown = tuple(
                KnowledgeRelationDegree(
                    relation,
                    len(incoming_by_relation.get((node_id, relation), ())),
                    len(outgoing_by_relation.get((node_id, relation), ())),
                )
                for relation in relation_order
                if incoming_by_relation.get((node_id, relation))
                or outgoing_by_relation.get((node_id, relation))
            )
            result.append(KnowledgeDegreeSummary(
                node_id,
                len(incoming.get(node_id, ())),
                len(outgoing.get(node_id, ())),
                breakdown,
            ))
        return tuple(result)

    def stable_digest(self) -> str:
        """Hash canonical serialization without materializing one large JSON string."""

        if self._stable_digest is not None:
            return self._stable_digest
        digest = hashlib.sha256()

        def update(value: object) -> None:
            digest.update(json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8"))

        digest.update(b'{"edges":[')
        for index, edge in enumerate(self.edges):
            if index:
                digest.update(b",")
            update({
                "source": edge.source,
                "target": edge.target,
                "kind": edge.relation.value,
                "evidence": list(edge.evidence),
            })
        digest.update(b'],"nodes":[')
        for index, node in enumerate(self.nodes):
            if index:
                digest.update(b",")
            update(self._node_to_dict(node))
        digest.update(b'],"schema_version":1}')
        self._stable_digest = digest.hexdigest()
        return self._stable_digest
    def to_dict(self):
        return {
            'schema_version': 1,
            'nodes': [self._node_to_dict(node) for node in self.nodes],
            'edges': [
                {
                    'source': edge.source,
                    'target': edge.target,
                    'kind': edge.relation.value,
                    'evidence': list(edge.evidence),
                }
                for edge in self.edges
            ],
        }
    @staticmethod
    def _node_to_dict(node):
        metadata=dict(node.metadata)
        qualified_name=node.qualified_name or node.name
        payload={
            'id':node.id,
            'kind':node.kind.value,
            'qualified_name':qualified_name,
            'project_id':node.project_id,
            'language':node.language,
        }
        if node.name != qualified_name:
            payload['name']=node.name
        if node.symbol_id is not None and str(node.symbol_id) != node.id:
            payload['symbol_id']=str(node.symbol_id)
        if metadata:
            payload['metadata']=metadata
        return payload
    @classmethod
    def from_dict(cls,payload):
        if not isinstance(payload,Mapping): raise TypeError('graph payload must be a mapping')
        nodes=[]
        for item in payload.get('nodes',()):
            if not isinstance(item,Mapping): continue
            metadata=dict(item.get('metadata',{})) if isinstance(item.get('metadata'),Mapping) else {}
            raw_symbol=item.get('symbol_id')
            kind=KnowledgeKind(str(item.get('kind','symbol')))
            inferred_symbol=(
                kind in {
                    KnowledgeKind.SYMBOL,
                    KnowledgeKind.PACKAGE,
                    KnowledgeKind.TYPE,
                    KnowledgeKind.METHOD,
                    KnowledgeKind.FIELD,
                }
            )
            nodes.append(KnowledgeNode(
                str(item.get('id','')),
                kind,
                str(item.get('name') or item.get('qualified_name') or item.get('id','')),
                (
                    SymbolId(str(raw_symbol))
                    if raw_symbol is not None
                    else SymbolId(str(item.get('id',''))) if inferred_symbol
                    else None
                ),
                tuple(sorted((str(key),str(value)) for key,value in metadata.items())),
                str(item.get('qualified_name')) if item.get('qualified_name') is not None else None,
                str(item.get('project_id')) if item.get('project_id') is not None else None,
                str(item.get('language') or 'unknown'),
            ))
        edges=[]
        for item in payload.get('edges',()):
            if not isinstance(item,Mapping): continue
            edges.append(KnowledgeEdge(
                str(item.get('source','')),
                str(item.get('target','')),
                KnowledgeRelation(str(item.get('kind','related_to'))),
                tuple(map(str,item.get('evidence',()))),
            ))
        return cls(nodes,edges)
