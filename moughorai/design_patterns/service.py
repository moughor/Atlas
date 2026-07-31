from __future__ import annotations

from collections import OrderedDict, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json

from moughorai.call_graph import CallGraph, CallSiteKind
from moughorai.java_architecture import ArchitectureEdgeKind, JavaArchitectureGraph
from moughorai.knowledge_graph import (
    KnowledgeEdge,
    KnowledgeGraph,
    KnowledgeKind,
    KnowledgeNode,
    KnowledgeRelation,
)
from moughorai.semantic_evidence import (
    ConfidenceCalculator,
    ConfidenceTier,
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
    EvidenceRole,
)

from .models import (
    PatternAvailability,
    PatternCapability,
    PatternDetectionReport,
    PatternFinding,
    PatternKind,
    PatternParticipant,
)


@dataclass(frozen=True, slots=True)
class _RelationFact:
    source: str
    target: str
    evidence_id: str
    role: str = ""


@dataclass(frozen=True, slots=True)
class _CallFact:
    source_owner: str
    target_owner: str
    source_method: str | None
    target_method: str | None
    evidence_id: str
    kind: str = "unknown"
    method_name: str = ""


@dataclass(frozen=True, slots=True)
class _ReturnFact:
    owner: str
    target: str
    method_name: str
    evidence_id: str


@dataclass(slots=True)
class _Facts:
    graph: KnowledgeGraph
    evidence: EvidenceIndex
    nodes: dict[str, KnowledgeNode]
    owner_by_member: dict[str, str]
    inheritance: tuple[_RelationFact, ...]
    compositions: tuple[_RelationFact, ...]
    usages: tuple[_RelationFact, ...]
    calls: tuple[_CallFact, ...]
    overrides: tuple[_RelationFact, ...]
    returns: tuple[_ReturnFact, ...]
    architecture_available: bool
    call_graph_available: bool


class PatternDetectionService:
    """Detect PR130 patterns from existing canonical and specialized evidence."""

    PRODUCER_VERSION = "atlas-pr130/1"

    def __init__(
        self,
        *,
        confidence: ConfidenceCalculator | None = None,
        cache_size: int = 8,
    ) -> None:
        if cache_size < 1:
            raise ValueError("cache_size must be positive")
        self._confidence = confidence or ConfidenceCalculator()
        self._cache_size = cache_size
        self._cache: OrderedDict[str, PatternDetectionReport] = OrderedDict()

    def detect(
        self,
        graph: KnowledgeGraph,
        *,
        java_architecture_graphs: Mapping[str, JavaArchitectureGraph] | None = None,
        call_graphs: Mapping[str, CallGraph] | None = None,
    ) -> PatternDetectionReport:
        architecture = dict(java_architecture_graphs or {})
        calls = dict(call_graphs or {})
        fingerprint = self._fingerprint(graph, architecture, calls)
        cached = self._cache.get(fingerprint)
        if cached is not None:
            self._cache.move_to_end(fingerprint)
            return cached

        facts = self._facts(graph, architecture, calls, fingerprint)
        findings = tuple(
            sorted(
                (
                    *self._strategies(facts),
                    *self._factories(facts),
                    *self._builders(facts),
                    *self._adapters(facts),
                    *self._decorators(facts),
                    *self._commands(facts),
                    *self._template_methods(facts),
                ),
                key=self._finding_key,
            )
        )
        referenced_evidence = {
            evidence_id
            for finding in findings
            for evidence_id in finding.evidence_ids
        }
        report_evidence = EvidenceIndex(
            record
            for record in facts.evidence.records
            if record.evidence_id in referenced_evidence
        )
        report = PatternDetectionReport(
            findings,
            self._capabilities(facts),
            report_evidence,
            fingerprint,
            self.PRODUCER_VERSION,
        )
        self._cache[fingerprint] = report
        self._cache.move_to_end(fingerprint)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return report

    def _facts(
        self,
        graph: KnowledgeGraph,
        architecture: Mapping[str, JavaArchitectureGraph],
        call_graphs: Mapping[str, CallGraph],
        fingerprint: str,
    ) -> _Facts:
        evidence = EvidenceIndex()
        nodes = {node.id: node for node in graph.nodes}
        owner_by_member = {
            edge.source: edge.target
            for edge in graph.edges
            if edge.relation is KnowledgeRelation.MEMBER_OF
            and nodes.get(edge.target) is not None
            and nodes[edge.target].kind is KnowledgeKind.TYPE
        }
        inheritance: list[_RelationFact] = []
        compositions: list[_RelationFact] = []
        usages: list[_RelationFact] = []
        calls: list[_CallFact] = []
        overrides: list[_RelationFact] = []
        lineage = f"semantic-graph:{fingerprint}"

        for edge in graph.edges:
            if edge.relation not in {
                KnowledgeRelation.INHERITS,
                KnowledgeRelation.COMPOSES,
                KnowledgeRelation.CALLS,
                KnowledgeRelation.OVERRIDES,
            }:
                continue
            evidence_id = evidence.add(self._canonical_evidence(edge, nodes, lineage))
            if edge.relation is KnowledgeRelation.INHERITS:
                inheritance.append(_RelationFact(edge.source, edge.target, evidence_id))
            elif edge.relation is KnowledgeRelation.COMPOSES:
                source = owner_by_member.get(edge.source, edge.source)
                if self._is_type(nodes, source) and self._is_type(nodes, edge.target):
                    fact = _RelationFact(source, edge.target, evidence_id, "composition")
                    compositions.append(fact)
                    usages.append(fact)
            elif edge.relation is KnowledgeRelation.CALLS:
                source_owner = owner_by_member.get(edge.source, edge.source)
                target_owner = owner_by_member.get(edge.target, edge.target)
                if self._is_type(nodes, source_owner) and self._is_type(nodes, target_owner):
                    calls.append(_CallFact(
                        source_owner,
                        target_owner,
                        edge.source if edge.source in owner_by_member else None,
                        edge.target if edge.target in owner_by_member else None,
                        evidence_id,
                    ))
            else:
                overrides.append(_RelationFact(edge.source, edge.target, evidence_id))

        returns: list[_ReturnFact] = []
        type_lookup = self._type_lookup(graph)
        method_lookup = self._method_lookup(graph)
        for project, java_graph in sorted(architecture.items()):
            for edge in sorted(
                java_graph.edges,
                key=lambda item: (
                    item.source, item.target, item.kind.value, item.role,
                ),
            ):
                source = self._resolve(type_lookup, project, edge.source)
                target = self._resolve(type_lookup, project, edge.target)
                if source is None or target is None:
                    continue
                evidence_id = evidence.add(
                    self._architecture_evidence(project, edge, source, target, lineage)
                )
                if edge.kind in {
                    ArchitectureEdgeKind.FIELD_TYPE,
                    ArchitectureEdgeKind.CONSTRUCTOR_PARAMETER,
                    ArchitectureEdgeKind.METHOD_PARAMETER,
                }:
                    usage = _RelationFact(source, target, evidence_id, edge.kind.value)
                    usages.append(usage)
                    if edge.kind is ArchitectureEdgeKind.FIELD_TYPE:
                        compositions.append(usage)
                elif edge.kind is ArchitectureEdgeKind.METHOD_RETURN:
                    returns.append(_ReturnFact(
                        source,
                        target,
                        edge.role.partition(":")[2],
                        evidence_id,
                    ))

        for project, call_graph in sorted(call_graphs.items()):
            for edge in call_graph.edges:
                source_owner = self._resolve(type_lookup, project, edge.caller.owner)
                target_owner = self._resolve(type_lookup, project, edge.callee.owner)
                if source_owner is None or target_owner is None:
                    continue
                source_method = self._resolve(
                    method_lookup, project, edge.caller.qualified_name,
                )
                target_method = self._resolve(
                    method_lookup, project, edge.callee.qualified_name,
                )
                evidence_id = evidence.add(
                    self._call_evidence(
                        project, edge, source_owner, target_owner, lineage,
                    )
                )
                calls.append(_CallFact(
                    source_owner,
                    target_owner,
                    source_method,
                    target_method,
                    evidence_id,
                    edge.kind.value,
                    edge.caller.name,
                ))

        return _Facts(
            graph,
            evidence,
            nodes,
            owner_by_member,
            tuple(sorted(inheritance, key=self._relation_key)),
            tuple(sorted(set(compositions), key=self._relation_key)),
            tuple(sorted(set(usages), key=self._relation_key)),
            tuple(sorted(set(calls), key=self._call_key)),
            tuple(sorted(overrides, key=self._relation_key)),
            tuple(sorted(set(returns), key=lambda item: (
                item.owner, item.target, item.method_name, item.evidence_id,
            ))),
            bool(architecture),
            bool(call_graphs) or any(
                edge.relation is KnowledgeRelation.CALLS for edge in graph.edges
            ),
        )

    def _strategies(self, facts: _Facts) -> tuple[PatternFinding, ...]:
        children = self._children(facts.inheritance)
        result = []
        for abstraction, implementations in sorted(children.items()):
            if len({item.source for item in implementations}) < 2:
                continue
            clients = tuple(
                item for item in facts.usages
                if item.target == abstraction
                and item.source not in {edge.source for edge in implementations}
            )
            for client in clients:
                participants = (
                    self._participant(facts, "abstraction", abstraction),
                    self._participant(facts, "client", client.source),
                    *(
                        self._participant(facts, "implementation", item.source)
                        for item in implementations
                    ),
                )
                finding = self._finding(
                    facts,
                    PatternKind.STRATEGY,
                    participants,
                    (
                        EvidenceRole(
                            "multiple implementations",
                            tuple(item.evidence_id for item in implementations),
                        ),
                        EvidenceRole("client abstraction usage", (client.evidence_id,)),
                    ),
                    "Multiple implementations are consumed through a shared abstraction.",
                    (
                        "Runtime strategy selection is not proven without resolved call or data-flow evidence.",
                    ),
                )
                if finding is not None:
                    result.append(finding)
        return tuple(result)

    def _factories(self, facts: _Facts) -> tuple[PatternFinding, ...]:
        if not (facts.architecture_available and facts.call_graph_available):
            return ()
        children = self._children(facts.inheritance)
        result = []
        for returned in facts.returns:
            products = children.get(returned.target, ())
            product_ids = {item.source for item in products}
            created = tuple(
                item for item in facts.calls
                if item.source_owner == returned.owner
                and item.method_name == returned.method_name
                and item.kind == CallSiteKind.CONSTRUCTOR.value
                and item.target_owner in product_ids
            )
            if len({item.target_owner for item in created}) < 2:
                continue
            selected = tuple(
                item for item in products
                if item.source in {call.target_owner for call in created}
            )
            participants = (
                self._participant(facts, "creator", returned.owner),
                self._participant(facts, "product_abstraction", returned.target),
                *(
                    self._participant(facts, "concrete_product", item.source)
                    for item in selected
                ),
            )
            finding = self._finding(
                facts,
                PatternKind.FACTORY,
                participants,
                (
                    EvidenceRole("abstract product return", (returned.evidence_id,)),
                    EvidenceRole(
                        "concrete product construction",
                        tuple(item.evidence_id for item in created),
                    ),
                    EvidenceRole(
                        "product compatibility",
                        tuple(item.evidence_id for item in selected),
                    ),
                ),
                "A creator returns an abstraction and constructs multiple compatible products.",
                ("Only statically resolved constructor calls are covered.",),
            )
            if finding is not None:
                result.append(finding)
        return tuple(result)

    def _builders(self, facts: _Facts) -> tuple[PatternFinding, ...]:
        by_owner: dict[str, list[_ReturnFact]] = defaultdict(list)
        for item in facts.returns:
            by_owner[item.owner].append(item)
        result = []
        for owner, returns in sorted(by_owner.items()):
            fluent = tuple(
                item for item in returns
                if item.target == owner and item.method_name
            )
            if len({item.method_name for item in fluent}) < 2:
                continue
            for product in sorted(
                (item for item in returns if item.target != owner),
                key=lambda item: (item.target, item.method_name),
            ):
                finding = self._finding(
                    facts,
                    PatternKind.BUILDER,
                    (
                        self._participant(facts, "builder", owner),
                        self._participant(facts, "product", product.target),
                    ),
                    (
                        EvidenceRole(
                            "staged fluent returns",
                            tuple(item.evidence_id for item in fluent),
                        ),
                        EvidenceRole("terminal product return", (product.evidence_id,)),
                    ),
                    "A type exposes multiple self-returning stages and a distinct product return.",
                    (
                        "Typed return structure cannot exclude a non-construction fluent DSL without behavioral evidence.",
                    ),
                )
                if finding is not None:
                    result.append(finding)
        return tuple(result)

    def _adapters(self, facts: _Facts) -> tuple[PatternFinding, ...]:
        result = []
        for inherited in facts.inheritance:
            for composed in facts.compositions:
                if composed.source != inherited.source or composed.target == inherited.target:
                    continue
                delegated = tuple(
                    item for item in facts.calls
                    if item.source_owner == inherited.source
                    and item.target_owner == composed.target
                )
                if not delegated:
                    continue
                finding = self._finding(
                    facts,
                    PatternKind.ADAPTER,
                    (
                        self._participant(facts, "adapter", inherited.source),
                        self._participant(facts, "target", inherited.target),
                        self._participant(facts, "adaptee", composed.target),
                    ),
                    (
                        EvidenceRole("target contract", (inherited.evidence_id,)),
                        EvidenceRole("adaptee composition", (composed.evidence_id,)),
                        EvidenceRole(
                            "adaptee delegation",
                            tuple(item.evidence_id for item in delegated),
                        ),
                    ),
                    "A target implementation delegates behavior to a distinct composed type.",
                    ("Argument and result conversion semantics are not modeled.",),
                )
                if finding is not None:
                    result.append(finding)
        return tuple(result)

    def _decorators(self, facts: _Facts) -> tuple[PatternFinding, ...]:
        result = []
        for inherited in facts.inheritance:
            composed = tuple(
                item for item in facts.compositions
                if item.source == inherited.source and item.target == inherited.target
            )
            delegated = tuple(
                item for item in facts.calls
                if item.source_owner == inherited.source
                and item.target_owner == inherited.target
            )
            if not composed or not delegated:
                continue
            finding = self._finding(
                facts,
                PatternKind.DECORATOR,
                (
                    self._participant(facts, "decorator", inherited.source),
                    self._participant(facts, "component", inherited.target),
                ),
                (
                    EvidenceRole("shared component contract", (inherited.evidence_id,)),
                    EvidenceRole(
                        "wrapped component",
                        tuple(item.evidence_id for item in composed),
                    ),
                    EvidenceRole(
                        "component delegation",
                        tuple(item.evidence_id for item in delegated),
                    ),
                ),
                "A component implementation wraps and delegates to the same contract.",
                ("Transparent preservation of every contract operation is not proven.",),
            )
            if finding is not None:
                result.append(finding)
        return tuple(result)

    def _commands(self, facts: _Facts) -> tuple[PatternFinding, ...]:
        children = self._children(facts.inheritance)
        result = []
        for abstraction, implementations in sorted(children.items()):
            if len({item.source for item in implementations}) < 2:
                continue
            invocations = tuple(
                call for call in facts.calls if call.target_owner == abstraction
            )
            invokers = {
                item.source: item
                for item in facts.compositions
                if item.target == abstraction
            }
            for invocation in invocations:
                invoker_evidence = invokers.get(invocation.source_owner)
                if invoker_evidence is None:
                    continue
                receiver_pairs: list[tuple[_RelationFact, _CallFact]] = []
                for implementation in implementations:
                    for composition in facts.compositions:
                        if composition.source != implementation.source:
                            continue
                        delegated = next((
                            call for call in facts.calls
                            if call.source_owner == implementation.source
                            and call.target_owner == composition.target
                        ), None)
                        if delegated is not None:
                            receiver_pairs.append((composition, delegated))
                if not receiver_pairs:
                    continue
                participants = (
                    self._participant(facts, "command", abstraction),
                    self._participant(facts, "invoker", invocation.source_owner),
                    *(
                        self._participant(facts, "concrete_command", item.source)
                        for item in implementations
                    ),
                    *(
                        self._participant(facts, "receiver", composition.target)
                        for composition, _ in receiver_pairs
                    ),
                )
                finding = self._finding(
                    facts,
                    PatternKind.COMMAND,
                    participants,
                    (
                        EvidenceRole(
                            "command implementations",
                            tuple(item.evidence_id for item in implementations),
                        ),
                        EvidenceRole(
                            "invoker relationship",
                            (invoker_evidence.evidence_id, invocation.evidence_id),
                        ),
                        EvidenceRole(
                            "receiver delegation",
                            tuple(
                                evidence_id
                                for pair in receiver_pairs
                                for evidence_id in (
                                    pair[0].evidence_id, pair[1].evidence_id,
                                )
                            ),
                        ),
                    ),
                    "An invoker delegates an operation object that in turn delegates to a receiver.",
                    ("Command lifecycle and undo semantics are outside the available evidence.",),
                )
                if finding is not None:
                    result.append(finding)
        return tuple(result)

    def _template_methods(self, facts: _Facts) -> tuple[PatternFinding, ...]:
        result = []
        inheritance_pairs = {
            (item.source, item.target): item for item in facts.inheritance
        }
        for overridden in facts.overrides:
            child_owner = facts.owner_by_member.get(overridden.source)
            base_owner = facts.owner_by_member.get(overridden.target)
            if child_owner is None or base_owner is None:
                continue
            inherited = inheritance_pairs.get((child_owner, base_owner))
            if inherited is None:
                continue
            skeleton_calls = tuple(
                item for item in facts.calls
                if item.source_owner == base_owner
                and item.target_method == overridden.target
                and item.source_method is not None
                and item.source_method != overridden.target
            )
            for skeleton in skeleton_calls:
                finding = self._finding(
                    facts,
                    PatternKind.TEMPLATE_METHOD,
                    (
                        self._participant(facts, "base_type", base_owner),
                        self._participant(facts, "template_method", skeleton.source_method),
                        self._participant(facts, "hook_method", overridden.target),
                        self._participant(facts, "subclass", child_owner),
                        self._participant(facts, "override", overridden.source),
                    ),
                    (
                        EvidenceRole("base algorithm call", (skeleton.evidence_id,)),
                        EvidenceRole("hook override", (overridden.evidence_id,)),
                        EvidenceRole("subclass relationship", (inherited.evidence_id,)),
                    ),
                    "A base algorithm invokes a hook overridden by a subclass.",
                    ("The complete ordering of algorithm steps is not modeled.",),
                )
                if finding is not None:
                    result.append(finding)
        return tuple(result)

    def _finding(
        self,
        facts: _Facts,
        pattern: PatternKind,
        participants: tuple[PatternParticipant, ...],
        roles: tuple[EvidenceRole, ...],
        explanation: str,
        limitations: tuple[str, ...],
    ) -> PatternFinding | None:
        confidence = self._confidence.calculate(roles, facts.evidence)
        if confidence.tier is ConfidenceTier.INSUFFICIENT:
            return None
        evidence_ids = tuple(
            evidence_id
            for role in roles
            for evidence_id in role.evidence_ids
        )
        projects = {
            facts.nodes[item.symbol_id].project_id
            for item in participants
            if item.symbol_id in facts.nodes
            and facts.nodes[item.symbol_id].project_id
        }
        languages = {
            facts.nodes[item.symbol_id].language
            for item in participants
            if item.symbol_id in facts.nodes
            and facts.nodes[item.symbol_id].language != "unknown"
        }
        return PatternFinding(
            pattern,
            participants,
            confidence.score,
            confidence.tier,
            evidence_ids,
            explanation,
            limitations,
            f"project:{next(iter(projects))}" if len(projects) == 1 else "repository",
            next(iter(languages)) if len(languages) == 1 else "mixed",
            self.PRODUCER_VERSION,
        )

    def _capabilities(self, facts: _Facts) -> tuple[PatternCapability, ...]:
        relationships = {
            "inheritance": True,
            "typed usage": facts.architecture_available or bool(facts.usages),
            "typed method returns": facts.architecture_available,
            "resolved calls": facts.call_graph_available,
            "composition": facts.architecture_available or bool(facts.compositions),
            "overrides": True,
        }
        requirements = {
            PatternKind.STRATEGY: ("inheritance", "typed usage"),
            PatternKind.FACTORY: (
                "inheritance", "typed method returns", "resolved calls",
            ),
            PatternKind.BUILDER: ("typed method returns",),
            PatternKind.ADAPTER: ("inheritance", "composition", "resolved calls"),
            PatternKind.OBSERVER: (
                "inheritance", "subscription registration", "resolved calls",
            ),
            PatternKind.DECORATOR: (
                "inheritance", "composition", "resolved calls",
            ),
            PatternKind.COMPOSITE: (
                "inheritance", "collection composition", "resolved calls",
            ),
            PatternKind.COMMAND: (
                "inheritance", "composition", "resolved calls",
            ),
            PatternKind.CHAIN_OF_RESPONSIBILITY: (
                "inheritance", "successor composition", "conditional forwarding",
            ),
            PatternKind.STATE: (
                "inheritance", "composition", "state transition",
            ),
            PatternKind.TEMPLATE_METHOD: (
                "inheritance", "overrides", "resolved calls",
            ),
        }
        available = {
            name for name, present in relationships.items() if present
        }
        result = []
        for pattern, required in requirements.items():
            missing = tuple(sorted(set(required).difference(available)))
            result.append(PatternCapability(
                pattern,
                (
                    PatternAvailability.INSUFFICIENT
                    if missing else PatternAvailability.AVAILABLE
                ),
                required,
                tuple(sorted(set(required).intersection(available))),
                tuple(
                    f"Required semantic evidence is unavailable: {name}."
                    for name in missing
                ),
            ))
        return tuple(sorted(result, key=lambda item: item.pattern.value))

    @staticmethod
    def _participant(
        facts: _Facts,
        role: str,
        node_id: str | None,
    ) -> PatternParticipant:
        if node_id is None or node_id not in facts.nodes:
            raise ValueError(f"pattern participant is not canonical: {node_id}")
        node = facts.nodes[node_id]
        return PatternParticipant(
            role,
            node.id,
            node.qualified_name or node.name,
        )

    @staticmethod
    def _children(
        inheritance: tuple[_RelationFact, ...],
    ) -> dict[str, tuple[_RelationFact, ...]]:
        result: dict[str, list[_RelationFact]] = defaultdict(list)
        for item in inheritance:
            result[item.target].append(item)
        return {
            key: tuple(sorted(value, key=PatternDetectionService._relation_key))
            for key, value in result.items()
        }

    @staticmethod
    def _canonical_evidence(
        edge: KnowledgeEdge,
        nodes: Mapping[str, KnowledgeNode],
        lineage: str,
    ) -> EvidenceRecord:
        source = nodes.get(edge.source)
        language = source.language if source is not None else "unknown"
        project = source.project_id if source is not None else None
        return EvidenceRecord.create(
            EvidenceKind.GRAPH_EDGE,
            f"{edge.source}|{edge.relation.value}|{edge.target}",
            "knowledge-graph/1",
            lineage,
            source_refs=edge.evidence,
            scope=f"project:{project}" if project else "repository",
            language=language,
            detail={
                "source": edge.source,
                "target": edge.target,
                "relation": edge.relation.value,
            },
            reliability=1.0,
            specificity=0.9,
        )

    @staticmethod
    def _architecture_evidence(
        project: str,
        edge,
        source: str,
        target: str,
        lineage: str,
    ) -> EvidenceRecord:
        return EvidenceRecord.create(
            EvidenceKind.SEMANTIC_FACT,
            f"{project}|{source}|{edge.kind.value}|{target}|{edge.role}",
            "java-architecture/1",
            lineage,
            source_refs=(
                f"canonical:{source}",
                f"canonical:{target}",
                f"java-role:{edge.role}",
            ),
            scope=f"project:{project}",
            language="java",
            detail={
                "source": source,
                "target": target,
                "kind": edge.kind.value,
                "role": edge.role,
            },
            reliability=0.9,
            specificity=0.8,
        )

    @staticmethod
    def _call_evidence(
        project: str,
        edge,
        source_owner: str,
        target_owner: str,
        lineage: str,
    ) -> EvidenceRecord:
        return EvidenceRecord.create(
            EvidenceKind.ANALYSIS_RESULT,
            (
                f"{project}|{edge.caller.qualified_name}|calls|"
                f"{edge.callee.qualified_name}|{edge.kind.value}"
            ),
            "call-graph/1",
            lineage,
            source_refs=(
                f"canonical:{source_owner}",
                f"canonical:{target_owner}",
                f"call:{edge.caller.qualified_name}->{edge.callee.qualified_name}",
            ),
            scope=f"project:{project}",
            language="java",
            detail={
                "caller": edge.caller.qualified_name,
                "callee": edge.callee.qualified_name,
                "dispatch": edge.dispatch.value,
                "kind": edge.kind.value,
                "status": edge.status.value,
            },
            reliability=0.9,
            specificity=0.9,
        )

    @staticmethod
    def _type_lookup(
        graph: KnowledgeGraph,
    ) -> dict[tuple[str | None, str], tuple[str, ...]]:
        result: dict[tuple[str | None, str], list[str]] = defaultdict(list)
        for node in graph.by_kind(KnowledgeKind.TYPE):
            name = node.qualified_name or node.name
            result[(node.project_id, name)].append(node.id)
            result[(None, name)].append(node.id)
        return {key: tuple(sorted(set(value))) for key, value in result.items()}

    @staticmethod
    def _method_lookup(
        graph: KnowledgeGraph,
    ) -> dict[tuple[str | None, str], tuple[str, ...]]:
        result: dict[tuple[str | None, str], list[str]] = defaultdict(list)
        for node in graph.by_kind(KnowledgeKind.METHOD):
            name = node.qualified_name or node.name
            result[(node.project_id, name)].append(node.id)
            result[(None, name)].append(node.id)
        return {key: tuple(sorted(set(value))) for key, value in result.items()}

    @staticmethod
    def _resolve(
        lookup: Mapping[tuple[str | None, str], tuple[str, ...]],
        project: str,
        qualified_name: str,
    ) -> str | None:
        scoped = lookup.get((project, qualified_name), ())
        if len(scoped) == 1:
            return scoped[0]
        global_matches = lookup.get((None, qualified_name), ())
        return global_matches[0] if len(global_matches) == 1 else None

    @staticmethod
    def _is_type(nodes: Mapping[str, KnowledgeNode], node_id: str) -> bool:
        node = nodes.get(node_id)
        return node is not None and node.kind is KnowledgeKind.TYPE

    @classmethod
    def _fingerprint(
        cls,
        graph: KnowledgeGraph,
        architecture: Mapping[str, JavaArchitectureGraph],
        call_graphs: Mapping[str, CallGraph],
    ) -> str:
        payload = {
            "producer_version": cls.PRODUCER_VERSION,
            "graph": graph.to_dict(),
            "java_architecture": {
                project: {
                    "nodes": [
                        {
                            "qualified_name": item.qualified_name,
                            "type_kind": item.type_kind,
                        }
                        for item in sorted(
                            graph_value.nodes,
                            key=lambda node: node.qualified_name,
                        )
                    ],
                    "edges": [
                        {
                            "source": item.source,
                            "target": item.target,
                            "kind": item.kind.value,
                            "role": item.role,
                        }
                        for item in sorted(
                            graph_value.edges,
                            key=lambda edge: (
                                edge.source, edge.target,
                                edge.kind.value, edge.role,
                            ),
                        )
                    ],
                    "unresolved": [
                        {
                            "owner": item.owner,
                            "role": item.role,
                            "requested_name": item.requested_name,
                            "status": item.status,
                            "candidates": list(item.candidates),
                        }
                        for item in sorted(
                            graph_value.unresolved,
                            key=lambda item: (
                                item.owner, item.role, item.requested_name,
                            ),
                        )
                    ],
                }
                for project, graph_value in sorted(architecture.items())
            },
            "call_graphs": {
                project: graph_value.to_dict()
                for project, graph_value in sorted(call_graphs.items())
            },
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _relation_key(item: _RelationFact):
        return item.source, item.target, item.role, item.evidence_id

    @staticmethod
    def _call_key(item: _CallFact):
        return (
            item.source_owner,
            item.target_owner,
            item.source_method or "",
            item.target_method or "",
            item.kind,
            item.method_name,
            item.evidence_id,
        )

    @staticmethod
    def _finding_key(item: PatternFinding):
        return (
            item.pattern.value,
            tuple(
                (participant.role, participant.symbol_id)
                for participant in item.participants
            ),
        )
