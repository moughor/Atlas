# Performance Measurement Platform and Phase Matrix

M2 reports only observations provided by the current runtime and executed Atlas
path. An absent producer is unavailable, never zero.

## Platform counters

| Counter | Windows | Linux | Other platforms |
| --- | --- | --- | --- |
| Wall time | `time.perf_counter_ns()` | Same | Same where Python provides it |
| Process CPU | `time.process_time_ns()` | Same | Same where Python provides it |
| Thread CPU | `time.thread_time_ns()` when present | Same | `unsupported/runtime-unsupported` when absent |
| RSS | `WorkingSetSize` | Resident pages from `/proc/self/statm` | `unsupported/platform-unsupported` |
| Working set | `WorkingSetSize` | Explicit alias of Linux RSS | `unsupported/platform-unsupported` |
| Commit | `PrivateUsage` | Unsupported; virtual size is not substituted | `unsupported/platform-unsupported` |
| Python allocated/peak | Opt-in `tracemalloc` boundary sample | Same | Same where `tracemalloc` is active |
| OS process I/O | Not measured | Not measured | Not measured |

Failed or malformed provider observations are `unavailable/provider-unavailable`.
Absolute memory counters require non-negative integer bytes. RSS and allocation
values are boundary samples, not operating-system lifetime peaks. Process utilization
is process CPU divided by wall time, is not CPU-count normalized, and may exceed 100%.

## Normal phase coverage

| Phase | `atlas analyze --profile` producer | Availability condition |
| --- | --- | --- |
| `workspace.discovery` | `WorkspaceService` | Workspace construction starts. |
| `project.ownership` | Discovery and dependency graph | Workspace discovery succeeds. |
| `project.analysis` | Workspace executor | A project is analyzed rather than reused, blocked, or cancelled. |
| `repository.inventory` | Repository Summary | Successful workspace analysis reaches context publication. |
| `filesystem.traversal` | Discovery and project file selection | An instrumented traversal executes. |
| `path.normalization` | Discovery and project file selection | An instrumented normalization executes. |
| `build.parsing` | Workspace discovery | A workspace/build descriptor path executes. |
| `language.java.parsing` | Analyzer registry | A project has selected Java inputs. |
| `language.kotlin.parsing` | Reserved stable phase | Unavailable until an authoritative Kotlin producer executes. |
| `language.python.parsing` | Analyzer registry | A project has selected Python inputs. |
| `symbol.extraction` | Language analyzers and semantic collector | Symbol-producing analysis executes. |
| `dependency.intelligence` | Existing dependency service | A project analyzer inspects manifests. |
| `knowledge_graph.build` | Context builder/collector | Successful semantic context construction. |
| `architecture.analysis` | Existing Java/repository architecture services | Corresponding context analysis executes. |
| `reachability.analysis` | Existing reachability service | Successful workspace context collection. |
| `risk.analysis` | Existing risk service | Successful workspace context collection. |
| `repository.summary` | Existing summary service | Successful workspace context collection. |
| `repository.report` | Existing report service | Successful workspace context collection. |
| `explain.projection` | Explain engine | `atlas ai explain --profile`, not normal analysis. |
| `semantic_search.index` | PR135 snapshot index builder | `atlas search --profile` constructs an in-memory index. |
| `semantic_search.interpret` | PR135 query interpreter | An opt-in measured search executes. |
| `semantic_search.retrieve` | PR135 candidate retrieval | An opt-in measured search executes. |
| `semantic_search.score` | PR135 deterministic ranker | Retrieved candidates are scored. |
| `semantic_search.sort` | PR135 deterministic ranker | Scored candidates are ordered and bounded. |
| `semantic_search.evidence` | PR135 evidence projection | Search hits are enriched from structured evidence. |
| `semantic_search.render` | PR135 CLI | `atlas search --profile` renders human or JSON output. |
| `impact_prediction.resolver_index` | PR134 resolver through PR136 | The canonical snapshot graph and resolver indexes are restored once per service. |
| `impact_prediction.index` | PR136 snapshot-backed service | A compatible canonical graph is indexed for relation capability counts. |
| `impact_prediction.query` | PR136 snapshot-backed service | One complete warm impact request is measured as an inclusive boundary. |
| `impact_prediction.resolve` | PR134 resolver through PR136 | An opt-in impact request resolves its canonical subject. |
| `impact_prediction.neighbors` | PR136 bounded adjacency | A traversed subject evaluates a bounded canonical incoming-edge prefix. |
| `impact_prediction.traverse` | PR136 traversal | An impact request performs bounded, cycle-safe propagation. |
| `impact_prediction.cycle_check` | PR136 traversal | Traversal records deterministic cycle observations. |
| `impact_prediction.direct` | PR136 finding planner | Evidence-backed findings and owning-scope aggregation are planned. |
| `impact_prediction.sort` | PR136 deterministic selector | Bounded top-k impact classifications are selected with canonical tie-breaking. |
| `impact_prediction.score` | PR136 deterministic ranker | Retained impact findings are scored. |
| `impact_prediction.evidence` | PR136 evidence projection | Accepted graph and compatible analyzer evidence is projected. |
| `impact_prediction.serialize` | PR136 response model | Canonical response JSON size is measured. |
| `impact_prediction.render` | PR136 CLI | `atlas impact --profile` renders human or JSON output. |
| `semantic_snapshot.build` | ASS store | Successful analysis proceeds to snapshot capture. |
| `serialization` | State and ASS stores | A measured serialization/load boundary executes. |
| `persistence` | State and ASS stores | A measured durable read/write boundary executes. |
| `recovery` | Existing recovery manager | Recovery is enabled and its load/save path executes. |
| `publication` | History and ASS stores | The corresponding durable publication executes. |

TypeScript currently uses the source-free extension phase
`language.typescript.parsing`; other registered languages use
`language.other.parsing`. PR130 design-pattern analysis uses
`design_patterns.analysis`. These operational extensions do not change the stable
semantic snapshot schema.

PR135 measurements are request-local and never enter semantic snapshots or search
ranking. Normal `atlas analyze` runs do not build the search index, so the seven
semantic-search phases are absent unless snapshot search is explicitly invoked.

PR136 measurements are also request-local and never enter semantic snapshots,
impact ordering, or confidence. Normal `atlas analyze` runs do not execute impact
queries, so impact phases are absent unless `atlas impact` is explicitly invoked.

Filesystem coverage is separately `partial/explicit-instrumentation-boundaries` when
enabled. Therefore phase wall/CPU observations and explicit filesystem counters do
not constitute a complete CPU-bound/I/O-bound classification without OS I/O evidence.
