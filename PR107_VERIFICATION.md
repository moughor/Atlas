# PR107 Verification

1. Check out baseline commit `110b214`.
2. Apply `PR107.patch` and run `git diff --check`.
3. Run the complete pytest suite.
4. Run `tests/test_pr107_llm_provider_abstraction.py`.
5. Confirm registry ordering, timeout propagation, retry exhaustion, and
   streaming failure semantics.
