# PR109 — Prompt Builder

`SemanticPromptBuilder` combines PR108 semantic JSON with versioned prompt
templates and returns a PR107 `LlmRequest`. Template fields are restricted to
plain identifiers, required variables fail explicitly, and input ordering is
stable.

`TokenEstimator` provides a documented provider-neutral heuristic (four
characters per estimated token by default). It supports deterministic
preflight budgets; provider-reported usage remains authoritative when present.

The original `PromptBuilder` API remains available unchanged.
