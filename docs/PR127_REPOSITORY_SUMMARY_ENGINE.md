# PR127 — Repository Summary Engine

`RepositorySummaryService` produces a deterministic, source-free repository
model by composing Atlas components that already existed before PR127.

The model contains repository and project metadata, language distributions,
build systems, framework evidence, entry points, nested module ownership,
production/test/generated counts, and dependencies grouped by ecosystem.

The version 1 extensibility contract now includes explicit aliases without
removing or changing the original keys:

- `inventoried_file_count` and `inventoried_file_bytes` replace ambiguous
  presentation of `files` and `size`;
- `language_file_counts` identifies languages as recognized-extension file
  counts rather than semantic coverage;
- `classified_non_test_source_files`, `classified_test_source_files`, and
  `classified_generated_files` describe inventory classifications rather than
  compiler-proven production units;
- `total_declared_dependency_records` distinguishes parsed declaration records
  from resolved external packages.

Legacy keys and the version 1 marker remain serialized for existing API and
snapshot consumers. A new version was deliberately not declared because the
change is additive and Atlas has no separate repository-summary migration
boundary.

Nested workspaces assign files to the most specific project so aggregate counts
do not double-count modules. Every collection is sorted before publication.
The resulting dictionary is available as
`semantic_context.repository_summary` in Atlas Semantic Snapshots, allowing AI
features to consume verified metadata without raw source files.

Framework results reuse Maven framework detection and normalized dependency
facts. PR127 does not introduce a competing framework scanner.
