# PR67 — Workspace & Project Model

PR67 introduces a deterministic multi-project workspace layer for Atlas.

## Capabilities

- Load `atlas.yaml` or `atlas.yml` workspace manifests.
- Define named projects, paths, dependencies, include/exclude globs, and string-normalized options.
- Discover projects from standard ecosystem markers when no manifest exists.
- Validate duplicate names, path traversal, missing dependencies, and dependency cycles.
- Produce deterministic dependency and analysis orderings.
- Compute content fingerprints and identify changed projects.
- Expand changes to transitively impacted downstream projects.
- Serialize workspace state deterministically for API, CLI, and LSP consumers.

## Example

```yaml
projects:
  - name: core
    path: packages/core
    include: ["**/*.py"]
  - name: api
    path: services/api
    dependencies: [core]
    exclude: ["build/**/*"]
options:
  profile: strict
```

```python
from moughorai.workspace import WorkspaceService

service = WorkspaceService(".")
plan = service.analysis_order(("api",))
```

The plan includes all required dependencies in stable topological order.

## Maven reactor discovery

When no `atlas.yaml` is present, Atlas follows explicit Maven `<modules>`
declarations recursively, including modules below the generic directory-scan depth.
Only declared modules whose POM remains inside the workspace are added. Each reactor
module receives its own project identity, and ancestor projects exclude files owned
by their discovered descendants.

This keeps independent Maven artifacts separate without treating arbitrary POMs in
test resources as workspace projects. Invalid or undeclared fixture trees remain
outside reactor discovery.
