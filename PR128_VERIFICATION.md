# PR128 Verification

From a clean checkout of `47a3657`:

```powershell
git apply --check PR128.patch
git apply PR128.patch
python -m pytest -q tests/test_pr128_architecture_detection.py `
  tests/test_java_architecture_graph.py `
  tests/test_pr127_repository_summary.py `
  tests/test_ai_context_pipeline_integration.py
```

Inspect `.atlas/ass/latest.ass` after analysis and confirm that
`semantic_context.architecture` contains deterministic findings with confidence
and non-empty evidence, plus dependency directions, cycles, bounded contexts,
ports/adapters, and infrastructure layers.
