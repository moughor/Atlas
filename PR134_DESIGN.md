# PR134 Design — Explain Anything

PR134 generalizes existing `ExplainEngine` for repository, project, package/module,
class/type, method, dependency, framework, build system/target, symbol, and graph
relationship explanations.

Resolution order is exact canonical ID, qualified name in scope, unique normalized
name, then ranked candidates requiring disambiguation. Language, kind, project, and
path constrain matches. “Build target” is used only for an actual task/target producer;
Maven/Gradle/npm detection remains “build system.”

Context priority is subject identity/coverage; direct evidence; containment and
repository context; filtered incoming/outgoing relations; relevant architecture,
pattern, reachability, risk, impact, and security results; then limitations/conflicts.
Expansion is cycle-safe, bounded, evidence-ranked, and reports omissions. Repository
questions prioritize PR133; narrow subjects prioritize direct facts.

Prompts require evidence citations, confidence wording, observation/interpretation
separation, and uncertainty. They contain no source. The response returns resolved
subject, context digest, citations, and truncation. Context selection is deterministic
even if provider prose is not.

Indexes reuse PR129 IDs; resolution is indexed and selection
`O(V_selected+E_selected)`. Existing default explanation stays compatible. Tests cover
every subject, duplicates/overloads, build targets, framework scope, edge explanation,
cycles, confidence, citations, source exclusion, truncation, old snapshots, JUnit,
and million-node lookup. Line-level source explanation and automatic changes are
deferred.
