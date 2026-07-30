# PR127 Existing-Capability Assessment

## Already present

Atlas already provides project scanning, file classification, inventory
statistics, technology detection, Maven framework evidence, Maven module
graphs, workspace discovery, project-scoped file matching, and normalized
dependency declarations.

## Reused

PR127 composes `ProjectClassifier`, `ProjectStatisticsCollector`,
`ProjectTechnologyDetector`, `MavenFrameworkService`, `WorkspaceService`,
`project_files`, and `DependencyIntelligenceService`.

## Missing before PR127

There was no immutable repository-level summary joining projects, languages,
build systems, frameworks, entry points, module hierarchy, source roles,
generated sources, and dependency totals.

## Extension

`RepositorySummaryService` adds that composition layer and publishes its
source-free model in semantic snapshots. Existing inventory and framework APIs
remain unchanged.

## Regression risks and controls

- Nested projects could be counted twice; the summary assigns files to the
  most specific project.
- Filesystem order could affect output; every aggregate is explicitly sorted.
- Inaccessible or malformed metadata could abort analysis; safe reads and
  existing non-executing parsers isolate failures.
- Snapshot consumers could receive raw source; the model contains paths,
  counts, names, and evidence only.
