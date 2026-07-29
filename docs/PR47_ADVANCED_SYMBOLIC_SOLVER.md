# PR47 — Advanced Symbolic Solver

PR47 extends Atlas symbolic reasoning without changing the PR41 public execution model. It adds affine interval reasoning, stronger boolean and nullability contradictions, string predicates (`startsWith`, `endsWith`, `contains`), collection length and emptiness facts, deterministic solve summaries, and contradiction explanations. The existing `is_feasible` entry point delegates to the advanced solver after its compatibility checks.
