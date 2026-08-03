from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from types import MappingProxyType
import unicodedata

from moughorai.dependency_graph import DependencyGraph
from moughorai.global_symbols import GlobalSymbolDatabase
from moughorai.knowledge_graph import KnowledgeKind, KnowledgeRelation
from moughorai.knowledge_graph.evidence import (
    is_structured_edge_evidence,
    safe_edge_evidence_refs,
)
from moughorai.measurement import MeasurementSession
from moughorai.semantic_evidence import ConfidenceCalculator, EvidenceIndex, EvidenceKind, EvidenceRecord, EvidenceRole
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import (
    ResolutionStatus,
    SubjectQuery,
)

from .index import (
    SEARCH_INDEX_PRODUCER,
    SemanticIndexEntry,
    SemanticSearchIndex,
)
from .interpreter import interpret_query, query_terms
from .models import (
    QueryInterpretation,
    ScoreComponent,
    SearchCapabilityState,
    SearchIntent,
    SemanticSearchHit,
    SemanticSearchQuery,
    SemanticSearchRequest,
    SemanticSearchResponse,
    StructuredSearchHit,
)


SEARCH_WEIGHTS = MappingProxyType({
    "exact_identity": 0.35,
    "lexical": 0.25,
    "intent_fit": 0.15,
    "graph_proximity": 0.15,
    "evidence_quality": 0.10,
})
MAXIMUM_RELATION_EDGES = 4_096
MAXIMUM_HIT_EVIDENCE = 64
_KIND_ORDER = {kind: index for index, kind in enumerate(KnowledgeKind)}


class SemanticSearchService:
    """PR25-compatible symbol search plus PR135 snapshot semantic search."""

    def __init__(
        self,
        symbols: GlobalSymbolDatabase,
        graph: DependencyGraph | None = None,
    ) -> None:
        self._symbols = symbols
        self._graph = graph
        self._index: SemanticSearchIndex | None = None
        self._measurement = MeasurementSession()

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AtlasSemanticSnapshot,
        *,
        measurement: MeasurementSession | None = None,
    ) -> SemanticSearchService:
        session = measurement or MeasurementSession()
        instance = cls.__new__(cls)
        instance._symbols = None
        instance._graph = None
        instance._measurement = session
        instance._index = SemanticSearchIndex.from_snapshot(
            snapshot, measurement=session,
        )
        return instance

    @property
    def capabilities(self):
        """Return immutable capability metadata without exposing the index."""

        return self._index.capabilities if self._index is not None else ()

    @property
    def index_id(self) -> str | None:
        return self._index.index_id if self._index is not None else None

    def search(self, query: SemanticSearchQuery) -> tuple[SemanticSearchHit, ...]:
        """Preserve the exact PR25 search contract for existing consumers."""

        if self._symbols is None:
            raise TypeError("snapshot search uses search_semantic(), not the PR25 search() API")
        allowed = None
        if query.related_to is not None:
            if self._graph is None:
                return ()
            allowed = self._related(query)
        hits = []
        needle = (query.text or "").casefold().strip()
        for symbol in self._symbols.symbols:
            if query.kinds and symbol.kind not in query.kinds:
                continue
            if query.owner_id is not None and symbol.owner_id != query.owner_id:
                continue
            if query.source_prefix is not None and (
                symbol.source is None
                or not self._under(symbol.source, query.source_prefix)
            ):
                continue
            if allowed is not None and symbol.id not in allowed:
                continue
            score = 0
            reasons = []
            if needle:
                simple = symbol.name.casefold()
                qualified = symbol.qualified_name.casefold()
                if simple == needle:
                    score += 100
                    reasons.append("exact-name")
                elif qualified == needle:
                    score += 95
                    reasons.append("exact-qualified-name")
                elif simple.startswith(needle):
                    score += 70
                    reasons.append("name-prefix")
                elif needle in simple:
                    score += 50
                    reasons.append("name-contains")
                elif needle in qualified:
                    score += 30
                    reasons.append("qualified-name-contains")
                else:
                    continue
            else:
                reasons.append("filters")
            hits.append(SemanticSearchHit(symbol, score, tuple(reasons)))
        hits.sort(key=lambda hit: (
            -hit.score, hit.symbol.qualified_name, hit.symbol.kind.value,
        ))
        return tuple(hits[:query.limit] if query.limit is not None else hits)

    def search_semantic(
        self,
        request: SemanticSearchRequest,
    ) -> SemanticSearchResponse:
        if self._index is None:
            raise TypeError("PR135 semantic search requires a snapshot-backed service")
        if not isinstance(request, SemanticSearchRequest):
            raise TypeError("semantic search requires a SemanticSearchRequest")
        index = self._index
        with self._measurement.scope(
            "semantic_search.interpret",
            consumer="semantic-search",
            sample_key=index.index_id,
        ) as measured:
            interpretation = interpret_query(request)
            measured.add_units(len(interpretation.terms))

        limitations = set(index.limitations)
        exact_ids: set[str] = set()
        relation_ids: set[str] = set()
        relation_evidence: dict[str, list[EvidenceRecord]] = defaultdict(list)
        identity_mode = (
            SearchIntent.EXACT_IDENTITY in interpretation.intents
            and SearchIntent.CONCEPT not in interpretation.intents
        )

        with self._measurement.scope(
            "semantic_search.retrieve",
            consumer="semantic-search",
            sample_key=index.index_id,
        ) as measured:
            candidate_ids: set[str] = set()
            scope_filters = dict(interpretation.filters)
            candidate_scope = index.scope_ids(
                project=request.project or scope_filters.get("project"),
                module=request.module or scope_filters.get("module"),
                package=request.package or scope_filters.get("package"),
                language=request.language or scope_filters.get("language"),
            )

            def candidates(values: Iterable[str], label: str) -> set[str]:
                selected = tuple(values)
                if len(selected) > index.MAXIMUM_CANDIDATES:
                    limitations.add(
                        f"{label} candidate retrieval reached the deterministic "
                        f"{index.MAXIMUM_CANDIDATES}-subject bound; additional candidates were not evaluated."
                    )
                    selected = selected[:index.MAXIMUM_CANDIDATES]
                return set(selected)

            if identity_mode:
                resolution = index.resolver.resolve(SubjectQuery(
                    request.text,
                    request.kinds[0] if len(request.kinds) == 1 else None,
                    request.project,
                    request.language,
                ))
                if resolution.status is ResolutionStatus.RESOLVED and resolution.subject is not None:
                    exact_ids.add(resolution.subject.graph_id)
                    candidate_ids.add(resolution.subject.graph_id)
                elif resolution.status is ResolutionStatus.AMBIGUOUS:
                    resolved_ids = {
                        item.graph_id for item in resolution.candidates
                        if candidate_scope is None
                        or candidate_scope.matches(item.graph_id)
                    }
                    resolved_ids.update(index.exact_identity_candidates(
                        request.text,
                        within=candidate_scope,
                    ))
                    if len(resolved_ids) == 1:
                        graph_id = next(iter(resolved_ids))
                        exact_ids.add(graph_id)
                        candidate_ids.add(graph_id)
                    elif resolved_ids:
                        candidate_ids.update(resolved_ids)
                        limitations.update(resolution.limitations)
                        interpretation = _with_ambiguity(
                            interpretation,
                            tuple(
                                entry.subject.canonical_id
                                for graph_id in sorted(resolved_ids)
                                if (entry := index.entry(graph_id)) is not None
                            ),
                        )
                    else:
                        limitations.update(resolution.limitations)
                elif resolution.status is ResolutionStatus.UNAVAILABLE:
                    limitations.update(resolution.limitations)
                else:
                    candidate_ids.update(candidates(
                        index.token_candidates(
                            interpretation.terms, within=candidate_scope,
                        ),
                        "Lexical",
                    ))

            using_value = dict(interpretation.filters).get("using")
            using_project_ids: set[str] = set()
            using_project_evidence: dict[str, list[EvidenceRecord]] = {}
            if using_value:
                using_project_ids, using_project_evidence, using_limits = (
                    self._projects_using(
                        using_value,
                        project=request.project or scope_filters.get("project"),
                    )
                )
                limitations.update(using_limits)
            if interpretation.relation is not None:
                (
                    related,
                    evidence,
                    relation_limits,
                    relation_alternatives,
                ) = self._relational_candidates(interpretation, request)
                candidate_ids.update(related)
                relation_ids.update(related)
                for graph_id, records in evidence.items():
                    relation_evidence[graph_id].extend(records)
                limitations.update(relation_limits)
                if relation_alternatives:
                    interpretation = _with_ambiguity(
                        interpretation, relation_alternatives,
                    )
            elif interpretation.concepts:
                if not interpretation.ambiguous:
                    identity = index.resolver.resolve(SubjectQuery(
                        request.text,
                        request.kinds[0] if len(request.kinds) == 1 else None,
                        request.project,
                        request.language,
                    ))
                    if identity.status is ResolutionStatus.RESOLVED and identity.subject is not None:
                        exact_ids.add(identity.subject.graph_id)
                        candidate_ids.add(identity.subject.graph_id)
                        interpretation = _with_ambiguity(
                            interpretation,
                            (
                                f"identity:{identity.subject.canonical_id}",
                                *(f"concept:{item}" for item in interpretation.concepts),
                            ),
                        )
                if interpretation.ambiguous:
                    concept_groups = tuple(
                        candidates(
                            index.concept_candidates(
                                (concept,), within=candidate_scope,
                            ),
                            f"Concept {concept!r}",
                        )
                        for concept in interpretation.concepts
                    )
                    if concept_groups:
                        candidate_ids.update(set.union(*concept_groups))
                else:
                    candidate_ids.update(candidates(
                        index.conjunctive_concept_candidates(
                            interpretation.concepts, within=candidate_scope,
                        ),
                        "Conjunctive concept",
                    ))
            elif SearchIntent.SUBJECT_KIND in interpretation.intents:
                inferred_kinds = _interpretation_kinds(interpretation)
                if interpretation.subject_terms:
                    subject_text = " ".join(interpretation.subject_terms)
                    resolution = index.resolver.resolve(SubjectQuery(
                        subject_text,
                        inferred_kinds[0] if len(inferred_kinds) == 1 else None,
                        request.project,
                        request.language,
                    ))
                    if resolution.status is ResolutionStatus.RESOLVED and resolution.subject is not None:
                        exact_ids.add(resolution.subject.graph_id)
                        candidate_ids.add(resolution.subject.graph_id)
                    elif resolution.status is ResolutionStatus.AMBIGUOUS:
                        resolved_ids = {
                            item.graph_id for item in resolution.candidates
                            if candidate_scope is None
                            or candidate_scope.matches(item.graph_id)
                        }
                        resolved_ids.update(index.exact_identity_candidates(
                            subject_text,
                            within=candidate_scope,
                        ))
                        if len(resolved_ids) == 1:
                            graph_id = next(iter(resolved_ids))
                            exact_ids.add(graph_id)
                            candidate_ids.add(graph_id)
                        elif resolved_ids:
                            candidate_ids.update(resolved_ids)
                            limitations.update(resolution.limitations)
                            interpretation = _with_ambiguity(
                                interpretation,
                                tuple(
                                    entry.subject.canonical_id
                                    for graph_id in sorted(resolved_ids)
                                    if (entry := index.entry(graph_id)) is not None
                                ),
                            )
                        else:
                            limitations.update(resolution.limitations)
                    else:
                        candidate_ids.update(candidates(
                            index.token_candidates(
                                query_terms(subject_text), within=candidate_scope,
                            ),
                            "Subject-name",
                        ))
                        limitations.update(resolution.limitations)
                else:
                    candidate_ids.update(candidates(
                        index.kind_candidates(
                            inferred_kinds, within=candidate_scope,
                        ),
                        "Subject-kind",
                    ))
            elif SearchIntent.UNKNOWN in interpretation.intents:
                resolution = index.resolver.resolve(SubjectQuery(
                    request.text,
                    request.kinds[0] if len(request.kinds) == 1 else None,
                    request.project,
                    request.language,
                ))
                if (
                    resolution.status is ResolutionStatus.RESOLVED
                    and resolution.subject is not None
                    and (
                        candidate_scope is None
                        or candidate_scope.matches(resolution.subject.graph_id)
                    )
                ):
                    exact_ids.add(resolution.subject.graph_id)
                    candidate_ids.add(resolution.subject.graph_id)
                elif resolution.status is ResolutionStatus.AMBIGUOUS:
                    resolved_ids = {
                        item.graph_id
                        for item in resolution.candidates
                        if candidate_scope is None
                        or candidate_scope.matches(item.graph_id)
                    }
                    resolved_ids.update(index.exact_identity_candidates(
                        request.text,
                        within=candidate_scope,
                    ))
                    candidate_ids.update(resolved_ids)
                    limitations.update(resolution.limitations)
                    if resolved_ids:
                        interpretation = _with_ambiguity(
                            interpretation,
                            tuple(
                                entry.subject.canonical_id
                                for graph_id in sorted(resolved_ids)
                                if (entry := index.entry(graph_id)) is not None
                            ),
                        )
                else:
                    candidate_ids.update(candidates(
                        index.token_candidates(
                            interpretation.terms,
                            within=candidate_scope,
                        ),
                        "Unknown-query lexical",
                    ))
                    limitations.update(resolution.limitations)

            if using_value:
                requested_kinds = set(_interpretation_kinds(interpretation)).union(request.kinds)
                project_query = (
                    requested_kinds == {KnowledgeKind.PROJECT}
                    and not interpretation.concepts
                )
                if project_query:
                    candidate_ids.intersection_update(using_project_ids)
                else:
                    candidate_ids = {
                        graph_id
                        for graph_id in candidate_ids
                        if (entry := index.entry(graph_id)) is not None
                        and _matching_project_ids(index, entry, using_project_ids)
                    }
                for graph_id in sorted(candidate_ids):
                    entry = index.entry(graph_id)
                    if entry is None:
                        continue
                    matched_projects = _matching_project_ids(
                        index, entry, using_project_ids,
                    )
                    if not matched_projects:
                        continue
                    relation_ids.add(graph_id)
                    for project_id in matched_projects:
                        relation_evidence[graph_id].extend(
                            using_project_evidence.get(project_id, ())
                        )

            if len(candidate_ids) > index.MAXIMUM_CANDIDATES:
                omitted = len(candidate_ids) - index.MAXIMUM_CANDIDATES
                requested_terms = frozenset(map(_normalize, interpretation.terms))
                requested_concepts = frozenset(interpretation.concepts)

                def retrieval_priority(graph_id: str) -> tuple[object, ...]:
                    entry = index.entry(graph_id)
                    matched_terms = (
                        len(requested_terms.intersection(entry.tokens))
                        if entry is not None else 0
                    )
                    matched_concepts = (
                        len(requested_concepts.intersection(entry.concepts))
                        if entry is not None else 0
                    )
                    structured_matches = matched_concepts + (
                        1 if graph_id in relation_ids else 0
                    )
                    return (
                        0 if graph_id in exact_ids else 1,
                        -(matched_terms + structured_matches),
                        -matched_terms,
                        -structured_matches,
                        graph_id,
                    )

                candidate_ids = set(sorted(
                    candidate_ids, key=retrieval_priority,
                )[:index.MAXIMUM_CANDIDATES])
                limitations.add(
                    f"Global candidate retrieval omitted {omitted} subject(s) at the "
                    f"deterministic {index.MAXIMUM_CANDIDATES}-subject bound."
                )

            entries = tuple(
                entry
                for graph_id in sorted(candidate_ids)
                if (entry := index.entry(graph_id)) is not None
                if _entry_matches(entry, request, interpretation)
            )
            measured.add_units(len(candidate_ids))
            measured.add_objects_produced(len(entries))

        scored: list[StructuredSearchHit] = []
        records_by_subject: dict[str, tuple[EvidenceRecord, ...]] = {}
        with self._measurement.scope(
            "semantic_search.score",
            consumer="semantic-search",
            sample_key=index.index_id,
        ) as measured:
            with self._measurement.scope(
                "semantic_search.evidence",
                consumer="semantic-search",
                sample_key=index.index_id,
            ) as evidence_measurement:
                for entry in entries:
                    hit, hit_records = self._score(
                        entry,
                        request,
                        interpretation,
                        exact=entry.graph_id in exact_ids,
                        graph_match=entry.graph_id in relation_ids,
                        relation_records=tuple(relation_evidence.get(entry.graph_id, ())),
                    )
                    if hit.score <= 0.0 or hit.confidence.score < request.minimum_confidence:
                        continue
                    scored.append(hit)
                    records_by_subject[hit.canonical_subject_id] = hit_records
                evidence_measurement.add_units(sum(len(hit.evidence_ids) for hit in scored))
                evidence_measurement.add_objects_produced(len(scored))
            measured.add_units(len(entries))
            measured.add_objects_produced(len(scored))

        with self._measurement.scope(
            "semantic_search.sort",
            consumer="semantic-search",
            sample_key=index.index_id,
        ) as measured:
            scored.sort(key=lambda hit: (
                -hit.score,
                _KIND_ORDER[hit.kind],
                hit.qualified_name.casefold(),
                hit.qualified_name,
                hit.canonical_subject_id,
            ))
            total = len(scored)
            hits = tuple(scored[:request.limit])
            measured.add_units(total)
            measured.add_objects_produced(len(hits))

        response_evidence = EvidenceIndex(
            record
            for hit in hits
            for record in records_by_subject.get(hit.canonical_subject_id, ())
        ).freeze()

        if interpretation.unsupported_terms:
            limitations.add(
                "Some query terms have no supported structured interpretation: "
                + ", ".join(interpretation.unsupported_terms)
                + "."
            )
        if dict(interpretation.filters).get("relation_ambiguous") == "true":
            limitations.add(
                "'used by' is ambiguous across calls, imports, composition, and "
                "dependencies; supply --relation to select authoritative edge evidence."
            )
        if not hits:
            limitations.add(
                "No evidence-backed result matched; this does not prove the concept or relationship is absent."
            )
        return SemanticSearchResponse(
            request,
            interpretation,
            hits,
            total,
            total - len(hits),
            index.capabilities,
            index.index_id,
            response_evidence.freeze(),
            tuple(limitations),
        )

    def _relational_candidates(
        self,
        interpretation: QueryInterpretation,
        request: SemanticSearchRequest,
    ) -> tuple[
        set[str],
        dict[str, list[EvidenceRecord]],
        set[str],
        tuple[str, ...],
    ]:
        index = self._require_index()
        graph = index.graph
        relation = interpretation.relation
        if graph is None or relation is None:
            return (
                set(), {},
                {"Canonical relationship evidence is unavailable."},
                (),
            )
        capability = next((
            item for item in index.capabilities
            if item.name == f"relation.{relation.value}"
        ), None)
        if capability is None or capability.state in {
            SearchCapabilityState.UNAVAILABLE,
            SearchCapabilityState.INCOMPATIBLE,
        }:
            return (
                set(), {},
                set(capability.limitations if capability else (
                    f"Canonical {relation.value} relationship evidence is unavailable.",
                )),
                (),
            )
        target_text = (
            interpretation.subject_terms[0]
            if interpretation.subject_terms
            else request.text
        )
        # Query scopes constrain returned relationship subjects. They must not
        # silently re-scope the named target (for example, a caller in one
        # project may invoke a type owned by another project).
        resolution = index.resolver.resolve(SubjectQuery(target_text))
        direction = dict(interpretation.filters).get("direction", "incoming")

        def relation_endpoint(graph_id: str) -> bool:
            if direction == "outgoing":
                _, total = graph.bounded_outgoing(
                    graph_id, limit=1, relation=relation,
                )
            else:
                _, total = graph.bounded_incoming(
                    graph_id, limit=1, relation=relation,
                )
            return total > 0

        targets: set[str] = set()
        limitations = set(capability.limitations)
        alternatives: tuple[str, ...] = ()
        if resolution.status is ResolutionStatus.RESOLVED and resolution.subject is not None:
            targets.add(resolution.subject.graph_id)
        elif resolution.status is ResolutionStatus.AMBIGUOUS:
            targets.update(
                item.graph_id for item in resolution.candidates
                if relation_endpoint(item.graph_id)
            )
            limitations.update(resolution.limitations)
        if resolution.status is not ResolutionStatus.RESOLVED:
            lexical_targets = index.token_candidates(
                query_terms(target_text),
                predicate=relation_endpoint,
            )
            if len(lexical_targets) > index.MAXIMUM_CANDIDATES:
                limitations.add(
                    "Relationship target retrieval reached the deterministic "
                    f"{index.MAXIMUM_CANDIDATES}-compatible-subject bound; the "
                    "total may be larger."
                )
            targets.update(lexical_targets[:index.MAXIMUM_CANDIDATES])
        if resolution.status not in {
            ResolutionStatus.RESOLVED,
            ResolutionStatus.AMBIGUOUS,
        }:
            limitations.update(resolution.limitations)
        if len(targets) > 64:
            limitations.add(
                f"Relationship target resolution was bounded at 64 of at least {len(targets)} compatible candidates."
            )
        if resolution.status is ResolutionStatus.AMBIGUOUS:
            alternatives = tuple(sorted({
                *(item.canonical_id for item in resolution.candidates),
                *(
                    entry.subject.canonical_id
                    for graph_id in sorted(targets)[:64]
                    if (entry := index.entry(graph_id)) is not None
                ),
            }))[:64]
        relation_phrase = dict(interpretation.filters).get("relation_phrase", "")
        filters = dict(interpretation.filters)
        candidate_scope = index.scope_ids(
            project=request.project or filters.get("project"),
            module=request.module or filters.get("module"),
            package=request.package or filters.get("package"),
            language=request.language or filters.get("language"),
        )
        found: set[str] = set()
        evidence: dict[str, list[EvidenceRecord]] = defaultdict(list)
        for target in sorted(targets)[:64]:
            ignored_subtype = 0
            if direction == "outgoing":
                edges, total = graph.bounded_outgoing(
                    target,
                    limit=MAXIMUM_RELATION_EDGES,
                    relation=relation,
                    target_predicate=(
                        candidate_scope.matches if candidate_scope is not None else None
                    ),
                )
                pairs = ((edge.target, edge) for edge in edges)
            else:
                edges, total = graph.bounded_incoming(
                    target,
                    limit=MAXIMUM_RELATION_EDGES,
                    relation=relation,
                    source_predicate=(
                        candidate_scope.matches if candidate_scope is not None else None
                    ),
                )
                pairs = ((edge.source, edge) for edge in edges)
            if total > len(edges):
                limitations.add(
                    f"Canonical {relation.value} expansion was bounded at {MAXIMUM_RELATION_EDGES} edges."
                )
            ignored_untraceable = 0
            for candidate_id, edge in pairs:
                structured_refs = tuple(
                    item for item in edge.evidence
                    if is_structured_edge_evidence(item)
                )
                safe_refs = safe_edge_evidence_refs(structured_refs)
                if not safe_refs:
                    ignored_untraceable += 1
                    continue
                if (
                    relation is KnowledgeRelation.INHERITS
                    and relation_phrase in {"implements", "extends"}
                    and not any(
                        _evidence_establishes_inheritance_kind(item, relation_phrase)
                        for item in structured_refs
                    )
                ):
                    ignored_subtype += 1
                    continue
                found.add(candidate_id)
                record = EvidenceRecord.create(
                    EvidenceKind.GRAPH_EDGE,
                    _public_graph_id(index, candidate_id),
                    SEARCH_INDEX_PRODUCER,
                    index.snapshot_id,
                    source_refs=("semantic_graph.edges", *safe_refs),
                    detail={
                        "relation": relation.value,
                        "source": _public_graph_id(index, edge.source),
                        "target": _public_graph_id(index, edge.target),
                    },
                )
                evidence[candidate_id].append(record)
            if ignored_untraceable:
                limitations.add(
                    f"Ignored {ignored_untraceable} canonical {relation.value} edge(s) without safe traceable evidence."
                )
            if ignored_subtype:
                limitations.add(
                    f"Ignored {ignored_subtype} inheritance edge(s) whose evidence "
                    f"does not establish '{relation_phrase}'."
                )
        return found, evidence, limitations, alternatives

    def _projects_using(
        self,
        value: str,
        *,
        project: str | None = None,
    ) -> tuple[set[str], dict[str, list[EvidenceRecord]], set[str]]:
        index = self._require_index()
        graph = index.graph
        if graph is None:
            return set(), {}, {"Canonical dependency evidence is unavailable."}
        target_candidates = index.token_candidates(
            query_terms(value),
            kinds=frozenset({KnowledgeKind.DEPENDENCY, KnowledgeKind.FRAMEWORK}),
        )
        targets = set(target_candidates[:index.MAXIMUM_CANDIDATES])
        projects: set[str] = set()
        evidence: dict[str, list[EvidenceRecord]] = defaultdict(list)
        ignored_untraceable = 0
        project_scope = index.scope_ids(project=project)
        for target in sorted(targets)[:64]:
            edges, total = graph.bounded_incoming(
                target,
                limit=MAXIMUM_RELATION_EDGES,
                relation=KnowledgeRelation.DEPENDS_ON,
                source_predicate=(
                    project_scope.matches if project_scope is not None else None
                ),
            )
            if total > len(edges):
                ignored = total - len(edges)
                ignored_untraceable += ignored
            for edge in edges:
                safe_refs = safe_edge_evidence_refs(edge.evidence)
                if not safe_refs:
                    ignored_untraceable += 1
                    continue
                if index.entry(edge.source) is None:
                    continue
                projects.add(edge.source)
                evidence[edge.source].append(EvidenceRecord.create(
                    EvidenceKind.GRAPH_EDGE,
                    _public_graph_id(index, edge.source),
                    SEARCH_INDEX_PRODUCER,
                    index.snapshot_id,
                    source_refs=("semantic_graph.edges", *safe_refs),
                    detail={
                        "relation": KnowledgeRelation.DEPENDS_ON.value,
                        "source": _public_graph_id(index, edge.source),
                        "target": _public_graph_id(index, edge.target),
                    },
                ))
        limitations = set()
        if len(target_candidates) > index.MAXIMUM_CANDIDATES:
            limitations.add(
                "Dependency target retrieval reached the deterministic "
                f"{index.MAXIMUM_CANDIDATES}-subject bound; the total may be larger."
            )
        if not targets:
            limitations.add(
                "The requested dependency or framework could not be resolved from canonical structured subjects."
            )
        if len(targets) > 64:
            limitations.add(
                f"Dependency target resolution was bounded at 64 of at least {len(targets)} compatible candidates."
            )
        if ignored_untraceable:
            limitations.add(
                f"Ignored or bounded {ignored_untraceable} dependency edge(s) without retained traceable evaluation."
            )
        return projects, evidence, limitations

    def _score(
        self,
        entry: SemanticIndexEntry,
        request: SemanticSearchRequest,
        interpretation: QueryInterpretation,
        *,
        exact: bool,
        graph_match: bool,
        relation_records: tuple[EvidenceRecord, ...],
    ) -> tuple[StructuredSearchHit, tuple[EvidenceRecord, ...]]:
        terms = set(interpretation.terms)
        token_set = set(entry.tokens)
        lexical = len(terms.intersection(token_set)) / len(terms) if terms else 0.0
        normalized = _normalize(request.text)
        if normalized in {
            _normalize(entry.subject.name),
            _normalize(entry.subject.qualified_name),
            _normalize(entry.subject.canonical_id),
        }:
            lexical = 1.0
        requested_concepts = set(interpretation.concepts)
        matched_concepts = requested_concepts.intersection(entry.concepts)
        inferred_kinds = set(_interpretation_kinds(interpretation))
        intent_values = []
        if requested_concepts:
            concept_values = []
            risk = dict(entry.risk)
            for concept in sorted(requested_concepts):
                if concept not in matched_concepts:
                    concept_values.append(0.0)
                elif concept == "risk_hotspot":
                    try:
                        concept_values.append(max(0.0, min(1.0, float(risk.get("score", 1.0)))))
                    except ValueError:
                        concept_values.append(0.0)
                else:
                    concept_values.append(1.0)
            intent_values.append(sum(concept_values) / len(concept_values))
        if inferred_kinds:
            intent_values.append(1.0 if entry.subject.kind in inferred_kinds else 0.0)
        if interpretation.relation is not None:
            intent_values.append(1.0 if graph_match else 0.0)
        intent_fit = sum(intent_values) / len(intent_values) if intent_values else 0.0

        relevant_evidence_ids = {
            evidence_id
            for concept, evidence_id in entry.concept_evidence
            if concept in matched_concepts
        }
        concept_records = [
            record for evidence_id in sorted(relevant_evidence_ids)
            if (record := self._require_index().evidence.get(evidence_id)) is not None
        ]
        node_records: list[EvidenceRecord] = []
        kind_only = (
            SearchIntent.SUBJECT_KIND in interpretation.intents
            and not requested_concepts
            and interpretation.relation is None
        )
        if exact or kind_only:
            node_records.append(EvidenceRecord.create(
                EvidenceKind.GRAPH_NODE,
                entry.subject.canonical_id,
                SEARCH_INDEX_PRODUCER,
                self._require_index().snapshot_id,
                source_refs=("semantic_graph.nodes",),
                detail={
                    "canonical_subject_id": entry.subject.canonical_id,
                    "kind": entry.subject.kind.value,
                    "qualified_name": entry.subject.qualified_name,
                },
            ))
        all_records = (*concept_records, *relation_records, *node_records)
        records_by_id = {record.evidence_id: record for record in all_records}
        omitted_evidence = max(0, len(records_by_id) - MAXIMUM_HIT_EVIDENCE)
        records = [
            records_by_id[evidence_id]
            for evidence_id in sorted(records_by_id)[:MAXIMUM_HIT_EVIDENCE]
        ]
        retained_ids = {record.evidence_id for record in records}
        evidence_index = EvidenceIndex(records, frozen=True)
        roles = (EvidenceRole(
            "structured-search-evidence",
            tuple(record.evidence_id for record in records),
        ),)
        calculator = ConfidenceCalculator()
        confidence = calculator.calculate(roles, evidence_index)
        upstream_caps = dict(entry.concept_confidence)
        applicable_caps = tuple(
            upstream_caps[concept]
            for concept in matched_concepts
            if concept in upstream_caps
        )
        if applicable_caps and confidence.score > min(applicable_caps):
            cap = min(applicable_caps)
            denominator = confidence.support * confidence.agreement
            coverage = min(
                confidence.coverage,
                cap / denominator if denominator else 0.0,
            )
            confidence = calculator.calculate(
                roles, evidence_index, coverage=coverage,
            )
        active_weights = _active_weights_for_hit(
            interpretation,
            exact=exact,
            graph_match=graph_match,
            has_evidence=bool(records),
        )
        values = {
            "exact_identity": 1.0 if exact else 0.0,
            "lexical": lexical,
            "intent_fit": intent_fit,
            "graph_proximity": 1.0 if graph_match else 0.0,
            "evidence_quality": confidence.score,
        }
        component_evidence = {
            "exact_identity": tuple(
                record.evidence_id for record in node_records
                if record.evidence_id in retained_ids
            ),
            "lexical": (),
            "intent_fit": tuple(sorted({
                record.evidence_id for record in (*concept_records, *node_records)
                if record.evidence_id in retained_ids
            })),
            "graph_proximity": tuple(
                record.evidence_id for record in relation_records
                if record.evidence_id in retained_ids
            ),
            "evidence_quality": tuple(record.evidence_id for record in records),
        }
        components = tuple(
            ScoreComponent(
                name,
                values[name],
                active_weights.get(name, 0.0),
                values[name] * active_weights.get(name, 0.0),
                name in active_weights,
                component_evidence[name] if name in active_weights else (),
            )
            for name in SEARCH_WEIGHTS
        )
        score = sum(item.contribution for item in components)
        if not records and not exact:
            # Evidence-free lexical relevance remains monotonic while its
            # maximum stays below the first evidence-backed confidence tier.
            scale = 0.39
            components = tuple(
                ScoreComponent(
                    item.name,
                    item.value,
                    item.weight * scale,
                    item.value * (item.weight * scale),
                    item.available,
                    item.evidence_ids,
                )
                for item in components
            )
            score = sum(item.contribution for item in components)
        limitations = set(entry.limitations)
        if confidence.tier.value == "insufficient":
            limitations.add(
                "Available structured evidence is insufficient for a confident semantic conclusion."
            )
        if exact and requested_concepts and not matched_concepts:
            limitations.add(
                "This hit is an exact identity alternative; no structured evidence established the requested concept."
            )
        if omitted_evidence:
            limitations.add(
                f"{omitted_evidence} additional evidence record(s) were omitted by the per-hit bound."
            )
        relationships = []
        if interpretation.relation is not None and relation_records:
            relation_phrase = dict(interpretation.filters).get("relation_phrase")
            relation_label = (
                relation_phrase
                if interpretation.relation is KnowledgeRelation.INHERITS
                and relation_phrase in {"implements", "extends"}
                else interpretation.relation.value
            )
            relationships.append(
                f"canonical {relation_label} relationship matched"
            )
        capability_sources = {
            source
            for concept, source in entry.concept_sources
            if concept in matched_concepts
        }
        if exact or kind_only:
            capability_sources.add("canonical_graph")
        if relation_records:
            capability_sources.add("canonical_graph")
        hit = StructuredSearchHit(
            canonical_subject_id=entry.subject.canonical_id,
            display_name=entry.subject.name,
            qualified_name=entry.subject.qualified_name,
            kind=entry.subject.kind,
            score=score,
            score_components=components,
            confidence=confidence,
            project=entry.subject.project,
            module=entry.module,
            package=entry.package,
            language=entry.subject.language,
            source_classifications=entry.source_classifications,
            matched_concepts=tuple(matched_concepts),
            capability_sources=tuple(capability_sources),
            evidence_ids=tuple(record.evidence_id for record in records),
            relationships=tuple(relationships),
            risk=entry.risk,
            limitations=tuple(limitations),
        )
        return hit, tuple(records)

    def _require_index(self) -> SemanticSearchIndex:
        if self._index is None:
            raise RuntimeError("snapshot semantic search index is unavailable")
        return self._index

    def _related(self, query: SemanticSearchQuery):
        if self._graph is None:
            return set()
        if not query.relation_kinds:
            return set(
                self._graph.dependents(query.related_to, query.transitive)
                if query.reverse_relation
                else self._graph.dependencies(query.related_to, query.transitive)
            )
        found = set()
        frontier = [query.related_to]
        while frontier:
            current = frontier.pop(0)
            edges = (
                self._graph.incoming(current)
                if query.reverse_relation
                else self._graph.outgoing(current)
            )
            for edge in edges:
                if edge.kind not in query.relation_kinds:
                    continue
                following = edge.source if query.reverse_relation else edge.target
                if following not in found:
                    found.add(following)
                    if query.transitive:
                        frontier.append(following)
        return found

    @staticmethod
    def _under(path, prefix):
        try:
            path.relative_to(prefix)
            return True
        except ValueError:
            return False


def _active_weights_for_hit(
    interpretation: QueryInterpretation,
    *,
    exact: bool,
    graph_match: bool,
    has_evidence: bool,
) -> dict[str, float]:
    active = {"lexical"}
    if exact or SearchIntent.EXACT_IDENTITY in interpretation.intents:
        active.add("exact_identity")
    if (
        interpretation.concepts
        or SearchIntent.SUBJECT_KIND in interpretation.intents
        or interpretation.relation is not None
    ):
        active.add("intent_fit")
    if graph_match:
        active.add("graph_proximity")
    if has_evidence:
        active.add("evidence_quality")
    denominator = sum(SEARCH_WEIGHTS[name] for name in active)
    return {
        name: SEARCH_WEIGHTS[name] / denominator
        for name in SEARCH_WEIGHTS
        if name in active
    }


def _interpretation_kinds(interpretation: QueryInterpretation) -> tuple[KnowledgeKind, ...]:
    raw = dict(interpretation.filters).get("kinds", "")
    result = []
    for item in raw.split(","):
        if not item:
            continue
        try:
            result.append(KnowledgeKind(item))
        except ValueError:
            continue
    return tuple(sorted(set(result), key=lambda item: item.value))


def _entry_matches(
    entry: SemanticIndexEntry,
    request: SemanticSearchRequest,
    interpretation: QueryInterpretation,
) -> bool:
    kinds = set(request.kinds).union(_interpretation_kinds(interpretation))
    if kinds and entry.subject.kind not in kinds:
        return False
    filters = dict(interpretation.filters)
    project = request.project or filters.get("project")
    if project and _normalize(project) not in {
        _normalize(entry.subject.project or ""),
        *(_normalize(item) for item in entry.subject.project_scopes),
    }:
        return False
    module = request.module or filters.get("module")
    if module and _normalize(module) not in {
        _normalize(entry.module or ""),
        *(_normalize(item) for item in entry.module_scopes),
    }:
        return False
    package = request.package or filters.get("package")
    if package and not (
        _normalize(entry.package or "") == _normalize(package)
        or _normalize(entry.subject.qualified_name).startswith(_normalize(package) + ".")
    ):
        return False
    if request.language and _normalize(request.language) != _normalize(entry.subject.language):
        return False
    return True


def _matching_project_ids(
    index: SemanticSearchIndex,
    entry: SemanticIndexEntry,
    project_ids: set[str],
) -> tuple[str, ...]:
    entry_scopes = {
        _normalize(entry.subject.project or ""),
        *(_normalize(item) for item in entry.subject.project_scopes),
    }
    matched = []
    for project_id in sorted(project_ids):
        project = index.entry(project_id)
        if project is None:
            continue
        project_scopes = {
            _normalize(project.subject.name),
            _normalize(project.subject.qualified_name),
            _normalize(project.subject.canonical_id),
            _normalize(project.subject.project or ""),
            *(_normalize(item) for item in project.subject.project_scopes),
        }
        if entry.graph_id == project_id or entry_scopes.intersection(project_scopes):
            matched.append(project_id)
    return tuple(matched)


def _with_ambiguity(
    value: QueryInterpretation,
    alternatives: tuple[str, ...],
) -> QueryInterpretation:
    return QueryInterpretation(
        value.raw_query,
        value.normalized_query,
        value.terms,
        (*value.intents, SearchIntent.AMBIGUOUS),
        value.concepts,
        value.subject_terms,
        value.relation,
        value.filters,
        (*value.alternatives, *alternatives),
        value.unsupported_terms,
        True,
    )


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value.strip()).casefold()


def _public_graph_id(index: SemanticSearchIndex, graph_id: str) -> str:
    entry = index.entry(graph_id)
    return entry.subject.canonical_id if entry is not None else "canonical-subject"


def _evidence_establishes_inheritance_kind(value: str, kind: str) -> bool:
    normalized = value.casefold()
    for separator in (":", ".", "/", "_", "-"):
        normalized = normalized.replace(separator, " ")
    return kind in normalized.split()
