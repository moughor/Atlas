# PR129 Verification

1. Apply `PR129.patch` to a clean checkout of baseline commit `dfac541`.
2. Run:

   ```text
   python -m pytest -q tests/test_pr129_knowledge_graph.py \
     tests/test_pr27_knowledge_graph.py \
     tests/test_pr125_cross_language_workspace.py \
     tests/test_pr128_architecture_detection.py \
     tests/test_ai_context_pipeline_integration.py
   ```

3. Run the complete suite:

   ```text
   python -m pytest -q
   ```

4. Analyze a workspace and inspect
   `.atlas/ass/latest.ass`:

   - `semantic_context.semantic_graph.schema_version` is `1`;
   - node kinds include repository/workspace/project/module and language
     symbols;
   - dependency, framework, and build-system facts appear when detected;
   - edges contain deterministic semantic evidence;
   - no raw source text appears.

## Production support

Populated in the normal pipeline:

- imports: Python and TypeScript when a unique internal target resolves;
- inheritance: Java and Python when the target resolves internally;
- overrides: Java methods with `@Override` and a matching resolved internal
  ancestor method;
- dependencies: workspace project dependencies, declared dependencies, and
  scoped framework evidence;
- membership and ownership: global-symbol and workspace metadata.

Supported by the model but not populated:

- composition;
- calls;
- build targets/tasks (`build_system` is populated instead).

Intentionally deferred:

- speculative call/name resolution;
- treating every typed field as lifecycle composition;
- unannotated or external Java override inference;
- graph database/distributed persistence.

Verify exact serialization with:

```python
payload = graph.to_dict()
assert KnowledgeGraph.from_dict(payload).to_dict() == payload
```
