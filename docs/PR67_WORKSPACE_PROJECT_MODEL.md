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

## Gradle settings discovery

Automatic discovery statically recognizes top-level literal Gradle declarations in
both parenthesized and Groovy command form, including multiple literal arguments and
colon-separated nested project paths:

```groovy
include(":core", ":services:api")
include "framework-docs"
```

Atlas does not execute settings scripts. For ordinary `include` discovery, variables,
interpolation, conditionals, collections, loops, `projectDir` remapping, `includeBuild`,
and nested settings evaluation remain unsupported. A declared directory must exist,
resolve inside the workspace, and use a conservative project-path grammar. Settings
evidence is merged with a project already found through another marker instead of
creating a duplicate. Ancestor file ownership is then pruned exactly as for Maven
reactor modules. Colon-separated paths also create each existing intermediate Gradle
project, matching Gradle's project hierarchy semantics.

### Statically verified recursive Groovy helpers

Atlas additionally recognizes one narrowly constrained Groovy helper pattern used by
large settings files to declare projects recursively. This is structural recognition,
not Gradle evaluation. A helper is accepted only when its complete body proves all of
the following behavior:

- a `void` method takes exactly a `String` logical-path parameter and a `File`
  directory parameter;
- non-directories return immediately;
- optional directory-name exclusions compare the directory name with string literals
  and return immediately;
- a missing literal `build.gradle` returns immediately, so every traversed hierarchy
  level is explicitly build-gated;
- a present literal `settings.gradle` returns immediately, establishing a nested-build
  boundary;
- an existing `findProject(directory)` result returns immediately;
- the logical project name is exactly `"${path}:${dir.name}"`;
- optional project exclusions use literal `projectName.equals(":path")` guards that
  return immediately;
- the helper includes exactly that computed project name;
- an optional directory mapping is limited to the proven
  `path.isEmpty() || path.startsWith(":literal")` form and assigns the current
  directory to the computed project;
- the only traversal is a deterministic recursive call over `directory.listFiles()`,
  passing the computed project name and each child; and
- no additional statement or altered recursion is present.

Invocation evidence must also be unconditional and literal at settings top level:

```groovy
scanProjects('', new File(rootProject.projectDir, 'modules'))
scanProjects('test', new File(rootProject.projectDir, 'test/external-modules'))
```

Prefixes and roots cannot use variables, interpolation, absolute paths, `..`, or other
dynamic expressions. Before each accepted invocation, Atlas accounts for earlier
literal `include` declarations in statement order. It rejects recursive proof when an
earlier top-level statement contains an unparsed or dynamic `include`, `includeFlat`,
or an external `projectDir`/`setProjectDir` mutation, because `findProject` semantics
would no longer be statically known. A later unsupported declaration does not
retroactively invalidate an already proven invocation.

Traversal is iterative and deterministic. It is bounded to the literal invocation
roots and to uninterrupted `build.gradle`-gated directory chains; it does not use an
unbounded workspace scan. Children are ordered deterministically, resolved paths must
remain inside the workspace, symlink directories are never followed, repeated physical
paths are visited once, literal exclusions are honored, and nested settings stop the
branch. Logical paths must round-trip to the exact traversed path segments.

Recursive membership uses the same resolved-path alias, flattened-name collision, and
descendant ownership rules as literal settings membership. Evidence remains
source-free and deterministic, for example:

```text
settings.gradle#recursive(scanProjects,:modules:core)
```

Recursive helper recognition is limited to this proven Groovy shape in
`settings.gradle`. Kotlin settings helpers (`settings.gradle.kts`), general Gradle
evaluation, arbitrary closures or loops, `includeBuild`, custom build-file names, and
arbitrary searches for `build.gradle` files are explicitly unsupported. Unsupported or
ambiguous semantics fail closed and fall back to the existing bounded marker discovery.

Resolved-path aliases and flattened project names must be unambiguous. If two Gradle
paths resolve to the same physical branch, or two physical paths would receive the
same established Atlas name, Atlas omits the affected declared branch and its
descendants rather than publishing an unstable identity.

Gradle membership proves the build system but does not prove the name or dependency
contents of a custom child build file. Atlas does not classify arbitrary `*.gradle`
scripts as project descriptors. If both settings filenames exist, Atlas treats their
authority as ambiguous and does not combine their declarations.
