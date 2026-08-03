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

Filesystem coverage is separately `partial/explicit-instrumentation-boundaries` when
enabled. Therefore phase wall/CPU observations and explicit filesystem counters do
not constitute a complete CPU-bound/I/O-bound classification without OS I/O evidence.
