# PR110 Verification

1. Apply `PR110.patch` to the PR109 commit.
2. Run `python -m pytest -q --basetemp=.pytest_pr110_verify`.
3. The tests use `httpx.MockTransport`; no Ollama server or network is needed.
