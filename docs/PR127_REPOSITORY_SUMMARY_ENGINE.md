# PR127 — Repository Summary Engine

`RepositorySummaryService` produces a deterministic, source-free repository
model by composing Atlas components that already existed before PR127.

The model contains repository and project metadata, language distributions,
build systems, framework evidence, entry points, nested module ownership,
production/test/generated counts, and dependencies grouped by ecosystem.

Nested workspaces assign files to the most specific project so aggregate counts
do not double-count modules. Every collection is sorted before publication.
The resulting dictionary is available as
`semantic_context.repository_summary` in Atlas Semantic Snapshots, allowing AI
features to consume verified metadata without raw source files.

Framework results reuse Maven framework detection and normalized dependency
facts. PR127 does not introduce a competing framework scanner.
