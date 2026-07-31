# PR131 Verification

## Baseline

Apply `PR131.patch` to a clean checkout of commit `b42138b`.

## Focused tests

```text
python -m pytest -q \
  tests/test_pr131_reachability.py \
  tests/test_pr114_explain_engine.py \
  tests/test_pr17_reachability.py \
  tests/test_pr36_interprocedural_call_graph.py \
  tests/test_pr37_data_flow_analysis.py \
  tests/test_pr46_framework_models.py \
  tests/test_java_spring_analysis.py \
  tests/test_pr124_analyzer_registry.py \
  tests/test_pr127_repository_summary.py \
  tests/test_pr128_architecture_detection.py \
  tests/test_pr129_knowledge_graph.py \
  tests/test_pr130_design_patterns.py \
  tests/test_ai_context_pipeline_integration.py \
  tests/test_pr111_semantic_snapshot.py
```

Verify direct/transitive and production/test traversal; optional specialized calls;
constructor ownership; missing-call uncertainty; public/external protection;
framework, reflection, Service Loader, generated/annotation, and CFG evidence;
partial failures; cache invalidation; bounds; source-free publication; deterministic
ordering and IDs; expanded and grouped exact round trips; and old-snapshot behavior.

## Complete suite

```text
python -m pytest -q -p no:cacheprovider
```

Run once after focused tests and record the exact result in
`PR131_TEST_REPORT.md`.

## Runtime acceptance

```text
python -m moughorai.atlas_cli analyze \
  C:\path\to\junit-team --no-recover
```

Inspect `.atlas/ass/latest.ass` and verify:

- `semantic_context.reachability.schema_version == 1`;
- producer version is `atlas-pr131/1`;
- serialization is `grouped-findings-v1`;
- grouped round-trip through `DeadCodeReport` is exact;
- every root/finding/coverage/capability evidence ID resolves;
- unavailable calls produce unknown rather than dead findings;
- no raw source is present;
- snapshot growth remains within the PR131 planning target.

## Compatibility

Confirm the PR129 graph payload, PR130 design-pattern report, architecture and
repository-summary fields remain loadable. Load a pre-PR131 snapshot and treat missing
reachability as unavailable. Confirm failed workspace analyses still do not replace
the latest successful snapshot.
