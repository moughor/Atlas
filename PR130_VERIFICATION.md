# PR130 Verification

## Baseline

Apply `PR130.patch` to a clean checkout of commit `f848850`.

## Focused verification

Run:

```text
python -m pytest -q tests/test_pr130_design_patterns.py
python -m pytest -q tests/test_pr114_explain_engine.py
python -m pytest -q \
  tests/test_pr128_architecture_detection.py \
  tests/test_pr129_knowledge_graph.py \
  tests/test_pr111_semantic_snapshot.py \
  tests/test_ai_context_pipeline_integration.py
```

Verify:

- evidence IDs are stable for normalized identical inputs;
- missing required evidence produces `insufficient`;
- report serialization round-trips exactly;
- shuffled graph inputs produce identical reports;
- name-only candidates produce no findings;
- Java Strategy and Builder findings are published through normal analysis;
- optional structured call evidence supports the documented call-dependent patterns;
- Java architecture artifacts survive persisted analysis-result recovery;
- no raw source is stored in pattern reports.
- repository explanations include compact pattern metadata when available;
- unavailable pattern analysis is stated explicitly;
- repository prompts omit participant identities, evidence details, and large symbol
  lists;
- targeted symbol explanations preserve the existing detailed context path.

## Complete verification

Run the complete suite once:

```text
python -m pytest -q
```

Record the exact result and warnings in `PR130_TEST_REPORT.md`.

## Runtime snapshot inspection

Analyze a Java workspace and inspect `.atlas/ass/latest.ass`:

- `semantic_context.design_patterns.schema_version` is `1`;
- `producer_version` and `input_fingerprint` are present;
- findings contain participants, confidence, evidence IDs, explanation, and
  limitations;
- every finding evidence ID resolves in `evidence_index.records`;
- unavailable semantic producers appear as `insufficient` capabilities;
- no source text appears in the report.

For repository-level explanations, confirm that only the compact fields `pattern`,
`status`, `confidence`, `participating_symbols_count`, `evidence_count`, and
`limitations` enter the default prompt.

## Compatibility

Confirm PR128 architecture and PR129 graph fields remain unchanged. Load an older
snapshot without `design_patterns`; it must remain valid. Encode/decode both Java
documents with and without `java_architecture_graph`.
