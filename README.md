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

PR133 composes those existing facts into one immutable, source-free AI repository
report. Every canonical section records capability and observation state; findings
retain evidence, producer, deterministic confidence where applicable, producer
coverage where available, and limitation metadata. Exact measurements use their
capability state instead of fabricated numeric coverage. The
default `atlas ai explain` renders a deterministic 7,000-token projection without
requiring an LLM, while older snapshots retain the accepted legacy explanation.
See [`docs/PR133_AI_REPOSITORY_REPORT.md`](docs/PR133_AI_REPOSITORY_REPORT.md).

PR134 resolves repository subjects against canonical PR129 identities and composes
bounded, deterministic explanations with exact evidence closure, confidence,
availability, lineage, limitations, citations, and truncation metadata. Targeted
`--json` output requires no LLM; optional narrative generation receives only the
selected source-free explanation rather than the complete semantic snapshot. See
[`docs/PR134_EXPLAIN_ANYTHING.md`](docs/PR134_EXPLAIN_ANYTHING.md).

The current repository includes completed work through PR134. Recent repository
intelligence work adds source-free summaries, a canonical knowledge graph,
evidence-backed architecture and design-pattern findings, conservative
reachability, deterministic risk/hotspot indicators, bounded executive reports, and
canonical subject explanations.

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

M1 adds a repository-neutral runner that records pinned provenance, exact project
results, deterministic hashes, environment identity, and timing samples without
hardcoding Maven, Quarkus, or any other repository:

```text
python -m benchmarks.repository_benchmark --help
```

See [`benchmarks/README.md`](benchmarks/README.md) and the
[`docs/stability/`](docs/stability/) strategies before accepting or updating a
baseline. Raw ASS hashes prove artifact integrity but are not portable semantic
goldens because capture history and workspace roots participate in snapshot data.

Run the reproducible large-workspace benchmark:

```text
python -m benchmarks.benchmark_large_workspace
```

Replay a semantic snapshot through the PR133 report benchmark:

```text
python -m benchmarks.benchmark_pr133_repository_report path/to/latest.ass
python -m benchmarks.benchmark_pr133_repository_report --synthetic-projects 10000 --measure-memory
python -m benchmarks.benchmark_pr134_explain_anything path/to/latest.ass
python -m benchmarks.benchmark_pr134_explain_anything --nodes 10000 100000 1000000
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

The M1 stabilization validation completed 3,681 passing tests with one explicitly
skipped test. Benchmark timings are machine-dependent and follow the documented
comparison thresholds rather than acting as unqualified pass/fail evidence.

Atlas is distributed under the MIT License.
# Atlas AI 1.0

Atlas includes an ASS-grounded AI layer with a dedicated `atlas ai` CLI,
conversation memory, Explain/Review/Ask engines, validated non-applying patch
proposals, Git context, and an editor-neutral IDE protocol. See
`docs/PR120_ATLAS_AI_1_0.md`.

The default `atlas ai explain` repository overview prefers the persisted PR133
repository report and is rendered deterministically from a token-bounded,
source-free projection. It does not send repository
facts to an LLM, so a provider cannot replace counts, invent technologies, or
promote weak evidence into facts. Explanations for an explicit `--subject` resolve a
canonical PR129 identity and construct a bounded structured context. `--json` renders
that context deterministically without a provider; optional narrative generation can
use the configured provider but receives no raw source or complete ASS. Metric
definitions and current limitations are documented in
[`docs/ATLAS_AI_EXPLAIN_ACCURACY_REVIEW.md`](docs/ATLAS_AI_EXPLAIN_ACCURACY_REVIEW.md).

## Repository report and risk analysis

PR132 adds deterministic, evidence-backed repository risk rankings to semantic
snapshots and repository explanations. Atlas combines only available structured
signals, keeps confidence separate from the score, and reports missing evidence
as unavailable rather than zero. The normal pipeline currently contributes
positive canonical graph degree, complete project inventory bytes, and bounded
Git change facts; complexity and resolved test density require authoritative producers.
See [`docs/PR132_RISK_HOTSPOT_ANALYSIS.md`](docs/PR132_RISK_HOTSPOT_ANALYSIS.md).

PR133 does not turn risk indicators into defects, missing analyses into negative
findings, or test-file inventory into test quality. Strengths and weaknesses remain
explicitly unavailable until an authoritative structured producer exists.
