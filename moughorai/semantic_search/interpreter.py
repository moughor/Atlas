from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from moughorai.knowledge_graph import KnowledgeKind, KnowledgeRelation

from .models import QueryInterpretation, SearchIntent, SemanticSearchRequest


CONCEPT_REGISTRY_VERSION = 1
MAXIMUM_QUERY_TERMS = 64
_TOKEN = re.compile(r"[\w.+:#@/-]+", re.UNICODE)


@dataclass(frozen=True, order=True, slots=True)
class ConceptDefinition:
    name: str
    aliases: tuple[str, ...]
    evidence_rules: tuple[str, ...]


# Aliases interpret caller intent. They do not classify repository subjects;
# classification is performed only from the structured evidence rules in the index.
CONCEPT_REGISTRY = (
    ConceptDefinition("authentication", ("auth", "authentication", "login"),
                      ("exact security annotation", "compatible security dependency")),
    ConceptDefinition("authorization", ("authorization", "access control", "permission"),
                      ("exact authorization annotation", "compatible security finding")),
    ConceptDefinition("rest_endpoint", ("rest endpoint", "http endpoint", "endpoint", "rest api"),
                      ("exact HTTP endpoint annotation",)),
    ConceptDefinition("controller", ("controller", "controllers"),
                      ("exact controller annotation",)),
    ConceptDefinition("service", ("service", "services"),
                      ("exact service/component annotation",)),
    ConceptDefinition("repository", ("data repository", "data repositories", "data access"),
                      ("exact repository annotation", "dependency subject")),
    ConceptDefinition("sql", ("sql", "sql query", "database query"),
                      ("exact query annotation",)),
    ConceptDefinition("orm", ("orm", "object relational mapping", "hibernate"),
                      ("exact persistence annotation", "ORM dependency subject")),
    ConceptDefinition("scheduling", ("scheduled task", "scheduler", "scheduling", "scheduled"),
                      ("exact scheduling annotation",)),
    ConceptDefinition("caching", ("cache", "caching", "cached"),
                      ("exact cache annotation", "cache dependency subject")),
    ConceptDefinition("messaging", ("messaging", "message consumer", "message producer"),
                      ("exact messaging annotation", "messaging dependency subject")),
    ConceptDefinition("kafka", ("kafka", "kafka consumer", "kafka consumers", "kafka producer", "kafka producers"),
                      ("exact Kafka annotation", "Kafka dependency subject")),
    ConceptDefinition("event_listener", ("event listener", "event listeners"),
                      ("exact event-listener annotation",)),
    ConceptDefinition("transaction", ("transaction", "transactions", "transactional"),
                      ("exact transaction annotation",)),
    ConceptDefinition("dependency_injection", ("dependency injection", "injection", "di"),
                      ("exact injection/component annotation",)),
    ConceptDefinition("configuration", ("configuration", "config"),
                      ("exact configuration annotation",)),
    ConceptDefinition("logging", ("logging", "logger"),
                      ("logging dependency subject",)),
    ConceptDefinition("security", ("security", "security filter"),
                      ("exact security annotation", "security dependency subject")),
    ConceptDefinition("serialization", ("serialization", "json", "serializer"),
                      ("exact serialization annotation", "serialization dependency subject")),
    ConceptDefinition("background_job", ("background job", "job"),
                      ("exact scheduling or asynchronous annotation",)),
    ConceptDefinition("entry_point", ("entry point", "entry points", "main"),
                      ("explicit analyzer entry-point role",)),
    ConceptDefinition("framework_extension", ("framework extension", "framework extensions"),
                      ("compatible Service Loader reachability root",)),
    ConceptDefinition("testing", ("test", "tests", "testing"),
                      ("exact test annotation or structured test scope",)),
    ConceptDefinition("generated_code", ("generated code", "generated"),
                      ("structured generated-source classification",)),
    ConceptDefinition("dead_code", ("dead code", "dead", "unreachable", "unused"),
                      ("compatible PR131 finding",)),
    ConceptDefinition("design_pattern", ("design pattern", "pattern"),
                      ("compatible PR130 finding",)),
    ConceptDefinition("builder_pattern", ("builder pattern", "model builder", "builder"),
                      ("compatible PR130 Builder finding",)),
    ConceptDefinition("strategy_pattern", ("strategy pattern", "strategy"),
                      ("compatible PR130 Strategy finding",)),
    ConceptDefinition("risk_hotspot", ("high risk", "risk hotspot", "hotspot"),
                      ("compatible PR132 hotspot",)),
    ConceptDefinition("architecture", ("architecture", "architecture pattern"),
                      ("compatible PR128 architecture finding",)),
    ConceptDefinition("architecture_modular_monolith", ("modular monolith",),
                      ("compatible PR128 modular-monolith finding",)),
    ConceptDefinition("architecture_layered", ("layered architecture",),
                      ("compatible PR128 layered finding",)),
    ConceptDefinition("architecture_event_driven", ("event driven architecture",),
                      ("compatible PR128 event-driven finding",)),
    ConceptDefinition("architecture_plugin", ("plugin architecture",),
                      ("compatible PR128 plugin-architecture finding",)),
)


_KIND_ALIASES = {
    "workspace": KnowledgeKind.WORKSPACE,
    "workspaces": KnowledgeKind.WORKSPACE,
    "repository": KnowledgeKind.REPOSITORY,
    "repositories": KnowledgeKind.REPOSITORY,
    "project": KnowledgeKind.PROJECT,
    "projects": KnowledgeKind.PROJECT,
    "module": KnowledgeKind.MODULE,
    "modules": KnowledgeKind.MODULE,
    "package": KnowledgeKind.PACKAGE,
    "packages": KnowledgeKind.PACKAGE,
    "type": KnowledgeKind.TYPE,
    "types": KnowledgeKind.TYPE,
    "class": KnowledgeKind.TYPE,
    "classes": KnowledgeKind.TYPE,
    "method": KnowledgeKind.METHOD,
    "methods": KnowledgeKind.METHOD,
    "field": KnowledgeKind.FIELD,
    "fields": KnowledgeKind.FIELD,
    "dependency": KnowledgeKind.DEPENDENCY,
    "dependencies": KnowledgeKind.DEPENDENCY,
    "framework": KnowledgeKind.FRAMEWORK,
    "frameworks": KnowledgeKind.FRAMEWORK,
    "build system": KnowledgeKind.BUILD_SYSTEM,
    "build systems": KnowledgeKind.BUILD_SYSTEM,
}

_RELATIONS = (
    # Direction is the adjacency to inspect from the named target in order to
    # return the subjects described by the query.
    ("depends on", KnowledgeRelation.DEPENDS_ON, "incoming"),
    ("implements", KnowledgeRelation.INHERITS, "incoming"),
    ("extends", KnowledgeRelation.INHERITS, "incoming"),
    ("inherits", KnowledgeRelation.INHERITS, "incoming"),
    ("calls", KnowledgeRelation.CALLS, "incoming"),
    ("called by", KnowledgeRelation.CALLS, "outgoing"),
    ("imports", KnowledgeRelation.IMPORTS, "incoming"),
    ("overrides", KnowledgeRelation.OVERRIDES, "incoming"),
    ("owned by", KnowledgeRelation.OWNS, "outgoing"),
)

_SCOPES = re.compile(r"\s+in\s+(project|module|package)\s+(.+?)\s*$")
_USING = re.compile(r"\s+using\s+(.+?)\s*$")


def normalize_query(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def query_terms(value: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _TOKEN.finditer(value))[:MAXIMUM_QUERY_TERMS]


def concept_aliases() -> dict[str, str]:
    return {
        normalize_query(alias): definition.name
        for definition in CONCEPT_REGISTRY
        for alias in definition.aliases
    }


def interpret_query(request: SemanticSearchRequest) -> QueryInterpretation:
    normalized = normalize_query(request.text)
    # Grammar punctuation is normalized separately so canonical IDs, dependency
    # coordinates, and names retain their exact spelling for PR134 resolution.
    working = re.sub(r"[?!,;]+", " ", normalized)
    working = " ".join(working.split())
    if not query_terms(working):
        raise ValueError("semantic search query contains no searchable identifier or terms")
    phrase_working = " ".join(working.replace("-", " ").split())
    structured_identity = (
        (":" in normalized or "#" in normalized)
        and " " not in normalized
    )
    filters: dict[str, str] = {}
    subject_terms: tuple[str, ...] = ()
    relation = request.relation
    ambiguous_relation = False

    scope_match = _SCOPES.search(working)
    if scope_match:
        scope_kind, scope_value = scope_match.groups()
        filters[scope_kind] = scope_value.strip()
        working = working[:scope_match.start()].strip()
        phrase_working = " ".join(working.replace("-", " ").split())
    using_match = _USING.search(working)
    if using_match:
        filters["using"] = using_match.group(1).strip()
        working = working[:using_match.start()].strip()
        phrase_working = " ".join(working.replace("-", " ").split())
        if not working:
            raise ValueError("semantic search 'using' requires a subject kind or concept")

    if phrase_working.startswith("used by "):
        ambiguous_relation = relation is None
        if ambiguous_relation:
            filters["relation_ambiguous"] = "true"
        else:
            filters["direction"] = "outgoing"
            filters["relation_phrase"] = "used by"
        subject_terms = (working[len("used by "):].strip(),)
        working = "used by"
        phrase_working = working

    for phrase, candidate_relation, direction in _RELATIONS:
        prefix = f"{phrase} "
        if phrase_working.startswith(prefix):
            if relation is not None and relation is not candidate_relation:
                raise ValueError("conflicting semantic search relation constraints")
            relation = candidate_relation
            filters["direction"] = direction
            filters["relation_phrase"] = phrase
            subject_terms = (working[len(prefix):].strip(),)
            working = phrase
            phrase_working = phrase
            break

    aliases = concept_aliases()
    concepts: set[str] = set()
    if not structured_identity:
        for alias, concept in sorted(aliases.items(), key=lambda item: (-len(item[0]), item[0])):
            if phrase_working == alias or f" {alias} " in f" {phrase_working} ":
                concepts.add(concept)

    exact_concept_alias = phrase_working in aliases
    kind_matches = tuple(
        (alias, kind)
        for alias, kind in sorted(_KIND_ALIASES.items(), key=lambda item: (-len(item[0]), item[0]))
        if not structured_identity and not exact_concept_alias and (
            phrase_working == alias
            or phrase_working.startswith(f"{alias} ")
            or phrase_working.endswith(f" {alias}")
        )
    )
    parsed_kinds = {kind for _, kind in kind_matches}
    if parsed_kinds and request.kinds and parsed_kinds.isdisjoint(request.kinds):
        raise ValueError("conflicting semantic search kind constraints")
    effective_kinds = parsed_kinds or set(request.kinds)
    if effective_kinds:
        filters["kinds"] = ",".join(sorted(item.value for item in effective_kinds))
    if parsed_kinds and not concepts and relation is None:
        alias = kind_matches[0][0]
        residual_source = working
        if residual_source == alias:
            residual = ""
        elif residual_source.startswith(f"{alias} "):
            residual = residual_source[len(alias):].strip()
        else:
            residual = residual_source[:-len(alias)].strip()
        if residual:
            subject_terms = (residual,)
    for name in ("project", "module", "package", "language"):
        value = getattr(request, name)
        if value is not None:
            if name in filters and normalize_query(filters[name]) != normalize_query(value):
                raise ValueError(
                    f"conflicting semantic search {name} constraints"
                )
            filters[name] = value

    intents: set[SearchIntent] = set()
    if relation is not None:
        intents.add(SearchIntent.RELATIONAL)
    if ambiguous_relation:
        intents.add(SearchIntent.RELATIONAL)
    if concepts:
        intents.add(SearchIntent.CONCEPT)
    if parsed_kinds:
        intents.add(SearchIntent.SUBJECT_KIND)
    if filters and (concepts or relation is not None or parsed_kinds):
        intents.add(SearchIntent.COMPOUND)
    ambiguous = ambiguous_relation or " or " in f" {phrase_working} "
    alternatives = (
        (
            "calls (outgoing)",
            "composition (outgoing)",
            "depends_on (outgoing)",
            "imports (outgoing)",
        )
        if ambiguous_relation
        else tuple(part.strip() for part in phrase_working.split(" or ") if part.strip())
        if ambiguous else ()
    )
    if not intents:
        if structured_identity or len(query_terms(normalized)) == 1:
            intents.add(SearchIntent.EXACT_IDENTITY)
        else:
            intents.add(SearchIntent.UNKNOWN)
    if ambiguous:
        intents.add(SearchIntent.AMBIGUOUS)

    recognized = set()
    for alias in aliases:
        recognized.update(query_terms(alias))
    recognized.update(word for phrase in _KIND_ALIASES for word in query_terms(phrase))
    recognized.update(word for phrase, _, _ in _RELATIONS for word in query_terms(phrase))
    recognized.update(("used", "by"))
    recognized.add("or")
    unsupported = ()
    if SearchIntent.EXACT_IDENTITY not in intents:
        subject_tokens = {
            token
            for value in subject_terms
            for candidate in (value, value.replace("-", " "))
            for token in query_terms(candidate)
        }
        unsupported = tuple(sorted(
            set(query_terms(phrase_working)) - recognized - subject_tokens
        ))
    if len(tuple(_TOKEN.finditer(normalized))) > MAXIMUM_QUERY_TERMS:
        unsupported = tuple(sorted({
            *unsupported,
            "additional query terms omitted by the 64-term bound",
        }))

    return QueryInterpretation(
        request.text,
        normalized,
        query_terms(normalized),
        tuple(intents),
        tuple(concepts),
        subject_terms,
        relation,
        tuple(filters.items()),
        alternatives,
        unsupported,
        ambiguous,
    )
