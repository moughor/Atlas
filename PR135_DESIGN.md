# PR135 Design — Semantic Search

PR135 evolves `SemanticSearchService`, `GlobalSymbolDatabase`, and PR129 indexes,
preserving existing query/hit APIs. It adds deterministic intents: symbol/member,
repository/project/module, dependency/dependent, architecture/pattern,
relationship, security/risk/dead-code, and hybrid.

Pipeline: normalize query; extract exact IDs/names/kinds/scopes/relations; retrieve
lexical candidates; apply structured filters; perform bounded relation-specific graph
expansion; join PR130–PR134 metadata; rank and deduplicate by canonical ID. An LLM may
suggest an intent only as an untrusted hint. Ambiguity remains explicit.

Default ranking is exact identity `0.35`, lexical `0.25`, intent fit `0.15`, graph
proximity `0.15`, evidence quality `0.10`, renormalized for available signals.
Confidence is separate. Ties sort by kind, qualified name, then ID. Generated/test
scope is labeled. Missing edges are never inferred.

Versioned incremental indexes cover tokens, names, kinds, scopes, and relation
endpoints. Complexity is `O(tokens + candidates log k + bounded_edges)` with stable
caps and truncation metadata. Tests cover every intent/mode, ambiguity, overloads,
cross-project dependencies, ranking, false positives, missing relations,
incrementality, compatibility, source exclusion, JUnit, and 100k/1M-node latency.
Embeddings, external vector stores, learned ranking, and federated repositories are
deferred.
