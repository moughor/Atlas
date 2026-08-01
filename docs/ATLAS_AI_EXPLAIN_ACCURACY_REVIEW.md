# Atlas AI Explain Accuracy Review

## Status and production recommendation

The default repository form of `atlas ai explain` is suitable for factual use on
large repositories after this hardening. Its output is deterministic Markdown
rendered directly from a bounded, source-free Atlas projection. No LLM is called,
so a provider cannot change counts, invent technologies, or promote a candidate
into a fact.

Targeted `--subject` explanations intentionally retain the existing LLM path.
They remain grounded by the semantic snapshot but are narrative output and should
not be treated as a replacement for structured Atlas facts.

## Root cause

The Quarkus snapshot contained the correct repository summary, but the old
default path serialized about 3.52 million characters (roughly 881,000 estimated
tokens) into a prompt and returned any non-empty provider response without a
factual schema check. The provider consequently substituted the 1,442-project
count for 12,889 classified non-test source files, omitted Gradle, invented entry
points and technologies, promoted a project byte count to repository scope, and
emitted language percentages totaling 101%.

Prompt wording could not guarantee factual output. The correction is therefore
at the presentation boundary: deterministic Atlas facts first, with LLM reasoning
excluded from the default repository report.

## Field-by-field contract

| Output field | Computation and evidence | Semantics and confidence |
| --- | --- | --- |
| Repository name | Final component of the persisted repository root | Deterministic identity projection; not inferred from repository contents |
| Discovered projects | Persisted repository-summary project count, falling back to the exact project collection length | Exact workspace discovery count |
| `inventoried_file_count` | Sum of selected inventory files across discovered projects | Unit: files; not source files or compilation units |
| `inventoried_file_bytes` | Sum of successfully statted selected inventory files | Unit: bytes; not LOC, source bytes, or total filesystem size |
| `classified_non_test_source_files` | Inventory `SOURCE` files without an exact test-path marker | Not compiler-proven production code; legacy alias: `production_files` |
| `classified_test_source_files` | Inventory `SOURCE` files with an exact test-path marker | Inventory classification; legacy alias: `test_files` |
| `classified_generated_files` | Files under configured generated-path markers | Not necessarily source code; legacy alias: `generated_files` |
| Language distribution | Recognized-extension inventory file counts | Includes source, test, generated, resources, and templates; not analyzer coverage |
| Language percentage | Integer basis-point largest-remainder allocation over exact language counts | Deterministic, ordered by count then language; sums to exactly 10,000 basis points |
| Build systems | Project counts from build-descriptor filename detections | Membership can overlap, so no percentages or unsupported “primary” claim |
| Frameworks and related technologies | Aggregated detector-matched dependency/plugin references, projects, and persisted scopes | Adoption confidence remains `insufficient`; primary/supported/compatibility roles are `unknown` without explicit evidence |
| Entry-point candidates | Persisted static-main, Python-main, or manifest candidates | Runtime role is `unknown`; application, CLI, lifecycle, build, and important-type roles are not inferred from names |
| Filesystem project hierarchy | Nearest containing discovered project path | Filesystem containment only; not reactor, deployment, domain, or bounded-context structure |
| Declared dependency records | Parsed manifest records grouped by ecosystem | Not unique or resolved external packages; managed and direct declarations can both occur |
| Dependency manifests | Distinct parsed manifest sources grouped by ecosystem | Count of manifests, not dependencies |
| Architecture findings | Existing PR128 findings plus evidence-kind review | Name, hierarchy, and entry-candidate-only findings are presented as `insufficient`; producer confidence is preserved separately |
| Dependency cycles/directions | Existing dependency analysis metadata | Reported only when execution is recorded with positive edge evidence |
| Design patterns | Bounded aggregation of PR130 findings and their supplied evidence/confidence | Atlas findings retain representative evidence IDs; participant lists remain omitted |
| Reachability | Bounded PR131 statistics, coverage, limitations, and representative candidates | Missing calls never prove dead code; no “safe to delete” inference |
| Technologies | No independent exhaustive technology field exists in the snapshot | The report does not invent one; only persisted framework-or-related-technology evidence is shown |

Exact measurements use `confidence.status = not-applicable` because they are
measurements rather than uncertain conclusions. Inferred classifications expose
`unknown`, `unavailable`, or `insufficient` when the evidence contract is absent.
Provider prose never creates or modifies confidence.

## Incorrect old fields and replacements

| Old presentation | Problem | Current presentation |
| --- | --- | --- |
| `production_files` | Ambiguous and was replaced by project count in provider prose | Legacy key retained; explain uses `classified_non_test_source_files` with definition |
| `size` | No repository scope or unit | `inventoried_file_bytes`, explicitly bytes and inventory-scoped |
| `languages` percentages | Provider-generated, incomplete, and totaled 101% | Exact `language_file_counts` plus deterministic basis points |
| `Maven 100%` | Ignored overlapping Gradle detections | Per-build detected-project counts; no percentage |
| `Spring Boot` | Unsupported by the Quarkus snapshot | Omitted unless detector evidence exists; adoption role remains insufficient |
| `technologies` descriptions | Entirely provider-generated | Omitted because no exhaustive structured field exists |
| Application entry points | Mixed source candidates, tests, generators, and build types | `entry_point_candidates` with unresolved runtime role |
| Architecture labels as facts | Weak name/hierarchy evidence could overstate topology | Producer score retained, presentation status set to insufficient when required evidence is absent |

The repository summary version 1 extensibility contract adds explicit keys while retaining `files`,
`size`, `languages`, `production_files`, `test_files`, `generated_files`,
`dependencies_by_ecosystem`, and `total_declared_dependencies` for compatibility.
Older snapshots are normalized by the explain projection and receive the same
conservative wording.

## Framework and technology classification

Maven framework matching now uses the existing coordinate-aware detector only.
Broad artifact substring matching is no longer applied to Maven coordinates, so
tokens such as `react` inside `reactive` and `spring` inside internal integration
artifact names do not establish React or Spring adoption. Non-Maven package rules
use exact package identities.

Persisted evidence scope can establish `test-or-sample-evidence`,
`optional-integration-evidence`, or `build-tooling-evidence`. It cannot by itself
establish a primary, supported, or compatibility role. Those roles remain unknown
until a producer records the required structured evidence.

## Bounded deterministic projection

The report keeps exact totals but bounds detail:

- 30 framework/technology names and 3 representative references per name;
- 20 entry-point candidates;
- 25 hierarchy relationships;
- 12 architecture findings and 20 dependency examples;
- 20 pattern types;
- 8 reachability candidates.

Architecture, pattern, and reachability conclusions retain at most three
representative evidence references or IDs each, together with exact omitted
counts, so displayed conclusions remain traceable without unbounded payloads.

Every bounded collection includes total, included, and omitted counts. A synthetic
1,500-project/10,000-evidence test verifies that the canonical projection remains
under 60,000 JSON characters while preserving exact aggregate counts.

## Before/after comparison

Representative old provider output (not supported by its snapshot):

```json
{
  "project_count": 1442,
  "production_files": 1442,
  "size": 253551,
  "languages_percent": {"Java": 90, "Kotlin": 5, "Shell": 3, "HTML": 2, "SQL": 1},
  "build_systems": {"Maven": 100},
  "frameworks": ["Quarkus", "Spring Boot"]
}
```

Current deterministic Quarkus projection from the regenerated snapshot:

```json
{
  "discovered_project_count": 1442,
  "inventory": {
    "inventoried_file_count": {"value": 31226, "unit": "files"},
    "inventoried_file_bytes": {"value": 127490025, "unit": "bytes"},
    "classified_non_test_source_files": {"value": 12889, "unit": "files"},
    "classified_test_source_files": {"value": 11983, "unit": "files"},
    "classified_generated_files": {"value": 58, "unit": "files"}
  },
  "language_file_counts": {"Java": 22166, "JavaScript": 2053, "Kotlin": 478},
  "build_system_project_counts": {"Maven": 1441, "Gradle": 9},
  "build_system_percentages_reported": false,
  "primary_framework": "unknown",
  "entry_point_runtime_roles": "unknown"
}
```

The shortened comparison omits additional languages and bounded evidence details;
the generated report retains them.

## Tests and validation

Focused tests cover provider fact substitution, exact language rounding, small
languages, overlapping build systems, unresolved entry roles, weak architecture
evidence, bounded large-workspace projection, legacy aliases, source-free output,
reordered-input determinism, invalid confidence values, Markdown escaping,
framework evidence scope, and Maven/Gradle framework-coordinate matching.

Validation executed on 2026-08-01:

- focused explain tests: `27 passed in 0.51s`;
- adjacent semantic-context tests: `101 passed in 1.27s`;
- complete Atlas suite: `3513 passed, 1 skipped in 9.20s`;
- Quarkus forced analysis: exit code 0 after 364.3 seconds, 1,442 projects,
  `succeeded: yes`;
- three CLI `atlas ai explain` runs: 369 lines and 19,768 characters each,
  identical SHA-256
  `fa7527a45f9c3cfbc34e5cf8f76bd10927b1eeb5e63876e7578ad84f90670ac1`;
- three JSON projections: 32,008 characters each, identical SHA-256
  `0434dbbdbdd38765461c5873e623fbaf33a430daf1de50c430e00591e4425f05`.

The regenerated snapshot identifier is
`d9d1f6500cfddfee32d16f729739a0f81e20febb467d8455285c6efb6b67f597`.
It contains 31,226 inventoried files, 12,889 classified non-test source files,
11,983 classified test source files, 58 classified generated files, Maven in
1,441 project inventories, and Gradle in 9. Spring and React have no framework
evidence in the regenerated summary. All reported language shares total exactly
10,000 basis points.

## Files modified

- `moughorai/ai_explain/engine.py`
- `moughorai/ai_explain/repository_projection.py`
- `moughorai/ai_explain/repository_report.py`
- `moughorai/project_inventory/classifier.py`
- `moughorai/repository_summary/models.py`
- `moughorai/repository_summary/service.py`
- `tests/test_ai_explain_accuracy.py`
- `tests/test_pr114_explain_engine.py`
- `README.md`
- `CHANGELOG.md`
- `docs/ATLAS_AI_EXPLAIN_ACCURACY_REVIEW.md`
- `docs/PR114_EXPLAIN_ENGINE.md`
- `docs/PR127_REPOSITORY_EXPLAIN_INTEGRATION_FIX.md`
- `docs/PR127_REPOSITORY_SUMMARY_ENGINE.md`

## Remaining limitations

- Build detector evidence paths and descriptor roles are not persisted in the
  repository summary, so embedded fixture descriptors can affect project counts.
- Framework category, producer identity, coverage, direct-versus-managed status,
  and a complete confidence input set are not yet persisted in the flattened
  repository summary. Explain reports insufficient adoption rather than guessing.
- The inventory source split is path/classifier based, not compiler-aware.
- Entry-point candidates do not yet carry resolved runtime roles.
- PR128 still produces heuristic architecture findings; the explain layer prevents
  weak findings from becoming facts but does not change that analyzer.
- Declared dependency records can include both managed and direct declarations and
  are not a resolved dependency graph.

These limitations are explicitly visible in output and do not authorize a new
analysis engine or a duplicated evidence/confidence model.
