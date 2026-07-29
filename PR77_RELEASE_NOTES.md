# PR77 Release Notes — Finding Baselines

Baseline: PR76 commit `d0567b1`

PR77 adds cross-language finding baselines that ignore accepted issues and
report only new findings. Baselines are atomic, checksummed, versioned, sorted,
and project-aware.

Use `--write-baseline PATH` to capture findings and `--baseline PATH` to filter
text, JSON, JSONL, or SARIF analysis output.
