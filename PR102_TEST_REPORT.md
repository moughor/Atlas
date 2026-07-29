# PR102 Test Report

Date: 2026-07-29

Baseline PR101 (`fc46e30`): **3294 passed in 7.44s**.

Focused concurrency and consumer matrix:

```text
python -m pytest tests/test_pr21_global_symbol_database.py tests/test_pr23_incremental_analysis.py tests/test_pr24_cross_references.py tests/test_pr25_semantic_search.py tests/test_pr26_impact_analysis.py tests/test_pr27_knowledge_graph.py tests/test_pr28_context_builder.py tests/test_pr29_ai_retrieval.py tests/test_pr102_global_symbol_concurrency.py -p no:cacheprovider --basetemp=.pytest_pr102_focused -q
```

Result: **128 passed in 0.39s**.

Full suite:

```text
python -m pytest -p no:cacheprovider --basetemp=.pytest_pr102_full -q
```

Result: **3301 passed in 6.75s**.

Clean replay from PR101 commit `fc46e30` passed `git apply --check` and
`git diff --check`.

Result: **3301 passed in 8.14s**.
