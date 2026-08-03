from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import heapq
import hashlib
import json
from pathlib import PurePosixPath
import re
from types import MappingProxyType
import unicodedata

from moughorai.design_patterns import PatternDetectionReport
from moughorai.knowledge_graph import KnowledgeGraph, KnowledgeKind, KnowledgeRelation
from moughorai.measurement import MeasurementSession
from moughorai.reachability import DeadCodeReport
from moughorai.repository_report.safety import contains_absolute_path, contains_absolute_path_text
from moughorai.risk_analysis import RiskAnalysisReport
from moughorai.semantic_evidence import (
    EvidenceIndex,
    EvidenceKind,
    EvidenceRecord,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import CanonicalSubjectResolver, SubjectCandidate

from .interpreter import CONCEPT_REGISTRY_VERSION
from .models import SearchCapability, SearchCapabilityState


SEARCH_INDEX_SCHEMA_VERSION = 1
SEARCH_INDEX_PRODUCER = "atlas-pr135-index/1"
MAXIMUM_METADATA_TEXT = 2_048
MAXIMUM_ANNOTATION_FACTS = 128
MAXIMUM_EDGE_EVIDENCE_REFS = 64
_WORD = re.compile(r"[\w+:#@/-]+", re.UNICODE)
_EVIDENCE_ID = re.compile(r"evidence:[0-9a-f]{64}\Z")
_LANGUAGE_ID = re.compile(r"[a-z][a-z0-9+.#_-]{0,31}\Z")
_SCOPE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@%+-]{0,255}\Z")
_SYMBOL_EVIDENCE = re.compile(
    r"global_symbol\.metadata:(?:imports|inherits|bases|overrides):"
    r"[A-Za-z_$][A-Za-z0-9_.$#()*\[\],?<>+-]{0,255}\Z"
)
_WORKSPACE_DEPENDENCY_EVIDENCE = re.compile(
    r"workspace\.projects:[A-Za-z0-9_.@%+-]{1,128}:dependencies:"
    r"[A-Za-z0-9_.@%+-]{1,128}\Z"
)
_SEMANTIC_GRAPH_EVIDENCE = re.compile(
    r"semantic_graph:(?:imports|member_of|extends|implements|inheritance|"
    r"composition|calls|overrides|dependencies|depends_on|ownership)\Z"
)
_DEPENDENCY_EVIDENCE = re.compile(
    r"declared_dependency:[A-Za-z0-9_.@%+~:/-]{1,512}\Z"
)
_EVIDENCE_REFERENCE_ID = re.compile(
    r"(?:evidence|report-item|repository-report):[0-9a-f]{64}\Z"
)
_FIXED_EDGE_EVIDENCE = frozenset({
    "global_symbol.owner_id",
    "workspace.root",
    "workspace.projects",
    "repository_summary.projects",
    "repository_summary.module_hierarchy",
    "repository_summary.build_systems",
    "repository_summary.frameworks",
    "semantic_graph.project_id",
    "metadata:domain",
    "metadata:capability",
    "calls",
    "extends",
    "implements",
    "uses",
    "imports",
    "annotated_by",
})
_FRAMEWORK_SCOPES = frozenset({
    "project-local", "test-only", "test-or-sample", "documentation",
    "build-tooling", "optional", "optional-integration",
})
_SAFE_METADATA = frozenset({
    "annotations", "decorators", "inherits", "bases", "overrides",
    "visibility", "entry_point", "generated", "source_set",
    "source_scope", "source_classification", "test",
})
_KNOWN_SOURCE_CLASSIFICATIONS = frozenset({
    "production", "test", "generated", "vendored", "external",
    "unsupported", "unknown",
})
_BUILT_IN_LANGUAGE_IDS = frozenset({
    "groovy", "java", "kotlin", "mixed", "python", "scala",
    "typescript", "unknown", "workspace",
})
_TEST_SOURCE_SCOPES = frozenset({
    "test", "tests", "test-fixtures", "testfixtures", "integration-test",
    "integrationtest",
})
_GENERATED_SOURCE_SCOPES = frozenset({
    "generated", "generated-source", "generated-sources",
})
_SUPPORTED_ARCHITECTURE_NAMES = frozenset({
    "layered", "modular-monolith", "microservices", "hexagonal",
    "clean-architecture", "cqrs", "event-driven", "plugin-architecture",
})


@dataclass(frozen=True, slots=True)
class SemanticIndexEntry:
    graph_id: str
    subject: SubjectCandidate
    tokens: tuple[str, ...]
    concepts: tuple[str, ...]
    concept_evidence: tuple[tuple[str, str], ...]
    concept_sources: tuple[tuple[str, str], ...]
    concept_confidence: tuple[tuple[str, float], ...] = ()
    module: str | None = None
    module_scopes: tuple[str, ...] = ()
    package: str | None = None
    source_classifications: tuple[str, ...] = ()
    risk: tuple[tuple[str, str], ...] = ()
    limitations: tuple[str, ...] = ()


class _ScopeFilter:
    """Membership-only scope predicate backed by immutable index postings."""

    __slots__ = ("_entries", "_language", "_module", "_package", "_project")

    def __init__(
        self,
        entries: Mapping[str, SemanticIndexEntry],
        *,
        project: frozenset[str] | None,
        module: frozenset[str] | None,
        package: str | None,
        language: frozenset[str] | None,
    ) -> None:
        self._entries = entries
        self._project = project
        self._module = module
        self._package = package
        self._language = language

    def matches(self, graph_id: str) -> bool:
        if self._project is not None and graph_id not in self._project:
            return False
        if self._module is not None and graph_id not in self._module:
            return False
        if self._language is not None and graph_id not in self._language:
            return False
        if self._package is not None:
            entry = self._entries.get(graph_id)
            package = _normalize(entry.package or "") if entry is not None else ""
            if package != self._package and not package.startswith(self._package + "."):
                return False
        return True


class SemanticSearchIndex:
    """Immutable, source-free and rebuildable PR135 snapshot index."""

    MAXIMUM_CANDIDATES = 2_000

    def __init__(
        self,
        *,
        snapshot_id: str,
        graph_digest: str,
        index_id: str,
        resolver: CanonicalSubjectResolver,
        entries: Iterable[SemanticIndexEntry],
        evidence: EvidenceIndex,
        capabilities: Iterable[SearchCapability],
        limitations: Iterable[str] = (),
    ) -> None:
        ordered = tuple(sorted(entries, key=lambda item: (
            item.subject.kind.value,
            item.subject.qualified_name.casefold(),
            item.subject.qualified_name,
            item.subject.canonical_id,
        )))
        by_id = {item.graph_id: item for item in ordered}
        public = defaultdict(list)
        identities = defaultdict(list)
        tokens = defaultdict(list)
        concepts = defaultdict(list)
        kinds = defaultdict(list)
        projects = defaultdict(list)
        modules = defaultdict(list)
        languages = defaultdict(list)
        for item in ordered:
            public[item.subject.canonical_id].append(item.graph_id)
            for identity in {
                item.subject.canonical_id,
                item.subject.name,
                item.subject.qualified_name,
            }:
                identities[_normalize(identity)].append(item.graph_id)
            for token in item.tokens:
                tokens[token].append(item.graph_id)
            for concept in item.concepts:
                concepts[concept].append(item.graph_id)
            kinds[item.subject.kind].append(item.graph_id)
            for project in {
                *(item.subject.project_scopes or ()),
                *((item.subject.project,) if item.subject.project else ()),
            }:
                projects[_normalize(project)].append(item.graph_id)
            for module in item.module_scopes:
                modules[_normalize(module)].append(item.graph_id)
            languages[_normalize(item.subject.language)].append(item.graph_id)
        self.snapshot_id = snapshot_id
        self.graph_digest = graph_digest
        self.index_id = index_id
        self.resolver = resolver
        self.graph = resolver.graph
        self.entries = ordered
        self.evidence = evidence.freeze()
        ordered_capabilities = tuple(sorted(capabilities, key=lambda item: item.name))
        if len({item.name for item in ordered_capabilities}) != len(ordered_capabilities):
            raise ValueError("semantic search index capability names must be unique")
        self.capabilities = ordered_capabilities
        self.limitations = tuple(sorted({str(item) for item in limitations if str(item)}))
        self._by_id = MappingProxyType(by_id)
        self._graph_rank = MappingProxyType({
            graph_id: rank for rank, graph_id in enumerate(sorted(by_id))
        })
        self._by_public_id = _freeze(public)
        self._by_identity = _freeze(identities)
        self._by_token = _freeze(tokens)
        self._by_concept = _freeze(concepts)
        self._by_kind = MappingProxyType({key: tuple(value) for key, value in kinds.items()})
        self._by_project = _freeze_sets(projects)
        self._by_module = _freeze_sets(modules)
        self._by_language = _freeze_sets(languages)

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AtlasSemanticSnapshot,
        *,
        measurement: MeasurementSession | None = None,
    ) -> SemanticSearchIndex:
        if not isinstance(snapshot, AtlasSemanticSnapshot):
            raise TypeError("semantic search indexes require an AtlasSemanticSnapshot")
        session = measurement or MeasurementSession()
        with session.scope(
            "semantic_search.index",
            consumer="semantic-search",
            sample_key=snapshot.snapshot_id,
        ) as scope:
            result = _IndexBuilder(snapshot).build()
            scope.add_units(len(result.entries))
            scope.add_objects_produced(len(result.entries))
            scope.set_objects_retained(len(result.entries) + len(result.evidence))
            return result

    def entry(self, graph_id: str) -> SemanticIndexEntry | None:
        return self._by_id.get(graph_id)

    def graph_ids_for_public_id(self, canonical_id: str) -> tuple[str, ...]:
        return self._by_public_id.get(canonical_id, ())

    def exact_identity_candidates(
        self,
        value: str,
        *,
        within: _ScopeFilter | None = None,
    ) -> tuple[str, ...]:
        selected = []
        for graph_id in self._by_identity.get(_normalize(value), ()):
            if within is not None and not within.matches(graph_id):
                continue
            selected.append(graph_id)
            if len(selected) > self.MAXIMUM_CANDIDATES:
                break
        return tuple(selected)

    def token_candidates(
        self,
        terms: Iterable[str],
        *,
        within: _ScopeFilter | None = None,
        kinds: frozenset[KnowledgeKind] | None = None,
        predicate: Callable[[str], bool] | None = None,
    ) -> tuple[str, ...]:
        normalized_terms = tuple(sorted(set(map(_normalize, terms))))
        if not normalized_terms:
            return ()
        capacity = self.MAXIMUM_CANDIDATES + 1
        retained: set[str] = set()
        best: list[tuple[int, int, str]] = []
        for term in normalized_terms:
            for graph_id in self._by_token.get(term, ()):
                if graph_id in retained:
                    continue
                if within is not None and not within.matches(graph_id):
                    continue
                entry = self._by_id.get(graph_id)
                if kinds is not None and (
                    entry is None or entry.subject.kind not in kinds
                ):
                    continue
                if predicate is not None and not predicate(graph_id):
                    continue
                if entry is None:
                    continue
                matched_terms = sum(
                    candidate_term in entry.tokens
                    for candidate_term in normalized_terms
                )
                priority = (
                    matched_terms,
                    -self._graph_rank[graph_id],
                    graph_id,
                )
                if len(best) < capacity:
                    heapq.heappush(best, priority)
                    retained.add(graph_id)
                elif priority > best[0]:
                    _, _, omitted_id = heapq.heapreplace(best, priority)
                    retained.remove(omitted_id)
                    retained.add(graph_id)
        return tuple(
            graph_id
            for _, _, graph_id in sorted(
                best,
                key=lambda item: (-item[0], self._graph_rank[item[2]]),
            )
        )

    def concept_candidates(
        self,
        concepts: Iterable[str],
        *,
        within: _ScopeFilter | None = None,
    ) -> tuple[str, ...]:
        values: set[str] = set()
        for concept in sorted(set(concepts)):
            for graph_id in self._by_concept.get(concept, ()):
                if within is not None and not within.matches(graph_id):
                    continue
                values.add(graph_id)
                if len(values) > self.MAXIMUM_CANDIDATES:
                    return tuple(sorted(values))[: self.MAXIMUM_CANDIDATES + 1]
        return tuple(sorted(values))

    def conjunctive_concept_candidates(
        self,
        concepts: Iterable[str],
        *,
        within: _ScopeFilter | None = None,
    ) -> tuple[str, ...]:
        required = tuple(sorted(set(concepts)))
        if not required:
            return ()
        postings = tuple(self._by_concept.get(concept, ()) for concept in required)
        if any(not posting for posting in postings):
            return ()
        smallest = min(postings, key=lambda posting: (len(posting), posting))
        selected = []
        for graph_id in smallest:
            if within is not None and not within.matches(graph_id):
                continue
            entry = self._by_id.get(graph_id)
            if entry is not None and set(required).issubset(entry.concepts):
                selected.append(graph_id)
                if len(selected) > self.MAXIMUM_CANDIDATES:
                    break
        return tuple(selected)

    def kind_candidates(
        self,
        kinds: Iterable[KnowledgeKind],
        *,
        within: _ScopeFilter | None = None,
    ) -> tuple[str, ...]:
        values: set[str] = set()
        for kind in sorted(set(kinds), key=lambda item: item.value):
            for graph_id in self._by_kind.get(kind, ()):
                if within is not None and not within.matches(graph_id):
                    continue
                values.add(graph_id)
                if len(values) > self.MAXIMUM_CANDIDATES:
                    return tuple(sorted(values))[: self.MAXIMUM_CANDIDATES + 1]
        return tuple(sorted(values))

    def all_graph_ids(
        self,
        *,
        within: _ScopeFilter | None = None,
    ) -> tuple[str, ...]:
        if within is None:
            return tuple(sorted(self._by_id))[: self.MAXIMUM_CANDIDATES + 1]
        selected = []
        for graph_id in sorted(self._by_id):
            if within.matches(graph_id):
                selected.append(graph_id)
                if len(selected) > self.MAXIMUM_CANDIDATES:
                    break
        return tuple(selected)

    def scope_ids(
        self,
        *,
        project: str | None = None,
        module: str | None = None,
        package: str | None = None,
        language: str | None = None,
    ) -> _ScopeFilter | None:
        if all(value is None for value in (project, module, package, language)):
            return None
        return _ScopeFilter(
            self._by_id,
            project=(
                self._by_project.get(_normalize(project), frozenset())
                if project is not None else None
            ),
            module=(
                self._by_module.get(_normalize(module), frozenset())
                if module is not None else None
            ),
            package=_normalize(package) if package is not None else None,
            language=(
                self._by_language.get(_normalize(language), frozenset())
                if language is not None else None
            ),
        )


class _IndexBuilder:
    def __init__(self, snapshot: AtlasSemanticSnapshot) -> None:
        self.snapshot = snapshot
        self.context = snapshot.semantic_context
        self.resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
        self.graph = self.resolver.graph
        raw_graph = self.context.get("semantic_graph")
        self.source_graph_digest = (
            _source_graph_digest(raw_graph)
            if self.graph is not None else "unavailable"
        )
        self.trusted_project_scopes = _trusted_project_scope_ids(
            self.graph, self.context,
        )
        self.trusted_languages = _trusted_language_ids(self.context)
        self.public_to_graph: dict[str, list[str]] = defaultdict(list)
        self.candidates: dict[str, SubjectCandidate] = {}
        if self.graph is not None:
            for node in self.graph.nodes:
                candidate = self.resolver.candidate_for_graph_id(node.id)
                if candidate is not None:
                    candidate = SubjectCandidate(
                        candidate.canonical_id,
                        candidate.kind,
                        candidate.name,
                        candidate.qualified_name,
                        _safe_project_scope(
                            candidate.project, self.trusted_project_scopes,
                        ),
                        _safe_language(candidate.language, self.trusted_languages),
                        None,
                        tuple(filter(None, (
                            _safe_project_scope(
                                item, self.trusted_project_scopes,
                            )
                            for item in candidate.project_scopes
                        ))),
                        candidate.match_basis,
                        candidate.graph_id,
                    )
                    self.candidates[node.id] = candidate
                    self.public_to_graph[candidate.canonical_id].append(node.id)
        self.evidence = EvidenceIndex()
        self.provider_evidence_cache: dict[
            tuple[EvidenceIndex, str], EvidenceRecord | None
        ] = {}
        self.capabilities: list[SearchCapability] = []
        self.limitations: set[str] = set(self.resolver.limitations)
        self.concepts: dict[str, set[str]] = defaultdict(set)
        self.concept_evidence: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        self.concept_sources: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        self.entry_limitations: dict[str, set[str]] = defaultdict(set)
        self.concept_confidence: dict[str, dict[str, float]] = defaultdict(dict)
        self.source_classifications: dict[str, set[str]] = defaultdict(set)
        self.risk: dict[str, dict[str, str]] = defaultdict(dict)
        self.module_memberships = _module_memberships(self.graph)

    def build(self) -> SemanticSearchIndex:
        graph_digest = self.source_graph_digest
        if self.graph is None:
            self.capabilities.extend((
                SearchCapability(
                    "canonical_graph",
                    SearchCapabilityState.UNAVAILABLE,
                    limitations=self.resolver.limitations,
                ),
                SearchCapability(
                    "canonical_identity",
                    SearchCapabilityState.UNAVAILABLE,
                    limitations=self.resolver.limitations,
                ),
                SearchCapability(
                    "structured_symbols",
                    SearchCapabilityState.PARTIAL,
                    limitations=(
                        "Symbols cannot be published as canonical search hits without PR129 identity.",
                    ),
                ),
            ))
            for name in (
                "architecture", "design_patterns", "frameworks", "module_scope",
                "reachability", "risk_analysis",
            ):
                self.capabilities.append(SearchCapability(
                    name,
                    SearchCapabilityState.UNAVAILABLE,
                    limitations=(
                        "Canonical identity is unavailable, so structured findings cannot be joined to searchable subjects.",
                    ),
                ))
            for relation in KnowledgeRelation:
                self.capabilities.append(SearchCapability(
                    f"relation.{relation.value}",
                    SearchCapabilityState.UNAVAILABLE,
                    limitations=(
                        f"Canonical {relation.value} relationship evidence is unavailable.",
                    ),
                ))
            return SemanticSearchIndex(
                snapshot_id=self.snapshot.snapshot_id,
                graph_digest="unavailable",
                index_id=self._fingerprint("unavailable", ()),
                resolver=self.resolver,
                entries=(), evidence=self.evidence, capabilities=self.capabilities,
                limitations=(*self.limitations, "Canonical search is unavailable for this older snapshot."),
            )

        graph_state = (
            SearchCapabilityState.PARTIAL
            if self.resolver.limitations else SearchCapabilityState.AVAILABLE
        )
        self.capabilities.extend((
            SearchCapability(
                "canonical_graph", graph_state,
                1.0 if graph_state is SearchCapabilityState.AVAILABLE else None,
                self.resolver.limitations,
            ),
            SearchCapability("canonical_identity", SearchCapabilityState.AVAILABLE, 1.0),
        ))
        symbols = _mapping_items(self.context.get("symbols"))
        symbol_by_id, conflicting_symbol_ids = _deterministic_symbols(symbols)
        if conflicting_symbol_ids:
            self.limitations.add(
                "Ignored conflicting structured metadata for "
                f"{len(conflicting_symbol_ids)} canonical subject(s)."
            )
        eligible_symbols = sum(
            1 for node in self.graph.nodes
            if node.kind in {KnowledgeKind.TYPE, KnowledgeKind.METHOD, KnowledgeKind.FIELD}
        )
        covered_symbols = sum(
            1
            for graph_id in symbol_by_id
            if (node := self.graph.get(graph_id)) is not None
            and node.kind in {KnowledgeKind.TYPE, KnowledgeKind.METHOD, KnowledgeKind.FIELD}
        )
        symbol_coverage = min(1.0, covered_symbols / eligible_symbols) if eligible_symbols else 0.0
        symbol_state = (
            SearchCapabilityState.AVAILABLE
            if eligible_symbols and covered_symbols == eligible_symbols
            else SearchCapabilityState.PARTIAL
            if covered_symbols
            else SearchCapabilityState.UNAVAILABLE
        )
        self.capabilities.append(SearchCapability(
            "structured_symbols",
            symbol_state,
            round(symbol_coverage, 4) if covered_symbols else None,
            () if symbol_state is SearchCapabilityState.AVAILABLE else (
                "Structured symbol metadata does not cover every eligible canonical subject."
                if covered_symbols else "No structured symbol metadata is available."
                ,
            ),
        ))
        self._index_symbol_facts(symbol_by_id)
        self._provider_capabilities(graph_digest)
        self._relation_capabilities()
        module_nodes = self.graph.by_kind(KnowledgeKind.MODULE)
        module_ids = {item.id for item in module_nodes}
        module_members = sum(
            1 for graph_id, values in self.module_memberships.items()
            if graph_id not in module_ids and values
        )
        self.capabilities.append(SearchCapability(
            "module_scope",
            SearchCapabilityState.PARTIAL if module_members else SearchCapabilityState.UNAVAILABLE,
            None,
            (
                "Module filters use explicit canonical module membership only; project identity is not treated as a module."
                if module_nodes and module_members
                else "Canonical module membership evidence is unavailable."
            ,),
        ))

        entries = []
        languages: set[str] = set()
        for node in self.graph.nodes:
            subject = self.candidates.get(node.id)
            if subject is None:
                continue
            # Candidates were projected once at the index boundary; PR134 paths
            # and untrusted scope/language strings are not retained.
            languages.add(subject.language)
            tokens = _tokens(
                subject.name, subject.qualified_name, subject.kind.value,
            )
            module_names = self.module_memberships.get(node.id, ())
            module = (
                subject.name
                if subject.kind is KnowledgeKind.MODULE
                else module_names[0] if len(module_names) == 1
                else None
            )
            if len(module_names) > 1:
                self.entry_limitations[node.id].add(
                    "Subject has multiple explicit module memberships; no single display module was selected."
                )
            package = _package_name(subject)
            entries.append(SemanticIndexEntry(
                node.id, subject, tokens,
                tuple(sorted(self.concepts.get(node.id, ()))),
                tuple(sorted(
                    (concept, evidence_id)
                    for concept, evidence_ids_for_concept in self.concept_evidence.get(node.id, {}).items()
                    for evidence_id in evidence_ids_for_concept
                )),
                tuple(sorted(
                    (concept, source)
                    for concept, sources_for_concept in self.concept_sources.get(node.id, {}).items()
                    for source in sources_for_concept
                )),
                tuple(sorted(self.concept_confidence.get(node.id, {}).items())),
                module, module_names, package,
                tuple(sorted(self.source_classifications.get(node.id, ()))),
                tuple(sorted(self.risk.get(node.id, {}).items())),
                tuple(sorted(self.entry_limitations.get(node.id, ()))),
            ))
        index_id = self._fingerprint(graph_digest, tuple(sorted(languages)))
        return SemanticSearchIndex(
            snapshot_id=self.snapshot.snapshot_id,
            graph_digest=graph_digest,
            index_id=index_id,
            resolver=self.resolver,
            entries=entries,
            evidence=self.evidence,
            capabilities=self.capabilities,
            limitations=self.limitations,
        )

    def _index_symbol_facts(self, symbols: Mapping[str, Mapping[str, object]]) -> None:
        if self.graph is None:
            return
        for graph_id, symbol in sorted(symbols.items()):
            if self.graph.get(graph_id) is None:
                continue
            raw_metadata = symbol.get("metadata")
            metadata = raw_metadata if isinstance(raw_metadata, Mapping) else {}
            safe: dict[str, str] = {}
            omitted_metadata = 0
            for key, value in metadata.items():
                name = str(key)
                text = str(value)
                if name not in _SAFE_METADATA:
                    continue
                if (
                    len(text) > MAXIMUM_METADATA_TEXT
                    or contains_absolute_path_text(text)
                ):
                    omitted_metadata += 1
                    continue
                safe[name] = text
            if omitted_metadata:
                self.entry_limitations[graph_id].add(
                    f"Ignored {omitted_metadata} unsafe or oversized structured metadata field(s)."
                )
            annotations = (
                _fact_values(safe.get("annotations"))
                | _fact_values(safe.get("decorators"))
            )
            if len(annotations) > MAXIMUM_ANNOTATION_FACTS:
                self.entry_limitations[graph_id].add(
                    f"Annotation indexing was bounded at {MAXIMUM_ANNOTATION_FACTS} structured identities."
                )
                annotations = set(sorted(annotations)[:MAXIMUM_ANNOTATION_FACTS])
            canonical_annotations = {
                item for value in annotations
                if (item := _canonical_annotation(value))
            }
            concepts, trusted_concepts, accepted_annotations, unresolved_known = _annotation_concepts(
                canonical_annotations
            )
            source_classes = {
                _normalize(safe.get(name, ""))
                for name in ("source_set", "source_scope", "source_classification")
            }
            classification_sources = {
                f"symbols.metadata.{name}"
                for name in ("source_set", "source_scope", "source_classification")
                if _normalize(safe.get(name, "")) in {
                    *_KNOWN_SOURCE_CLASSIFICATIONS,
                    *_TEST_SOURCE_SCOPES,
                    *_GENERATED_SOURCE_SCOPES,
                    "main",
                }
            }
            classifications = {
                value for value in source_classes
                if value in _KNOWN_SOURCE_CLASSIFICATIONS
            }
            if (
                source_classes.intersection(_TEST_SOURCE_SCOPES)
                or _truthy(safe.get("test"))
                or accepted_annotations.intersection(_TEST_ANNOTATIONS)
            ):
                classifications.add("test")
            if _truthy(safe.get("test")):
                classification_sources.add("symbols.metadata.test")
            if (
                source_classes.intersection(_GENERATED_SOURCE_SCOPES)
                or _truthy(safe.get("generated"))
                or accepted_annotations.intersection(_GENERATED_ANNOTATIONS)
            ):
                classifications.add("generated")
            if _truthy(safe.get("generated")):
                classification_sources.add("symbols.metadata.generated")
            if "main" in source_classes:
                classifications.add("production")
            self.source_classifications[graph_id].update(classifications)
            if _entry_point_role(safe.get("entry_point")):
                concepts.add("entry_point")
                trusted_concepts.add("entry_point")
            if "generated" in classifications:
                concepts.add("generated_code")
                trusted_concepts.add("generated_code")
            if "test" in classifications:
                concepts.add("testing")
                trusted_concepts.add("testing")
            if unresolved_known:
                self.entry_limitations[graph_id].add(
                    "Known annotation simple names without a trusted namespace are retained only as weak evidence."
                )
            candidate = self.candidates.get(graph_id)
            for concept in sorted(concepts):
                details = {
                    "concept": concept,
                    "annotations": ",".join(sorted(accepted_annotations)),
                    "entry_point": safe.get("entry_point", "") if _entry_point_role(safe.get("entry_point")) else "",
                    "source_classifications": ",".join(sorted(classifications)),
                }
                record = EvidenceRecord.create(
                    EvidenceKind.SEMANTIC_FACT, graph_id, SEARCH_INDEX_PRODUCER,
                    self.snapshot.snapshot_id,
                    source_refs=("symbols.metadata", *sorted(classification_sources)),
                    scope=_safe_scope(candidate.project if candidate else None),
                    language=_safe_language(
                        candidate.language if candidate else "unknown",
                        self.trusted_languages,
                    ),
                    detail=details,
                    limitations=(
                        "Annotation identity is unresolved; this is weak structured evidence.",
                    ) if concept not in trusted_concepts else (),
                    reliability=1.0 if concept in trusted_concepts else 0.55,
                )
                self.evidence.add(record)
                self.concepts[graph_id].add(concept)
                self.concept_evidence[graph_id][concept].add(record.evidence_id)
                self.concept_sources[graph_id][concept].add("structured_symbols")

        for node in self.graph.nodes:
            if node.kind not in {KnowledgeKind.DEPENDENCY, KnowledgeKind.FRAMEWORK}:
                continue
            subject = self.candidates.get(node.id)
            if subject is None:
                continue
            technology_subject = subject.qualified_name
            concepts = _technology_concepts(technology_subject)
            if not concepts:
                continue
            record = EvidenceRecord.create(
                EvidenceKind.REPOSITORY_METADATA, node.id, SEARCH_INDEX_PRODUCER,
                self.snapshot.snapshot_id,
                source_refs=("semantic_graph.nodes",),
                detail={"technology_subject": technology_subject,
                        "concepts": ",".join(sorted(concepts))},
                reliability=0.8,
            )
            self.evidence.add(record)
            self.concepts[node.id].update(concepts)
            for concept in concepts:
                self.concept_evidence[node.id][concept].add(record.evidence_id)
                self.concept_sources[node.id][concept].add("dependency_intelligence")
            self.entry_limitations[node.id].add(
                "Technology presence does not establish use by arbitrary repository symbols."
            )

    def _provider_capabilities(self, graph_digest: str) -> None:
        self._patterns()
        self._reachability(graph_digest)
        self._risks(graph_digest)
        self._architecture()
        framework_concepts = {
            "authentication", "authorization", "rest_endpoint", "controller",
            "service", "repository", "sql", "orm", "scheduling", "caching",
            "messaging", "kafka", "dependency_injection", "configuration",
            "logging", "security", "serialization", "background_job",
            "event_listener", "transaction",
        }
        framework_evidence = any(
            concepts.intersection(framework_concepts)
            for concepts in self.concepts.values()
        )
        frameworks = bool(self.graph and self.graph.by_kind(KnowledgeKind.FRAMEWORK))
        framework_state = (
            SearchCapabilityState.PARTIAL
            if frameworks or framework_evidence else SearchCapabilityState.UNAVAILABLE
        )
        self.capabilities.append(SearchCapability(
            "frameworks", framework_state, None,
            (
                "Framework and dependency evidence is project-scoped; it does not establish repository-wide use."
                if frameworks or framework_evidence
                else "No canonical framework or structured framework evidence is available."
            ,),
        ))

    def _architecture(self) -> None:
        raw = self.context.get("architecture")
        if not isinstance(raw, Mapping):
            self.capabilities.append(SearchCapability(
                "architecture", SearchCapabilityState.UNAVAILABLE,
                limitations=("Compatible architecture findings are unavailable.",),
            ))
            return
        try:
            schema = int(raw.get("schema_version", 1))
        except (TypeError, ValueError):
            schema = -1
        if schema != 1:
            self.capabilities.append(SearchCapability(
                "architecture", SearchCapabilityState.INCOMPATIBLE,
                limitations=("Architecture findings use an unsupported schema.",),
            ))
            return
        findings = _mapping_items(raw.get("findings"))
        mapped_findings = 0
        for finding in findings:
            architecture = str(finding.get("architecture", "")).strip().casefold()
            try:
                confidence = float(finding.get("confidence", 0.0))
            except (TypeError, ValueError):
                continue
            if (
                architecture not in _SUPPORTED_ARCHITECTURE_NAMES
                or not 0.0 <= confidence <= 1.0
            ):
                continue
            graph_ids: set[str] = set()
            evidence_items = _mapping_items(finding.get("evidence"))
            for item in evidence_items:
                reference = str(item.get("reference", "")).strip()
                graph_id = self._graph_id(reference)
                if graph_id is None:
                    graph_id = self._graph_id(f"project:{reference}")
                if graph_id is not None:
                    graph_ids.add(graph_id)
            if not graph_ids:
                continue
            mapped_findings += 1
            specific = {
                "modular-monolith": "architecture_modular_monolith",
                "layered": "architecture_layered",
                "event-driven": "architecture_event_driven",
                "plugin-architecture": "architecture_plugin",
            }.get(architecture)
            concepts = ("architecture", *((specific,) if specific else ()))
            for graph_id in sorted(graph_ids):
                record = EvidenceRecord.create(
                    EvidenceKind.ANALYSIS_RESULT,
                    graph_id,
                    "atlas-pr128-architecture/1",
                    self.snapshot.snapshot_id,
                    source_refs=("architecture.findings",),
                    detail={"architecture": architecture},
                    reliability=0.9,
                )
                self.evidence.add(record)
                for concept in concepts:
                    self.concepts[graph_id].add(concept)
                    self.concept_evidence[graph_id][concept].add(record.evidence_id)
                    self.concept_sources[graph_id][concept].add("architecture")
                    self._cap_concept_confidence(graph_id, concept, confidence)
        coverage = round(mapped_findings / len(findings), 4) if findings else None
        state = (
            SearchCapabilityState.AVAILABLE
            if findings and mapped_findings == len(findings)
            else SearchCapabilityState.PARTIAL
            if findings
            else SearchCapabilityState.UNAVAILABLE
        )
        limitations = ()
        if findings and mapped_findings != len(findings):
            limitations = (
                "Repository-level architecture findings without canonical subject references are not indexed as subject hits.",
            )
        elif not findings:
            limitations = (
                "No compatible traceable architecture finding is available for subject search.",
            )
        self.capabilities.append(SearchCapability(
            "architecture", state, coverage, limitations,
        ))

    def _patterns(self) -> None:
        raw = self.context.get("design_patterns")
        state = SearchCapabilityState.UNAVAILABLE
        limitations: tuple[str, ...] = ("Compatible PR130 design-pattern findings are unavailable.",)
        provider_coverage: float | None = None
        participant_coverage: float | None = None
        if isinstance(raw, Mapping):
            try:
                report = PatternDetectionReport.from_dict(raw)
                if report.producer_version != "atlas-pr130/1":
                    raise ValueError("incompatible producer")
            except (KeyError, TypeError, ValueError):
                state = SearchCapabilityState.INCOMPATIBLE
                limitations = ("PR130 design-pattern data is schema- or producer-incompatible.",)
            else:
                available_capabilities = sum(
                    1 for item in report.capabilities if item.availability.value == "available"
                )
                capability_count = len(report.capabilities)
                provider_coverage = (
                    available_capabilities / capability_count
                    if capability_count else None
                )
                state = (
                    SearchCapabilityState.AVAILABLE
                    if capability_count and available_capabilities == capability_count
                    else SearchCapabilityState.PARTIAL
                    if report.findings or available_capabilities
                    else SearchCapabilityState.UNAVAILABLE
                )
                provider_limitation_count = sum(
                    len(capability.limitations)
                    for capability in report.capabilities
                )
                limitation_values = {
                    "PR130 findings are checksum co-published but do not carry an independent graph digest.",
                }
                if provider_limitation_count:
                    limitation_values.add(
                        f"PR130 reports {provider_limitation_count} capability limitation(s); consult its structured provider record."
                    )
                limitations = tuple(sorted(limitation_values))
                total_participants = 0
                indexed_participants = 0
                usable_findings = 0
                missing_evidence = 0
                for finding in report.findings:
                    concept = f"{finding.pattern.value.replace('-', '_')}_pattern"
                    if concept not in {"builder_pattern", "strategy_pattern"}:
                        concept = "design_pattern"
                    total_participants += len(finding.participants)
                    graph_ids = tuple(sorted({
                        graph_id
                        for participant in finding.participants
                        if (graph_id := self._graph_id(participant.symbol_id)) is not None
                    }))
                    if not graph_ids:
                        continue
                    projected = {
                        graph_id: self._merge_evidence_ids(
                            report.evidence_index,
                            finding.evidence_ids,
                            graph_id=graph_id,
                            source_ref="design_patterns.evidence_index",
                        )
                        for graph_id in graph_ids
                    }
                    if not all(projected.values()):
                        missing_evidence += 1
                        continue
                    usable_findings += 1
                    indexed_participants += len(graph_ids)
                    for graph_id in graph_ids:
                        retained = projected[graph_id]
                        self.concepts[graph_id].update(("design_pattern", concept))
                        for matched_concept in ("design_pattern", concept):
                            self.concept_evidence[graph_id][matched_concept].update(retained)
                            self.concept_sources[graph_id][matched_concept].add("design_patterns")
                            self._cap_concept_confidence(
                                graph_id, matched_concept, finding.confidence,
                            )
                        if finding.limitations:
                            self.entry_limitations[graph_id].add(
                                "The PR130 finding reports limitations; consult its structured provider record."
                            )
                if total_participants:
                    participant_coverage = indexed_participants / total_participants
                extra_limitations = set(limitations)
                if indexed_participants != total_participants:
                    extra_limitations.add(
                        f"Indexed {indexed_participants} of {total_participants} PR130 participant reference(s) with canonical identity and traceable evidence."
                    )
                if missing_evidence:
                    extra_limitations.add(
                        f"Ignored {missing_evidence} PR130 finding(s) without retained safe traceable evidence."
                    )
                limitations = tuple(sorted(extra_limitations))
                if report.findings and not usable_findings:
                    state = SearchCapabilityState.UNAVAILABLE
                elif (
                    indexed_participants != total_participants
                    or missing_evidence
                ):
                    state = SearchCapabilityState.PARTIAL
        coverage_values = tuple(
            value for value in (provider_coverage, participant_coverage)
            if value is not None
        )
        coverage = round(min(coverage_values), 4) if coverage_values else None
        self.capabilities.append(SearchCapability("design_patterns", state, coverage, limitations))

    def _reachability(self, graph_digest: str) -> None:
        raw = self.context.get("reachability")
        compatible_report: DeadCodeReport | None = None
        state = SearchCapabilityState.UNAVAILABLE
        limitations = ("Compatible PR131 reachability findings are unavailable.",)
        if isinstance(raw, Mapping):
            try:
                report = DeadCodeReport.from_dict(raw)
                if report.producer_version != "atlas-pr131/1" or report.graph_digest != graph_digest:
                    raise ValueError("incompatible producer or graph")
            except (KeyError, TypeError, ValueError):
                state = SearchCapabilityState.INCOMPATIBLE
                limitations = ("PR131 reachability data is schema-, producer-, or graph-incompatible.",)
            else:
                compatible_report = report
                status = report.coverage.status.value
                state = (
                    SearchCapabilityState.AVAILABLE if status == "complete"
                    else SearchCapabilityState.PARTIAL if report.findings
                    else SearchCapabilityState.UNAVAILABLE
                )
                limitations = (
                    (
                        f"PR131 reports {len(report.limitations)} limitation(s); consult its structured provider record."
                    ),
                ) if report.limitations else ()
                for finding in report.findings:
                    graph_id = self._graph_id(finding.subject_id)
                    if graph_id is None:
                        continue
                    retained = self._merge_evidence_ids(
                        report.evidence_index,
                        finding.evidence_ids,
                        graph_id=graph_id,
                        source_ref="reachability.evidence_index",
                    )
                    if not retained:
                        state = SearchCapabilityState.PARTIAL
                        continue
                    if finding.source_classification.value != "unknown":
                        self.source_classifications[graph_id].add(
                            finding.source_classification.value
                        )
                    if finding.dead_code_candidate:
                        self.concepts[graph_id].add("dead_code")
                        self.concept_evidence[graph_id]["dead_code"].update(retained)
                        self.concept_sources[graph_id]["dead_code"].add("reachability")
                        self._cap_concept_confidence(graph_id, "dead_code", finding.confidence)
                    if finding.state.value in {"entry_point", "reachable"} and finding.root_categories:
                        self.concepts[graph_id].add("entry_point")
                        self.concept_evidence[graph_id]["entry_point"].update(retained)
                        self.concept_sources[graph_id]["entry_point"].add("reachability")
                        self._cap_concept_confidence(graph_id, "entry_point", finding.confidence)
                    if any(item.value == "service_loader" for item in finding.root_categories):
                        self.concepts[graph_id].add("framework_extension")
                        self.concept_evidence[graph_id]["framework_extension"].update(retained)
                        self.concept_sources[graph_id]["framework_extension"].add("reachability")
                        self._cap_concept_confidence(graph_id, "framework_extension", finding.confidence)
                    if finding.limitations:
                        self.entry_limitations[graph_id].add(
                            "The PR131 finding reports limitations; consult its structured provider record."
                        )
        coverage = None
        if compatible_report is not None and self.graph is not None:
            eligible = sum(
                1 for node in self.graph.nodes
                if node.kind in {
                    KnowledgeKind.TYPE,
                    KnowledgeKind.METHOD,
                    KnowledgeKind.FIELD,
                }
            )
            coverage = (
                round(min(1.0, len(compatible_report.findings) / eligible), 4)
                if eligible else 0.0
            )
        self.capabilities.append(SearchCapability("reachability", state, coverage, limitations))

    def _risks(self, graph_digest: str) -> None:
        raw = self.context.get("risk_analysis")
        compatible_report: RiskAnalysisReport | None = None
        state = SearchCapabilityState.UNAVAILABLE
        limitations = ("Compatible PR132 risk findings are unavailable.",)
        if isinstance(raw, Mapping):
            try:
                report = RiskAnalysisReport.from_dict(raw)
                if report.producer_version != "atlas-pr132/1" or report.graph_digest != graph_digest:
                    raise ValueError("incompatible producer or graph")
            except (KeyError, TypeError, ValueError):
                state = SearchCapabilityState.INCOMPATIBLE
                limitations = ("PR132 risk data is schema-, producer-, or graph-incompatible.",)
            else:
                compatible_report = report
                capability_states = {item.status.value for item in report.capabilities}
                state = (
                    SearchCapabilityState.AVAILABLE
                    if capability_states and capability_states == {"available"}
                    and report.analyzed_subject_count == report.eligible_subject_count
                    else SearchCapabilityState.PARTIAL
                    if report.analyzed_subject_count or report.hotspots
                    else SearchCapabilityState.UNAVAILABLE
                )
                limitations = (
                    (
                        f"PR132 reports {len(report.limitations)} limitation(s); consult its structured provider record."
                    ),
                ) if report.limitations else ()
                for hotspot in report.hotspots:
                    graph_id = self._graph_id(hotspot.subject_id)
                    if graph_id is None:
                        continue
                    retained = self._merge_evidence_ids(
                        report.evidence_index,
                        hotspot.evidence_ids,
                        graph_id=graph_id,
                        source_ref="risk_analysis.evidence_index",
                    )
                    if not retained:
                        state = SearchCapabilityState.PARTIAL
                        continue
                    self.concepts[graph_id].add("risk_hotspot")
                    self.concept_evidence[graph_id]["risk_hotspot"].update(retained)
                    self.concept_sources[graph_id]["risk_hotspot"].add("risk_analysis")
                    self._cap_concept_confidence(
                        graph_id, "risk_hotspot", hotspot.confidence.score,
                    )
                    if hotspot.limitations:
                        self.entry_limitations[graph_id].add(
                            "The PR132 hotspot reports limitations; consult its structured provider record."
                        )
                    self.risk[graph_id].update({"score": str(hotspot.score), "rank": str(hotspot.rank)})
        coverage = None
        if compatible_report is not None and compatible_report.eligible_subject_count:
            coverage = round(min(
                1.0,
                compatible_report.analyzed_subject_count / compatible_report.eligible_subject_count,
            ), 4)
        self.capabilities.append(SearchCapability("risk_analysis", state, coverage, limitations))

    def _relation_capabilities(self) -> None:
        if self.graph is None:
            return
        found = {relation: 0 for relation in KnowledgeRelation}
        untraceable = {relation: 0 for relation in KnowledgeRelation}
        for edge in self.graph.edges:
            if any(is_structured_edge_evidence(item) for item in edge.evidence):
                found[edge.relation] += 1
            else:
                untraceable[edge.relation] += 1
        for relation in KnowledgeRelation:
            count = found[relation]
            omitted = untraceable[relation]
            state = SearchCapabilityState.PARTIAL if count else SearchCapabilityState.UNAVAILABLE
            limitations: tuple[str, ...] = ()
            if relation in {KnowledgeRelation.CALLS, KnowledgeRelation.COMPOSES} and not count:
                limitations = (
                    f"No authoritative canonical {relation.value} evidence is available; absence was not evaluated.",
                )
            elif relation is KnowledgeRelation.INHERITS and count:
                limitations = ("Canonical inheritance does not distinguish extends from implements.",)
            elif not count:
                limitations = (f"No canonical {relation.value} relationship evidence is available.",)
            if omitted:
                state = (
                    SearchCapabilityState.PARTIAL
                    if count else SearchCapabilityState.UNAVAILABLE
                )
                limitations = tuple(sorted({
                    *limitations,
                    f"Ignored {omitted} canonical {relation.value} edge(s) without safe traceable evidence.",
                }))
            if count:
                limitations = tuple(sorted({
                    *limitations,
                    "Only published traceable canonical edges are searchable; repository-wide relation coverage is not asserted.",
                }))
            self.capabilities.append(SearchCapability(
                f"relation.{relation.value}", state,
                None,
                limitations,
            ))

    def _merge_evidence_ids(
        self,
        index: EvidenceIndex,
        evidence_ids: Iterable[str],
        *,
        graph_id: str,
        source_ref: str,
    ) -> tuple[str, ...]:
        retained = []
        for evidence_id in sorted(set(evidence_ids)):
            cache_key = (index, evidence_id)
            if cache_key not in self.provider_evidence_cache:
                candidate = index.get(evidence_id)
                self.provider_evidence_cache[cache_key] = (
                    candidate
                    if candidate is not None
                    and _EVIDENCE_ID.fullmatch(candidate.evidence_id) is not None
                    and not contains_absolute_path(candidate.to_dict())
                    else None
                )
            record = self.provider_evidence_cache[cache_key]
            if record is None:
                continue
            subject = self.candidates.get(graph_id)
            projected = EvidenceRecord.create(
                EvidenceKind.ANALYSIS_RESULT,
                subject.canonical_id if subject is not None else "canonical-subject",
                SEARCH_INDEX_PRODUCER,
                self.snapshot.snapshot_id,
                source_refs=(source_ref, record.evidence_id),
                detail={"upstream_evidence_id": record.evidence_id},
                reliability=record.reliability,
                specificity=record.specificity,
            )
            self.evidence.add(projected)
            retained.append(projected.evidence_id)
        return tuple(retained)

    def _cap_concept_confidence(
        self,
        graph_id: str,
        concept: str,
        confidence: float,
    ) -> None:
        current = self.concept_confidence[graph_id].get(concept)
        value = max(0.0, min(1.0, float(confidence)))
        self.concept_confidence[graph_id][concept] = (
            value if current is None else min(current, value)
        )

    def _graph_id(self, public_id: str) -> str | None:
        if self.graph is None:
            return None
        if self.graph.get(public_id) is not None:
            return public_id
        matches = tuple(self.public_to_graph.get(public_id, ()))
        return matches[0] if len(matches) == 1 else None

    def _fingerprint(self, graph_digest: str, languages: tuple[str, ...]) -> str:
        providers = {
            name: (
                str(value.get("producer_version", "unavailable")),
                int(value.get("schema_version", 0)) if isinstance(value.get("schema_version", 0), int) else 0,
            )
            for name in ("design_patterns", "reachability", "risk_analysis", "architecture")
            if isinstance((value := self.context.get(name)), Mapping)
        }
        identity = {
            "snapshot_id": self.snapshot.snapshot_id,
            "graph_digest": graph_digest,
            "producer": SEARCH_INDEX_PRODUCER,
            "schema_version": SEARCH_INDEX_SCHEMA_VERSION,
            "concept_registry_version": CONCEPT_REGISTRY_VERSION,
            "languages": list(languages),
            "providers": providers,
            "configuration": "default-v1",
        }
        return "semantic-search-index:" + hashlib.sha256(json.dumps(
            identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        ).encode("utf-8")).hexdigest()


def _freeze(values: Mapping[object, list[str]]) -> Mapping:
    return MappingProxyType({key: tuple(sorted(set(items))) for key, items in values.items()})


def _freeze_sets(values: Mapping[object, list[str]]) -> Mapping:
    return MappingProxyType({
        key: frozenset(items) for key, items in values.items()
    })


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value.strip()).casefold()


def _safe_language(
    value: object,
    trusted: frozenset[str] = _BUILT_IN_LANGUAGE_IDS,
) -> str:
    normalized = _normalize(str(value))
    return (
        normalized
        if _LANGUAGE_ID.fullmatch(normalized) and normalized in trusted
        else "unknown"
    )


def _safe_optional_scope(value: object) -> str | None:
    normalized = unicodedata.normalize("NFKC", str(value or "").strip())
    return normalized if _SCOPE_ID.fullmatch(normalized) else None


def _safe_project_scope(
    value: object,
    trusted: frozenset[str],
) -> str | None:
    scope = _safe_optional_scope(value)
    return scope if scope is not None and _normalize(scope) in trusted else None


def _safe_scope(value: object) -> str:
    return _safe_optional_scope(value) or "repository"


def _trusted_project_scope_ids(
    graph: KnowledgeGraph | None,
    context: Mapping[str, object],
) -> frozenset[str]:
    """Return project identities corroborated by canonical/configuration facts."""

    values: set[str] = set()
    if graph is not None:
        for node in graph.by_kind(KnowledgeKind.PROJECT):
            values.update(filter(None, (
                _safe_optional_scope(node.name),
                _safe_optional_scope(node.qualified_name),
                _safe_optional_scope(node.project_id),
            )))
    workspace = context.get("workspace")
    if isinstance(workspace, Mapping):
        for project in _mapping_items(workspace.get("projects")):
            if scope := _safe_optional_scope(project.get("name")):
                values.add(scope)
    return frozenset(_normalize(value) for value in values)


def _trusted_language_ids(context: Mapping[str, object]) -> frozenset[str]:
    """Keep built-in or independently inventoried language identities only."""

    values = set(_BUILT_IN_LANGUAGE_IDS)
    summary = context.get("repository_summary")
    if isinstance(summary, Mapping):
        raw_languages = summary.get(
            "language_file_counts", summary.get("languages"),
        )
        if isinstance(raw_languages, Mapping):
            for value in raw_languages:
                normalized = _normalize(str(value))
                if _LANGUAGE_ID.fullmatch(normalized):
                    values.add(normalized)
    return frozenset(values)


def _tokens(*values: str) -> tuple[str, ...]:
    result: set[str] = set()
    for value in values:
        split_camel = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
        normalized = _normalize(split_camel)
        result.update(match.group(0) for match in _WORD.finditer(normalized))
        result.update(
            part for part in re.split(r"[-:/@]+", normalized) if part
        )
        if normalized:
            result.add(normalized)
    return tuple(sorted(result))


def _deterministic_symbols(
    values: Iterable[Mapping[str, object]],
) -> tuple[dict[str, Mapping[str, object]], frozenset[str]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for value in values:
        identifier = str(value.get("id", "")).strip()
        if identifier:
            grouped[identifier].append(value)
    selected: dict[str, Mapping[str, object]] = {}
    conflicting: set[str] = set()
    for identifier, candidates in sorted(grouped.items()):
        projections: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        for candidate in candidates:
            raw_metadata = candidate.get("metadata")
            metadata = raw_metadata if isinstance(raw_metadata, Mapping) else {}
            projection = {
                "project_id": str(candidate.get("project_id", "")),
                "metadata": {
                    str(key): str(item)
                    for key, item in metadata.items()
                    if str(key) in _SAFE_METADATA
                },
            }
            fingerprint = json.dumps(
                projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
            )
            projections[fingerprint].append(candidate)
        if len(projections) != 1:
            conflicting.add(identifier)
            continue
        fingerprint = next(iter(projections))
        selected[identifier] = min(
            projections[fingerprint],
            key=lambda item: json.dumps(
                dict(item), ensure_ascii=False, separators=(",", ":"),
                sort_keys=True, default=str,
            ),
        )
    return selected, frozenset(conflicting)


def _module_memberships(
    graph: KnowledgeGraph | None,
) -> dict[str, tuple[str, ...]]:
    if graph is None:
        return {}
    modules = {
        node.id: node.name
        for node in graph.nodes
        if node.kind is KnowledgeKind.MODULE
    }
    memberships: dict[str, set[str]] = defaultdict(set)
    children: dict[str, set[str]] = defaultdict(set)
    for module_id, name in modules.items():
        memberships[module_id].add(name)
    for edge in graph.edges:
        if edge.relation in {KnowledgeRelation.OWNS, KnowledgeRelation.PROVIDES}:
            children[edge.source].add(edge.target)
        elif edge.relation in {KnowledgeRelation.MEMBER_OF, KnowledgeRelation.BELONGS_TO}:
            children[edge.target].add(edge.source)
    queue = deque(
        (module_id, module_id, name)
        for module_id, name in sorted(modules.items())
    )
    seen = set(queue)
    while queue:
        parent, origin_module_id, name = queue.popleft()
        for child in sorted(children.get(parent, ())):
            memberships[child].add(name)
            if child in modules and child != origin_module_id:
                continue
            marker = (child, origin_module_id, name)
            if marker not in seen:
                seen.add(marker)
                queue.append(marker)
    return {
        graph_id: tuple(sorted(values))
        for graph_id, values in memberships.items()
    }


def _source_graph_digest(value: object) -> str:
    """Hash the canonical persisted PR129 payload without restoring it twice."""

    if not isinstance(value, Mapping) or value.get("schema_version") != 1:
        return "unavailable"
    raw_nodes = value.get("nodes")
    raw_edges = value.get("edges")
    if (
        not isinstance(raw_nodes, Sequence)
        or isinstance(raw_nodes, (str, bytes, bytearray))
        or not isinstance(raw_edges, Sequence)
        or isinstance(raw_edges, (str, bytes, bytearray))
        or any(not isinstance(item, Mapping) for item in raw_nodes)
        or any(not isinstance(item, Mapping) for item in raw_edges)
    ):
        return "unavailable"
    node_payloads = []
    node_ids: set[str] = set()
    for node in raw_nodes:
        identifier = str(node.get("id", ""))
        if not identifier or identifier in node_ids:
            return "unavailable"
        node_ids.add(identifier)
        try:
            kind = KnowledgeKind(str(node.get("kind", "symbol")))
        except ValueError:
            return "unavailable"
        qualified = (
            str(node.get("qualified_name"))
            if node.get("qualified_name") is not None else None
        )
        name = str(node.get("name") or qualified or identifier)
        qualified_name = qualified or name
        raw_symbol = node.get("symbol_id")
        symbol_id = str(raw_symbol) if raw_symbol is not None else (
            identifier
            if kind in {
                KnowledgeKind.SYMBOL, KnowledgeKind.PACKAGE, KnowledgeKind.TYPE,
                KnowledgeKind.METHOD, KnowledgeKind.FIELD,
            }
            else None
        )
        raw_metadata = node.get("metadata")
        metadata = {
            str(key): str(item)
            for key, item in raw_metadata.items()
        } if isinstance(raw_metadata, Mapping) else {}
        payload: dict[str, object] = {
            "id": identifier,
            "kind": kind.value,
            "qualified_name": qualified_name,
            "project_id": (
                str(node.get("project_id"))
                if node.get("project_id") is not None else None
            ),
            "language": str(node.get("language") or "unknown"),
        }
        if name != qualified_name:
            payload["name"] = name
        if symbol_id is not None and symbol_id != identifier:
            payload["symbol_id"] = symbol_id
        if metadata:
            payload["metadata"] = metadata
        node_payloads.append(payload)

    edge_payloads: set[tuple[str, str, str, tuple[str, ...]]] = set()
    for edge in raw_edges:
        raw_evidence = edge.get("evidence", ())
        if (
            not isinstance(raw_evidence, Sequence)
            or isinstance(raw_evidence, (str, bytes, bytearray))
        ):
            return "unavailable"
        evidence = tuple(map(str, raw_evidence))
        try:
            relation = KnowledgeRelation(
                str(edge.get("kind", "related_to"))
            ).value
        except ValueError:
            return "unavailable"
        edge_payloads.add((
            str(edge.get("source", "")),
            str(edge.get("target", "")),
            relation,
            evidence,
        ))

    digest = hashlib.sha256()

    def update(item: object) -> None:
        digest.update(json.dumps(
            item,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"))

    digest.update(b'{"edges":[')
    for position, (source, target, relation, evidence) in enumerate(sorted(edge_payloads)):
        if position:
            digest.update(b",")
        update({
            "source": source,
            "target": target,
            "kind": relation,
            "evidence": list(evidence),
        })
    digest.update(b'],"nodes":[')
    for position, node in enumerate(sorted(node_payloads, key=lambda item: str(item["id"]))):
        if position:
            digest.update(b",")
        update(node)
    digest.update(b'],"schema_version":1}')
    return digest.hexdigest()


def _mapping_items(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _fact_values(value: object) -> set[str]:
    if value is None:
        return set()
    return {item.strip() for item in str(value).split(",") if item.strip()}


_ANNOTATION_CONCEPTS = {
    # Security annotations with stable framework/API identities.
    "io.quarkus.security.authenticated": ("authentication", "security"),
    "jakarta.annotation.security.declareRoles".casefold(): ("authorization", "security"),
    "jakarta.annotation.security.denyall": ("authorization", "security"),
    "jakarta.annotation.security.rolesallowed": ("authorization", "security"),
    "javax.annotation.security.denyall": ("authorization", "security"),
    "javax.annotation.security.rolesallowed": ("authorization", "security"),
    "org.springframework.security.access.prepost.preauthorize": ("authorization", "security"),
    "org.springframework.security.access.annotation.secured": ("authorization", "security"),
    # JAX-RS and Spring/Micronaut HTTP endpoints.
    **{
        f"{namespace}.{verb}": ("rest_endpoint",)
        for namespace in ("jakarta.ws.rs", "javax.ws.rs")
        for verb in ("get", "post", "put", "delete", "patch", "head", "options")
    },
    **{
        f"org.springframework.web.bind.annotation.{name}": ("rest_endpoint",)
        for name in ("requestmapping", "getmapping", "postmapping", "putmapping", "deletemapping", "patchmapping")
    },
    **{
        f"io.micronaut.http.annotation.{name}": ("rest_endpoint",)
        for name in ("get", "post", "put", "delete", "patch", "head")
    },
    "org.springframework.stereotype.controller": ("controller",),
    "org.springframework.web.bind.annotation.restcontroller": ("controller",),
    "io.micronaut.http.annotation.controller": ("controller",),
    "org.springframework.stereotype.service": ("service",),
    "org.springframework.stereotype.repository": ("repository",),
    "org.springframework.data.jpa.repository.query": ("sql",),
    "jakarta.persistence.namedquery": ("sql",),
    "jakarta.persistence.namednativequery": ("sql",),
    "javax.persistence.namedquery": ("sql",),
    "javax.persistence.namednativequery": ("sql",),
    **{
        f"{namespace}.{name}": ("orm",)
        for namespace in ("jakarta.persistence", "javax.persistence")
        for name in ("entity", "table", "embeddable", "mappedsuperclass", "persistencecontext")
    },
    "org.springframework.scheduling.annotation.scheduled": ("scheduling", "background_job"),
    "io.quarkus.scheduler.scheduled": ("scheduling", "background_job"),
    **{
        f"org.springframework.cache.annotation.{name}": ("caching",)
        for name in ("cacheable", "cacheput", "cacheevict", "cacheconfig")
    },
    "org.springframework.kafka.annotation.kafkalistener": ("kafka", "messaging"),
    "org.eclipse.microprofile.reactive.messaging.incoming": ("messaging",),
    "org.eclipse.microprofile.reactive.messaging.outgoing": ("messaging",),
    "org.springframework.jms.annotation.jmslistener": ("messaging",),
    "jakarta.inject.inject": ("dependency_injection",),
    "javax.inject.inject": ("dependency_injection",),
    "org.springframework.beans.factory.annotation.autowired": ("dependency_injection",),
    "org.springframework.context.annotation.bean": ("dependency_injection",),
    "org.springframework.stereotype.component": ("dependency_injection",),
    "jakarta.enterprise.context.applicationscoped": ("dependency_injection",),
    "jakarta.enterprise.inject.produces": ("dependency_injection",),
    "jakarta.inject.singleton": ("dependency_injection",),
    "org.springframework.context.annotation.configuration": ("configuration",),
    "io.smallrye.config.configmapping": ("configuration",),
    "io.quarkus.runtime.annotations.configroot": ("configuration",),
    "org.eclipse.microprofile.config.inject.configproperty": ("configuration",),
    "com.fasterxml.jackson.annotation.jsonproperty": ("serialization",),
    "com.fasterxml.jackson.annotation.jsoncreator": ("serialization",),
    "com.fasterxml.jackson.annotation.jsontypename": ("serialization",),
    "io.micronaut.serde.annotation.serdeable": ("serialization",),
    "org.springframework.scheduling.annotation.async": ("background_job",),
    "org.springframework.context.event.eventlistener": ("event_listener",),
    "jakarta.enterprise.event.observes": ("event_listener",),
    "javax.enterprise.event.observes": ("event_listener",),
    "org.springframework.transaction.annotation.transactional": ("transaction",),
    "jakarta.transaction.transactional": ("transaction",),
    "javax.transaction.transactional": ("transaction",),
}
_TEST_ANNOTATIONS = frozenset({
    "org.junit.jupiter.api.test",
    "org.junit.jupiter.params.parameterizedtest",
    "org.junit.jupiter.api.repeatedtest",
    "org.junit.jupiter.api.testfactory",
    "org.junit.test",
})
_GENERATED_ANNOTATIONS = frozenset({
    "jakarta.annotation.generated", "javax.annotation.generated", "lombok.generated",
})
_KNOWN_ANNOTATION_SIMPLE_NAMES = frozenset(
    item.rsplit(".", 1)[-1]
    for item in (*_ANNOTATION_CONCEPTS, *_TEST_ANNOTATIONS, *_GENERATED_ANNOTATIONS)
)


def _canonical_annotation(value: str) -> str:
    return value.strip().lstrip("@").partition("(")[0].strip().casefold()


def _annotation_concepts(
    annotations: set[str],
) -> tuple[set[str], set[str], set[str], set[str]]:
    concepts: set[str] = set()
    trusted_concepts: set[str] = set()
    accepted: set[str] = set()
    unresolved_known: set[str] = set()
    for annotation in sorted(annotations):
        mapped = _ANNOTATION_CONCEPTS.get(annotation)
        if mapped is not None:
            concepts.update(mapped)
            trusted_concepts.update(mapped)
            accepted.add(annotation)
        elif annotation in _TEST_ANNOTATIONS or annotation in _GENERATED_ANNOTATIONS:
            accepted.add(annotation)
            trusted_concepts.add(
                "testing" if annotation in _TEST_ANNOTATIONS else "generated_code"
            )
        elif "." not in annotation and annotation in _KNOWN_ANNOTATION_SIMPLE_NAMES:
            unresolved_known.add(annotation)
            accepted.add(annotation)
            simple_mapped = {
                concept
                for qualified, qualified_concepts in _ANNOTATION_CONCEPTS.items()
                if qualified.rsplit(".", 1)[-1] == annotation
                for concept in qualified_concepts
            }
            if any(item.rsplit(".", 1)[-1] == annotation for item in _TEST_ANNOTATIONS):
                simple_mapped.add("testing")
            if any(item.rsplit(".", 1)[-1] == annotation for item in _GENERATED_ANNOTATIONS):
                simple_mapped.add("generated_code")
            concepts.update(simple_mapped)
    return concepts, trusted_concepts, accepted, unresolved_known


def _technology_concepts(value: str) -> set[str]:
    coordinate = _dependency_coordinate(value)
    if coordinate is None:
        return set()
    group, artifact = coordinate
    result: set[str] = set()
    rules = (
        (("org.springframework", "spring-security"), ("authentication", "authorization", "security")),
        (("org.keycloak", "keycloak"), ("authentication", "authorization", "security")),
        (("org.apache.shiro", "shiro"), ("authentication", "authorization", "security")),
        (("org.springframework", "spring-web"), ("rest_endpoint",)),
        (("org.jboss.resteasy", "resteasy"), ("rest_endpoint",)),
        (("org.hibernate", "hibernate"), ("orm", "repository")),
        (("org.springframework.data", "spring-data"), ("orm", "repository")),
        (("com.github.ben-manes.caffeine", "caffeine"), ("caching",)),
        (("org.ehcache", "ehcache"), ("caching",)),
        (("org.apache.kafka", "kafka"), ("kafka", "messaging")),
        (("org.springframework.kafka", "spring-kafka"), ("kafka", "messaging")),
        (("org.springframework.amqp", "spring-rabbit"), ("messaging",)),
        (("org.quartz-scheduler", "quartz"), ("scheduling", "background_job")),
        (("org.slf4j", "slf4j"), ("logging",)),
        (("org.apache.logging.log4j", "log4j"), ("logging",)),
        (("ch.qos.logback", "logback"), ("logging",)),
        (("com.fasterxml.jackson", "jackson"), ("serialization",)),
        (("com.google.code.gson", "gson"), ("serialization",)),
        (("jakarta.inject", "jakarta.inject"), ("dependency_injection",)),
        (("javax.inject", "javax.inject"), ("dependency_injection",)),
        (("org.springframework", "spring-context"), ("dependency_injection",)),
    )
    for (expected_group, artifact_prefix), concepts in rules:
        if group == expected_group or group.startswith(expected_group + "."):
            if artifact == artifact_prefix or artifact.startswith(artifact_prefix + "-"):
                result.update(concepts)
    return result


def _dependency_coordinate(value: str) -> tuple[str, str] | None:
    parts = tuple(item.strip().casefold() for item in value.split(":") if item.strip())
    if len(parts) >= 4 and parts[0] == "dependency":
        parts = parts[2:]
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def _truthy(value: object) -> bool:
    return str(value).casefold() in {"1", "true", "yes", "generated", "test"}


def _entry_point_role(value: object) -> bool:
    return str(value).strip().casefold() in {
        "1", "true", "yes", "java-main", "application", "command", "entry-point",
    }


def is_structured_edge_evidence(value: object) -> bool:
    """Accept only established, source-free canonical evidence references."""

    text = unicodedata.normalize("NFKC", str(value).strip())
    return _is_structured_edge_evidence_text(text)


def _is_structured_edge_evidence_text(text: str) -> bool:
    if (
        not text
        or len(text) > 512
        or any(character.isspace() or ord(character) < 32 for character in text)
        or "://" in text
    ):
        return False
    if text in _FIXED_EDGE_EVIDENCE:
        return True
    if contains_absolute_path_text(text):
        return False
    if (
        _SYMBOL_EVIDENCE.fullmatch(text)
        or _WORKSPACE_DEPENDENCY_EVIDENCE.fullmatch(text)
        or _SEMANTIC_GRAPH_EVIDENCE.fullmatch(text)
        or _EVIDENCE_REFERENCE_ID.fullmatch(text)
    ):
        return True
    if text.startswith("declared_dependency.source:"):
        raw_path = text.removeprefix("declared_dependency.source:")
        path = PurePosixPath(raw_path)
        return bool(
            raw_path
            and "\\" not in raw_path
            and not path.is_absolute()
            and all(part not in {"", ".", ".."} for part in path.parts)
            and re.fullmatch(r"[A-Za-z0-9_.@%+~#=/,-]+", raw_path)
        )
    if text.startswith("declared_dependency:"):
        payload = text.removeprefix("declared_dependency:")
        return bool(
            _DEPENDENCY_EVIDENCE.fullmatch(text)
            and len(payload.split(":")) >= 4
            and ".." not in payload
        )
    scope, separator, reference = text.partition(":")
    return bool(
        separator
        and scope in _FRAMEWORK_SCOPES
        and reference
        and len(reference) <= 384
        and re.fullmatch(r"[A-Za-z0-9_.@%+~#=/,:()-]+", reference)
        and ".." not in reference
    )


def safe_edge_evidence_refs(values: Iterable[object]) -> tuple[str, ...]:
    """Project accepted evidence into fixed, traceable, non-reversible IDs."""

    accepted = set()
    for value in values:
        text = unicodedata.normalize("NFKC", str(value).strip())
        if _is_structured_edge_evidence_text(text):
            accepted.add(_edge_evidence_reference_id(text))
    return tuple(sorted(accepted))[:MAXIMUM_EDGE_EVIDENCE_REFS]


def _edge_evidence_reference_id(value: str) -> str:
    return "semantic_graph.edge_ref:" + hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def _package_name(subject: SubjectCandidate) -> str | None:
    if subject.kind is KnowledgeKind.PACKAGE:
        return subject.qualified_name
    qualified = subject.qualified_name.partition("#")[0]
    if subject.kind in {KnowledgeKind.TYPE, KnowledgeKind.METHOD, KnowledgeKind.FIELD} and "." in qualified:
        return qualified.rsplit(".", 1)[0]
    return None
