# PR132 Existing Capabilities and Gap Analysis

## Scope decision

PR132 implements Risk and Hotspot Analysis exactly at its official roadmap
position. It extends PR129's canonical `KnowledgeGraph`; it does not create a
second repository graph, call graph, CFG, evidence model, confidence model,
cache framework, or repository model. It additively extends the existing
repository-summary model with file-size completeness metadata required to avoid
scoring unreadable bytes as zero.

## Capability inventory

| PR132 input | Existing capability | Reused in PR132 | Remaining boundary |
| --- | --- | --- | --- |
| Canonical topology | PR129 nodes, edges, incoming and outgoing indexes | One-pass, relation-filtered distinct-neighbour degree summaries | Canonical calls and composition are modelled but absent from the normal producer |
| Structural ownership | PR129 repository/workspace/project/module containment | Inspected and deliberately excluded from the contributor metric | It is not contributor ownership and is never scored as such |
| Project size | PR127 repository inventory file counts and bytes | `inventoried_file_bytes` only when the new stat-completeness count is zero, with a partial legacy `size` fallback | An incomplete modern inventory is unavailable; no symbol LOC, byte span, or callable size is persisted |
| Test metadata | PR127 classified production, test, and generated file counts | Scope reporting only | There is no resolved production-symbol-to-test mapping or test coverage evidence |
| Git context | PR118 Git service and subprocess/error conventions | Extended with one bounded repository-wide `git log --numstat` window | First-parent semantics, rename attribution, and long-term history are not inferred |
| Contributor evidence | Git commit author metadata | Pseudonymous contributor digests and aggregate change-author concentration | The digest is not an anonymity guarantee; Atlas does not publish identities or rank developers |
| Complexity | CFG and flow components exist in specialized domains | Structured external observations are accepted | No production complexity producer is connected to snapshots |
| Pattern findings | PR130 evidence-backed findings | Compatible optional context; no hidden score weight | Missing patterns do not affect the baseline formula |
| Reachability | PR131 findings, coverage, lineage, and specialized calls | Compatible optional context; no hidden score weight | Missing calls or roots never lower a risk score |
| Evidence/confidence | PR130 `EvidenceRecord`, `EvidenceIndex`, and `ConfidenceCalculator` | Reused directly | Risk score and confidence remain separate values |
| Persistence | Source-free semantic snapshots | Additive `risk_analysis` key | Older snapshots omit the key and degrade to unavailable |
| AI explanation | Bounded deterministic repository projection | Compact top-k risk indicators | Targeted symbol explanation behavior is unchanged |

## Roadmap gap analysis

| Planned PR132 capability | Baseline state | PR132 decision |
| --- | --- | --- |
| Canonical fan-in/fan-out | Partially implemented: PR129 had adjacency indexes but no filtered degree summary | Implemented as a deterministic distinct-neighbour query and consumed without altering graph serialization |
| Complexity | Missing production observation producer | Structured input and unavailable capability state implemented; no complexity value is invented |
| Git churn/change frequency | Partially implemented: PR118 exposed current Git context, not bounded history | Extended PR118 with one workspace-scoped, bounded, non-merge history query; exact commit-touch frequency is scored and line changes remain evidence detail |
| Size | Partially implemented at project inventory scope: stat failures previously became indistinguishable zero-byte values | Added a backward-compatible stat-error count; exact inventoried bytes are scored only when complete, with a documented partial legacy `size` fallback; no symbol LOC is inferred |
| Contributor ownership | Missing as a human-ownership fact; PR129 ownership is structural | A clearly named, lower-confidence Git change-author concentration proxy is available; structural ownership is excluded from this metric |
| Test density | Missing resolved production-symbol-to-test mapping | Explicitly unavailable unless supplied by a structured producer; inventory test counts are not substituted |
| Formula, rankings, confidence, and heatmaps | Missing | Implemented with fixed weights, available-weight renormalization, separate shared confidence, bounded top-k, and aggregate normalized bins |
| Snapshot and AI publication | Missing | Implemented as additive, bounded, source-free fields with legacy-unavailable behavior |
| Predictive ML, developer scoring, expensive centrality | Out of scope | Intentionally deferred; no hidden approximation was added |

No ADR was required: PR132 extends the existing PR129 graph-query surface and
PR130 evidence/confidence contracts without changing their architecture or
serialized graph contract.

## Evidence that can be populated normally

- Positive canonical relationship fan-in and fan-out, scoped by relation and
  endpoint kind and counted as distinct neighbours. `ownership` and
  `member_of` are excluded from coupling. An absent relationship remains
  unknown rather than becoming a zero observation.
- Project inventory size in bytes, including its unit and inventory limitation.
- Project change frequency within the configured Git commit window when Git
  evidence is available.
- Project change-author concentration within that same Git window, without
  publishing contributor identifiers. This is a bounded proxy, not blame
  ownership, CODEOWNERS, bus factor, or developer performance.

## Explicitly unavailable without another structured producer

- cyclomatic or cognitive complexity;
- method or type size;
- resolved symbol-to-test density or test coverage;
- call fan-in and call fan-out when authoritative call evidence is absent;
- trend when no compatible previous PR132 report is supplied.

Unavailable signals do not receive a zero. Their configured weights are removed
from the risk score and their absence lowers confidence.

## Compatibility and regression risks

- PR129 serialization and edge semantics remain unchanged.
- Duplicate graph edges carrying different evidence cannot inflate degree
  counts because degrees count distinct neighbours.
- Legacy repository summaries using `size`, `files`, and `languages` remain
  accepted.
- Git failures are isolated as capability limitations and do not fail workspace
  analysis.
- Git history is scoped to the analyzed workspace even when that workspace is a
  subdirectory of a larger Git repository; merges and renames are excluded and
  shallow/truncated history is disclosed.
- Per-subject graph or Git evidence is retained only for the bounded top-k,
  preventing graph duplication in semantic snapshots.
- Test, generated, and unknown scopes are measured but excluded from the
  default production ranking and reported through coverage counts.

No PR133 or later capability is implemented by PR132.
