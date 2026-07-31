# Atlas

Atlas is a modular static-analysis platform for multi-project workspaces.
Atlas 2.0 provides deterministic analysis reports, incremental, concurrent,
adaptive, and distributed execution, crash recovery, baselines, Git-diff
analysis, watch mode, quality gates, plugin and rule SDKs, SARIF output, CI
templates, historical reporting, profiling, dashboards, structured logging,
and opt-in governance.

`atlas analyze` now drives the complete semantic context pipeline: project
analysis returns immutable semantic documents, successful runs publish
`.atlas/ass/latest.ass`, and interrupted runs can restore source-free semantic
results without reanalyzing completed projects. See
[`docs/PR121_COMPLETE_AI_CONTEXT_PIPELINE.md`](docs/PR121_COMPLETE_AI_CONTEXT_PIPELINE.md).

Python repositories now publish modules, classes, functions, globals, imports,
decorators, annotations, and docstrings to the same context. See
[`docs/PR122_PYTHON_SEMANTIC_ANALYZER.md`](docs/PR122_PYTHON_SEMANTIC_ANALYZER.md).

Semantic snapshots publish a deterministic unified knowledge graph containing
repository structure, cross-language symbols, dependencies, frameworks, build
systems, and their semantic relationships. The graph remains source-free and
can be restored through `KnowledgeGraph.from_dict()`. See
[`docs/PR129_UNIFIED_KNOWLEDGE_GRAPH.md`](docs/PR129_UNIFIED_KNOWLEDGE_GRAPH.md).

Reachability analysis consumes that graph conservatively, separates production and
test reachability, protects structured external/framework/reflection/Service
Loader/generated contracts, and reports incomplete call coverage instead of
inventing dead-code certainty. See
[`docs/PR131_DEAD_CODE_REACHABILITY.md`](docs/PR131_DEAD_CODE_REACHABILITY.md).

The current repository includes completed work through PR106. Recent production
hardening added linear-time semantic table builders, thread-safe global symbol
storage, a reproducible 23,000-file benchmark, a versioned public API boundary,
and an explicit plugin threat model.

## Install

```text
python -m pip install moughorai
atlas --version
atlas analyze .
atlas check . --adaptive --workers 4
atlas dashboard .
```

Atlas requires Python 3.12 or newer. Workspace configuration is read from
`atlas.yaml`.

## Operational features

- Durable workspace state and crash-recovery journals
- Dependency-aware concurrent, adaptive, and distributed execution
- Deterministic text, JSON, JSONL, and SARIF reports
- Finding baselines, Git-diff analysis, watch mode, and quality gates
- Historical reports, performance profiling, progress events, and dashboards
- Rule authoring, testing, metadata, auto-fix, and rule-pack tooling
- Opt-in structured JSON or text logging with correlation IDs and redaction

Enable structured logging without changing normal CLI output:

```text
atlas --log-level info --log-format json \
  --correlation-id build-123 analyze .
```

## Public API

External Python consumers should use the versioned compatibility facade:

```python
from moughorai.public_api import AnalysisRequest, Project, Workspace
```

Legacy imports remain available. See
[`docs/PR105_PUBLIC_API_BOUNDARY.md`](docs/PR105_PUBLIC_API_BOUNDARY.md) for the
supported surface and compatibility policy.

## Performance

Run the reproducible large-workspace benchmark:

```text
python -m benchmarks.benchmark_large_workspace
```

The default workload creates 23 projects containing 23,000 source files and
measures Atlas production indexing and workspace-fingerprinting paths. Generated
data is temporary unless an explicit workspace path is supplied.

## Plugin security

Plugins execute as trusted in-process Python code. Atlas provides opt-in digest
verification and permission admission policies, but these controls are not an
OS sandbox and do not intercept plugin actions after loading. Production users
should combine strict trust policy with immutable artifacts and external process
or container isolation. Read
[`docs/PR106_PLUGIN_TRUST_MODEL.md`](docs/PR106_PLUGIN_TRUST_MODEL.md) before
deploying third-party plugins.

Start with the [architecture and concepts guide](docs/ARCHITECTURE.md).
Detailed feature documentation is available in [`docs/`](docs/).

## Development

```text
python -m pip install -e ".[dev]"
python -m pytest
```

The verified PR106 repository suite contains 3,323 tests. Benchmark timings are
machine-dependent and are deliberately not used as pass/fail thresholds.

Atlas is distributed under the MIT License.
# Atlas AI 1.0

Atlas includes an ASS-grounded AI layer with a dedicated `atlas ai` CLI,
conversation memory, Explain/Review/Ask engines, validated non-applying patch
proposals, Git context, and an editor-neutral IDE protocol. See
`docs/PR120_ATLAS_AI_1_0.md`.
