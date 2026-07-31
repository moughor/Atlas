# PR130 Release Notes

PR130 adds deterministic, evidence-backed design-pattern detection over the PR129
canonical `KnowledgeGraph`.

The normal Java pipeline can publish Strategy and Builder findings from resolved
inheritance, typed usage, and method-return evidence. Existing optional call-graph
evidence enables Factory, Adapter, Decorator, Command, and Template Method detection.
Observer, Composite, Chain of Responsibility, and State are explicitly
`insufficient` until reliable registration, collection, conditional-forwarding, and
transition producers exist.

Every finding contains canonical participating symbols, confidence score/tier,
traceable evidence IDs, explanation, limitations, scope, language, and detector
version. The common evidence index and confidence calculator are deterministic,
source-free, and independent of LLM reasoning.

PR130 preserves the existing canonical and specialized graphs. The Java architecture
artifact now survives analysis-result recovery and is reused during snapshot
publication. Existing APIs and snapshots remain backward compatible through additive
optional fields.

Repository-level `atlas ai explain` requests now consume a compact projection of
`semantic_context.design_patterns`. The projection exposes only the pattern name,
status, confidence, participant count, evidence count, and limitations. It excludes
participant identities, evidence details, and source code. Targeted symbol
explanations retain their existing detailed semantic-context path.
