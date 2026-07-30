# PR129 Canonical Relation Evidence

No relation is published from names alone. An edge is emitted only when both
endpoints resolve to canonical symbol or project nodes.

| Relation | Production evidence | Mapping | Languages | Limitations | Status |
|---|---|---|---|---|---|
| `imports` | `GlobalSymbol.metadata.imports` from language frontends | importing module/package to unique internal target | Python, TypeScript | external and ambiguous targets omitted; Java frontend does not persist import metadata | populated |
| `inheritance` | resolved `JavaArchitectureGraph` extends/implements; Python class `bases` metadata | child type to resolved internal base/interface | Java, Python | external or ambiguous bases omitted | populated |
| `overrides` | Java method `@Override`, resolved ancestor, exact name and parameter signature | child method to matching internal ancestor method | Java | unannotated, external, generic-erasure, and ambiguous cases omitted | populated conservatively |
| `dependencies` | `Workspace.Project.dependencies`, PR126 declared dependencies, PR127 framework evidence | project/workspace to project/dependency/framework | all workspace languages | declared dependencies are not resolved package graphs | populated |
| `ownership` | workspace/project/module structure, `project_id`, and `owner_id` | container to child; member to owner uses `member_of` | all | no inferred ownership | populated |
| `composition` | typed fields exist in `JavaArchitectureGraph` | no canonical mapping | none | a field reference does not prove lifecycle composition | supported, not populated |
| `calls` | `CallGraph` and cross-language call graph exist outside the normal analyzer pipeline | no canonical mapping | none | normal frontend supplies no normalized resolved call sites | supported, not populated |

Concrete build tasks/targets also remain unpopulated. PR129 publishes detected
tools as `build_system`; `build_target` stays in the enum for compatibility and
future task-level evidence.

Every populated edge includes evidence naming the producer and structured fact,
for example `global_symbol.metadata:inherits:demo.Base` or
`workspace.projects:api:dependencies:core`.
