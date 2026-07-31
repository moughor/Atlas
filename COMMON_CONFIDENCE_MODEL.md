# Atlas 2.x Common Confidence Model

Confidence is deterministic evidence quality and coverage, never an arbitrary detector
or LLM opinion. Each conclusion declares required and corroborating evidence roles.

Inputs:

- reliability: resolved semantic/graph fact `1.00`, structured analyzer result `0.90`,
  structured repository/build metadata `0.80`, reproducible heuristic metric `0.60`,
  name-only or LLM inference `0.00`;
- specificity: how uniquely evidence supports the conclusion;
- coverage: observed eligible subjects / known eligible subjects;
- agreement: weighted non-conflicting observations;
- contradiction and ambiguity penalties from explicit evidence.

Shared constants are versioned; individual features cannot tune them.

`support = Σ(reliability × specificity × role_weight) / Σ(role_weight)`

`confidence = clamp(support × coverage × agreement - contradiction - ambiguity, 0, 1)`

Required roles weigh `2`, corroborating roles `1`. A missing required role makes the
result `insufficient` regardless of score. No roles yield `unknown`, not a negative.
Inputs sort by evidence ID and scores round to four decimals.

| Score | Tier | Wording |
|---|---|---|
| `>= 0.80` | high | detected |
| `0.60–0.7999` | medium | likely |
| `0.40–0.5999` | low | possible |
| `< 0.40` or required role missing | insufficient | not enough evidence |

Serialize score, tier, evidence IDs, limitations, coverage, and model version.
Repository confidence is coverage-weighted across scopes; project-local evidence is
not promoted automatically. LLMs may explain supplied confidence but cannot alter it.
