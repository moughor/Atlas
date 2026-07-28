# PR40 — Repository Security CI Gate

PR40 turns the Java security frontend into a repository-scale, policy-driven CI scanner.
It supports JSON/YAML policies, rule and path filtering, auditable suppressions,
fingerprint baselines, new-finding-only gates, finding budgets, JSON/SARIF output,
and deterministic exit codes (`0` pass, `1` fail).
