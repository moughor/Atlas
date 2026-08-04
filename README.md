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

PR135 adds deterministic intent-based search over those same canonical identities
and structured findings. `atlas search` builds a bounded, immutable in-memory index
from a verified semantic snapshot; it uses no source text, report prose, embeddings,
LLM, or external service. Every ranked hit exposes relevance components, evidence,
confidence, capability sources, and limitations; the response reports capability
states. See
[`docs/PR135_SEMANTIC_SEARCH.md`](docs/PR135_SEMANTIC_SEARCH.md).

PR136 adds deterministic, evidence-backed impact prediction over the existing PR129
graph and PR134 subject resolver. `atlas impact` reports bounded direct and
transitive exposure, capability coverage, conservative breaking-change state, and
explicit uncertainty without source text or an LLM. See
[`docs/PR136_IMPACT_PREDICTION.md`](docs/PR136_IMPACT_PREDICTION.md).

PR137 adds a conservative deterministic refactoring advisor. Its first safe slice
uses only dependency cycles already reported by PR128 and fully revalidated against
authoritative PR129 relationships. `atlas refactor` identifies review seams with
traceable evidence, confidence, explicitly unknown gain and effort where evidence
cannot quantify them, optional bounded PR136 impact context, and explicit
unsupported capabilities. It
does not generate patches or infer recommendations from names or an LLM. See
[`docs/PR137_REFACTORING_ADVISOR.md`](docs/PR137_REFACTORING_ADVISOR.md).

PR138 begins the next official roadmap item, Security Intelligence; it does not
extend or complete PR137. Its first safe slice reuses the existing Java security
adapter while each selected source is already in memory, consolidates the resulting
evidence against PR129 canonical identities, and publishes a bounded source-free
`security_intelligence` snapshot section. `atlas security` queries only a verified
snapshot and supports deterministic repository, project, and symbol scopes without
rescanning source. The default repository explanation includes compact category,
severity, confidence, evidence-reference, and limitation counts. XSS,
interprocedural and cross-project taint, non-Java producers, and PR136 blast-radius
enrichment remain explicitly unavailable or deferred. See
[`docs/PR138_SECURITY_INTELLIGENCE.md`](docs/PR138_SECURITY_INTELLIGENCE.md).

PR139 adds Interactive Engineering Chat by extending the existing `AskEngine` and
workspace-scoped conversation memory. `atlas ai ask` and its `atlas ai chat` alias
resolve and search through PR134--PR135, optionally consume compatible impact,
refactoring, and security results, build a bounded source-free context, validate
provider evidence citations, and persist snapshot lineage and recoverable turn state.
Unavailable or ambiguous capabilities remain explicit; chat never runs analyzers or
turns missing evidence into a fact. See
[`docs/PR139_INTERACTIVE_ENGINEERING_CHAT.md`](docs/PR139_INTERACTIVE_ENGINEERING_CHAT.md).

PR140 adds deterministic, source-free review of tracked Git changes.
`atlas change-review` combines normalized PR92 Git metadata with exact PR134 path
identity, bounded PR136 impact/test/risk context, and compatible PR137 verified
cycle-seam context. Snapshot alignment and unavailable evidence remain explicit.
The command does not rescan by default, so semantic enrichment requires a
caller-verified fingerprint through the API or the explicit, unverified
`--assume-current-snapshot` CLI opt-in. `atlas ai review` remains unchanged. See
[`docs/PR140_CHANGE_REVIEW.md`](docs/PR140_CHANGE_REVIEW.md).

PR141 begins Repository Evolution with a deterministic, request-local comparison of
two checksum-verified semantic snapshots. `atlas evolution` reports bounded exact
changes to PR129 canonical nodes, relationships, and relationship evidence while
keeping commit association unavailable unless compatible PR132 Git-head evidence
exists, and explicitly partial even when it does. The base snapshot is required;
the head can be selected explicitly or use the verified `latest.ass` pointer. Atlas
does not claim complete producer, configuration, or coverage comparability from
matching analyzer versions alone. It never converts remove-plus-add into a rename or
infers API breakage, security causality, architectural drift, runtime behavior, or
developer intent. See
[`docs/PR141_REPOSITORY_EVOLUTION.md`](docs/PR141_REPOSITORY_EVOLUTION.md).

PR142 begins the Technical Debt Engine with a deliberately partial, cycle-only
slice. `atlas debt` ranks only dependency-cycle seams already fully revalidated by
PR137, using bounded PR136 represented impact and compatible exact-subject PR132
risk or structured-complexity context when available. It publishes no composite
debt score and keeps missing impact explicitly unranked; a cycle remains observed
debt evidence rather than proof of a defect. See
[`docs/PR142_TECHNICAL_DEBT.md`](docs/PR142_TECHNICAL_DEBT.md).

The current repository includes implemented work through PR142. PR137 Refactoring
Advisor, PR138 Security Intelligence, and PR142 Technical Debt remain deliberately
partial roadmap items; PR139 consumes only compatible published capabilities. Recent repository
intelligence work adds source-free summaries, a canonical knowledge graph,
evidence-backed architecture and design-pattern findings, conservative
reachability, deterministic risk/hotspot indicators, bounded executive reports, and
canonical subject explanations, search, impact prediction, refactoring advice, and
security intelligence.

## Install

```text
python -m pip install moughorai
atlas --version
atlas analyze .
atlas check . --adaptive --workers 4
atlas dashboard .
atlas search "REST endpoint" .
atlas search "depends on spring-web" . --json
atlas impact "com.example.UserService" . --change signature
atlas impact "dependency:maven:example" . --json
atlas refactor . --subject repository --no-impact
atlas refactor . --subject project:example --family cycle-breaking --json
atlas security .
atlas security . --scope project --project example --category sql-injection --json
atlas ai chat "Explain the repository architecture" .
atlas ai chat "What is the impact of changing UserService?" . --subject UserService --capability impact --json
atlas change-review . --json
atlas change-review . --staged --assume-current-snapshot
atlas evolution . --base-snapshot .atlas/ass/base.ass --head-snapshot .atlas/ass/latest.ass --json
atlas debt .
atlas debt . --subject project:example --candidate-limit 50 --json
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
from moughorai.public_api import (
    AnalysisRequest,
    ImpactPredictionRequest,
    ImpactPredictionService,
    Project,
    RefactoringAdvisorService,
    RefactoringRequest,
    SecurityIntelligenceRequest,
    SecurityIntelligenceService,
    SemanticSearchRequest,
    SemanticSearchService,
    SubjectQuery,
    Workspace,
)
```

Legacy imports remain available. See
[`docs/PR105_PUBLIC_API_BOUNDARY.md`](docs/PR105_PUBLIC_API_BOUNDARY.md) for the
supported surface and compatibility policy.

## Performance

M2 adds opt-in, source-free phase measurement to the normal analysis path without
changing its stdout or semantic outputs:

```text
atlas analyze . --profile
atlas analyze . --profile-output .atlas/measurements/atlas-profile.json
atlas analyze . --profile --profile-memory
atlas analyze . --profile-python-memory
atlas ai explain . --profile
atlas search "dependency injection" . --profile
atlas impact "com.example.UserService" . --profile
atlas refactor . --profile
atlas security . --profile
atlas change-review . --profile
atlas evolution . --base-snapshot .atlas/ass/base.ass --profile
atlas debt . --profile
```

The default sidecar is `.atlas/measurements/latest.json`; a compact summary is written
to stderr. The PR96 `atlas profile` command remains backward compatible and separate.
See [`docs/MEASUREMENT_CLI.md`](docs/MEASUREMENT_CLI.md),
[`docs/MEASUREMENT_SCHEMA.md`](docs/MEASUREMENT_SCHEMA.md), and
[`docs/MEASUREMENT_LIMITATIONS.md`](docs/MEASUREMENT_LIMITATIONS.md). Embedders and
instrumentation maintainers should also use
[`docs/MEASUREMENT_API.md`](docs/MEASUREMENT_API.md) and the
[`docs/MEASUREMENT_PLATFORM_MATRIX.md`](docs/MEASUREMENT_PLATFORM_MATRIX.md).

M2.1 removes repeated whole-workspace fingerprinting from recoverable project
checkpoints while retaining every durable PR70 state save and PR74 journal
transition. Its run-local verified fingerprint set refreshes each completed project
once and never becomes a persistent cache. See
[`docs/stability/M2_1_RECOVERY_CHECKPOINT_INVESTIGATION.md`](docs/stability/M2_1_RECOVERY_CHECKPOINT_INVESTIGATION.md).

M1.1 adds pinned repository definitions and a canonical orchestration layer around
the repository-neutral M1 runner. It records exact provenance, project results,
portable deterministic hashes, environment identity, and timing samples without
adding repository-specific behavior to Atlas analysis:

```text
python -m benchmarks.canonical_baseline list
python -m benchmarks.canonical_baseline --help
python -m benchmarks.repository_benchmark --help
```

See [`benchmarks/README.md`](benchmarks/README.md) and the
[`docs/stability/`](docs/stability/) strategies before accepting or updating a
baseline. Raw ASS hashes prove artifact integrity. Schema-2 manifests also record a
versioned portable semantic projection for cross-root regression comparison.
The accepted Maven and Quarkus M1.1 baseline evidence is recorded in
[`docs/stability/M1_1_VALIDATION_REPORT.md`](docs/stability/M1_1_VALIDATION_REPORT.md).
The benchmark-driven Spring Framework Gradle discovery investigation is recorded in
[`docs/stability/SPRING_FRAMEWORK_INVESTIGATION.md`](docs/stability/SPRING_FRAMEWORK_INVESTIGATION.md).
The portable-path hardening, corrected Java producer drift, and `M1.2 REQUIRED`
golden decision are recorded in
[`docs/stability/SPRING_PORTABLE_PATH_HARDENING.md`](docs/stability/SPRING_PORTABLE_PATH_HARDENING.md).

The Elasticsearch stability investigation documents narrow, statically verified
recursive Gradle membership, exact-counterpart handling for version-specific Java
overlays, and conservative symbol scopes when duplicate types are proven across
Gradle source sets. See
[`docs/stability/ELASTICSEARCH_FAILURE_INVESTIGATION.md`](docs/stability/ELASTICSEARCH_FAILURE_INVESTIGATION.md).

The IntelliJ diagnostic investigation separates fixture-only Java trees and
structured resource roots from compiled semantic inputs while preserving registered
modules and genuine duplicate failures. See
[`docs/stability/INTELLIJ_FIXTURE_SOURCE_ROOT_INVESTIGATION.md`](docs/stability/INTELLIJ_FIXTURE_SOURCE_ROOT_INVESTIGATION.md).

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
