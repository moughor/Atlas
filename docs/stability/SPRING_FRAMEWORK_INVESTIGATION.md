# Spring Framework Gradle Discovery Investigation

## Scope and provenance

This M1 hardening investigation fixes a generic Gradle workspace-discovery defect.
It does not add roadmap functionality or repository-specific behavior.

- Repository: `https://github.com/spring-projects/spring-framework.git`
- Pinned Spring commit: `eceebb3077dda9e1b19d73c0398ef022cd91f99c`
- Atlas starting commit: `fee13975bdbc80677b4e171eb51388c421d9c787`
- Atlas tag at start: `atlas-m1-stable`

The full Spring clone was verified at the official origin and pinned commit. Its
tracked worktree was clean before analysis; only Atlas-generated `.atlas` output was
created during validation. Atlas `HEAD` and `origin/main` matched and its worktree
was clean before implementation.

## Initial result and traceback

The original production command discovered only three projects:

```text
buildSrc: succeeded
framework-docs: succeeded
spring-framework: failed
projects: 3
succeeded: no
```

The root failed after approximately 49.7 seconds. A narrow direct diagnostic exposed
the exception hidden behind the workspace boundary:

```text
DuplicateTypeError: Duplicate Java type
'org.springframework.beans.factory.xml.ConstructorDependenciesBean'
in project 'spring-framework':
spring-beans/src/test/java/org/springframework/beans/factory/xml/
  ConstructorDependenciesBean.java
spring-context/src/test/java/org/springframework/beans/factory/xml/
  XmlBeanFactoryTestTypes.java
```

At the starting commit, the call path was
`moughorai/ai_context/analyzer_registry.py:116` →
`moughorai/ai_context/analyzer_registry.py:219` →
`moughorai/java_symbols/builder.py:44` →
`moughorai/java_symbols/index.py:41`. Duplicate detection was correct: the files
belong to different Gradle projects and had been merged only because those projects
were not discovered.

`atlas analyze` returned process exit code `0` while reporting `succeeded: no`. This
is established CLI behavior: benchmark acceptance reads the structured project
results rather than treating the process code as a quality gate.

## Actual Gradle model

The root `settings.gradle` contains 27 direct, literal Groovy command declarations:

```groovy
include "spring-aop"
// ... 25 additional literal children ...
include "integration-tests"
```

It also declares `rootProject.name = "spring"` and maps each child build filename to
`${project.name}.gradle`. Every declared child directory and mapped build script
exists. There are no `includeBuild`, `projectDir`, conditional, multiline, nested,
or dynamically generated project declarations in this pinned settings file. The
external `io.spring.develocity.conventions` settings plugin is not executed or
evaluated, so its runtime behavior is outside the statically proven model.

The statically proven checked-in model is:

- one main root;
- 27 declared main-build children;
- one automatic `buildSrc` auxiliary build;
- 29 Atlas projects under the existing inventory convention.

`framework-docs` is one of the 27 children. The generic scanner happened to find it
through `package.json`; it is not an independent documentation build.

## Defect classification

The settings file was detected and read, but `_gradle_projects()` accepted only the
parenthesized `include(...)` form. The 27 command-form declarations matched nothing.
The generic marker scan then found only the root, `buildSrc`, and `framework-docs`.
The remaining module trees were assigned to the root, producing the cross-module
duplicate. This is category B/L: a settings parser syntax gap with a downstream
ownership failure. Root analysis failure did not suppress child publication because
discovery had already completed.

The previous regression fixture used Kotlin-style `include("module")`, so it did not
cover Groovy command syntax.

## Generic fix

Workspace discovery now uses a bounded, linear, comment-aware static parser. It:

- accepts top-level `include("a", ":nested:b")`, including multiline argument lists
  and the existing intermediate projects implied by nested Gradle paths;
- accepts same-line Groovy `include "a", ":nested:b"`;
- accepts only complete single- or double-quoted literal argument lists;
- masks comments without joining tokens and rejects declarations nested in braces,
  parentheses, brackets, slashy strings, or unsupported control flow;
- rejects interpolation, variables, executable suffixes, path traversal, empty
  segments, slashes, escapes, and targets resolving outside the workspace;
- deduplicates by resolved physical path and preserves deterministic ordering;
- merges source-free settings membership evidence into an already discovered
  project rather than duplicating it;
- never scans arbitrary directories or treats every `*.gradle` file as a project.

The evidence records only the settings filename and normalized logical Gradle path.
Repository summary and Explain may therefore report Gradle membership without
claiming dependency coverage from a custom child script.

No Spring project name, path, or conditional exists in production code. The root
continues to use the checkout basename for compatibility; `rootProject.name` is not
used to change Atlas project identity.

## Java source-root follow-up

After discovery was corrected, 28 projects succeeded and `spring-core` exposed a
separate input-model defect:

```text
DuplicateTypeError: Duplicate Java type
'org.springframework.core.task.VirtualThreadDelegate'
in project 'spring-core':
spring-core/src/main/java/org/springframework/core/task/VirtualThreadDelegate.java
spring-core/src/main/java21/org/springframework/core/task/VirtualThreadDelegate.java
```

Spring's multi-release JAR intentionally compiles the second path as a Java 21
source-set alternative. Atlas now compares eligible Gradle paths and omits a
version-specific file only when its exact baseline path is also present. It emits a
source-free warning that source-set variant semantics are not modeled. Additive
version-specific files and custom `testFixtures`, JMH, integration-test, Android, or
other source roots retain their previous analysis behavior.

This does not weaken the invariant that duplicate types within one analyzed source
scope are errors.

## Validation

Two consecutive complete `--force --no-recover` runs against the pinned checkout
and final reviewed code succeeded:

| Result | Run 1 | Run 2 |
| --- | ---: | ---: |
| Projects | 29 | 29 |
| Succeeded | 29 | 29 |
| Failed | 0 | 0 |
| Internal exceptions | 0 | 0 |
| Elapsed | 74.112 s | 74.145 s |
| Snapshot size | 122,418,970 bytes | 122,418,970 bytes |

Deterministic gates matched across runs:

| Gate | SHA-256 |
| --- | --- |
| Workspace project order | `4586f23aa5d62a65187adc9202a065d332475fa957f38abf67b04d79145658c4` |
| Workspace payload | `db12f6a8f94a94fc9a9f5f381a7891cbaf512896028ac9f4d4dff8077d8d913a` |
| Module hierarchy | `4283c15ce65da84bbec761de286d53a69256042e3b7fe2da1f44ebe8a36573d6` |
| Dependency projection (21 records) | `fe1d09bd02537cf39a2f8b1d0b1e50766fa068bd3b0db4871521adf68fa5d07b` |
| Semantic payload | `d576f114185c20b90a2fb511ad257a88dbe3fa19c38588942bfd359d4a3261e3` |
| Repository report | `f998ad4d2707275d8591ad213d4656eb4b2b52fefa792dd279187d5c3c5e2ddd` |
| Default explanation | `1c137acccdb5ebe1b6050173b847a548d45541f07bb369ddb6a058439cffa616` |

Raw ASS hashes and snapshot IDs differed because run-specific history metadata is
part of ASS identity. The semantic payload, report, explanation, workspace,
hierarchy, dependency projection, size, project set, and order were identical.

Five repeated discovery-only measurements returned 29 projects and the same
workspace serialization hash
`672c5b85e38275d568b100ffc56bb209d86a36c2263e87694f79fefbe4c497eb`
each time. They ranged from 96.659 to 101.354 ms with a 97.941 ms median. The
settings parser adds no recursive traversal; it resolves and checks only literal
declared paths.

The final snapshot records 88,058 canonical graph nodes and 96,615 edges. Repository
summary reports Gradle in all 29 projects and npm in `framework-docs`. The default
explanation is 10,777 characters, deterministic and source-free, reports the
29-project repository, does not expose the checkout root, does not confuse Spring
Framework with Spring Boot, and does not introduce React or other unsupported
framework claims. Structured Explain output was byte-identical across two reads of
the same snapshot (27,159 characters; SHA-256
`817ca58bbb9700e1e5d54e92a933a375201fe71c9a0c222cf4d59a8b5549a399`).
Snapshot lineage fields intentionally change between analyses.

The final context contains 1,877 explicit per-file Java parse diagnostics and one
`ATLAS-JAVA-SOURCE-VARIANT` warning covering two shadowed version-specific files.
These are isolated input diagnostics, not internal workspace exceptions; all 29
projects completed. The parser limitations predate this discovery fix and are not
suppressed by it.

Focused regression validation used the active Atlas interpreter:

```powershell
python -m pytest -q -p no:cacheprovider `
  --basetemp=.pytest-tmp-gradle-final-targeted4 `
  tests/test_gradle_workspace_discovery.py `
  tests/test_pr67_workspace_model.py `
  tests/test_pr123_project_scoped_java_identity.py `
  tests/test_pr124_analyzer_registry.py `
  tests/test_pr127_repository_summary.py `
  tests/test_ai_explain_accuracy.py `
  tests/test_project_detector.py `
  tests/test_project_inventory_classifier.py `
  tests/test_pr126_dependency_intelligence.py `
  tests/test_pr19_workspace_scanner.py `
  tests/test_pr111_semantic_snapshot.py `
  tests/test_ai_context_pipeline_integration.py `
  tests/test_pr129_knowledge_graph.py
```

Result: `194 passed in 2.91s`.

`python -m compileall -q moughorai` completed successfully. `git diff --check`
reported no whitespace errors; its only output was the repository's existing
Windows LF-to-CRLF conversion warning. The complete validation command was:

```powershell
python -m pytest -q -rs -p no:cacheprovider `
  --basetemp=.pytest-tmp-gradle-full
```

Result: `3748 passed, 1 skipped in 22.31s`, with no test warnings. The exact skip
was `tests/test_production_review_remediations.py:107: file symlinks are unavailable
on this platform`.

The Apache Maven checkout was first analyzed again in 24.152 seconds: 92 projects,
92 successes, and no failures. After the implementation commit, the canonical
three-run capture was baseline-eligible with durations of 24,460, 23,514, and 23,518
ms. Every artifact field is byte-for-byte identical to the accepted M1.1 golden,
including raw ASS identity, semantic and portable payloads, reports, explanation,
risk, graph, workspace/analysis order, and deterministic-order hashes.

The accepted Quarkus snapshot was then replayed canonically three times in 99,622,
120,991, and 133,422 ms. The replay is baseline-eligible, reports 1,442 successes and
zero failures, and links to accepted fresh-manifest SHA-256
`a57b592a14c746d1f35aea5c032d3764febbf0b404bc6d52b07bc7045f6f351a`.
All ten replay artifact gates match the accepted M1.1 source exactly.
As designed, replay omits fresh analysis-order/report fields and hashes an explicit
analysis-order-unavailable state. No accepted golden was changed.

## Limitations and baseline status

- Literal collection loops, variables, interpolation, conditions, slashy strings,
  dual settings files, `projectDir`, `includeBuild`, nested settings evaluation, the
  external settings plugin, and executable Gradle logic are not evaluated.
- The `${project.name}.gradle` mapping is not interpreted. Dependency intelligence
  therefore covers default root/buildSrc descriptors but does not claim complete
  child-script dependency coverage.
- Gradle logical hierarchy is represented by the existing filesystem hierarchy;
  composite-build semantics are not modeled.
- Version-specific source sets are not modeled as distinct semantic variants. Only
  an alternative with an exact eligible baseline counterpart is omitted and warned;
  additive versioned, `testFixtures`, JMH, and other custom-root files remain
  analyzed in one unversioned semantic scope. Atlas neither proves that Gradle
  compiles them nor qualifies symbols by Java/source-set variant. Inventory totals
  still measure files rather than semantic variant coverage.
- Ambiguous physical aliases or flattened Atlas project-name collisions fail closed:
  the affected declared branch is not published. Unsupported or ambiguous settings
  syntax currently degrades to partial discovery without a workspace-level
  diagnostic.
- Portable snapshot projection currently rejects one valid Java signature containing
  a backslash as if it were a machine path (canonical graph node 59,169). The safety
  gate was not bypassed.

Spring is therefore a successful pinned diagnostic benchmark, not a promoted
canonical golden. The existing Maven and Quarkus goldens remain authoritative and
are not modified by this investigation.

## Maintainer decision

| Area | Decision | Rationale |
| --- | --- | --- |
| Gradle parser | Keep | Linear, literal-only parsing resolves the proven syntax gap without executing Gradle. |
| Project mapping | Keep | Resolved-path merge preserves existing project identity and prevents duplicate inventories. |
| Root failure fix | Keep | Correct ownership removes the false cross-module duplicate without weakening validation. |
| Java variants | Keep | Exact-path overlay comparison avoids the proven duplicate while preserving additive and loose-project scans. |
| Tests | Keep | Small fixtures cover command syntax, safety, ownership, summary evidence, and source variants. |
| Documentation | Keep | Records exact evidence and unsupported semantics without changing the roadmap. |
| Spring golden | Defer | The portable-path safety gate must pass before promotion. |

No Gradle execution, persistent cache, parallelism, broad exception suppression,
temporary traceback output, or repository-specific fallback was added.
