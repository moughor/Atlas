# PR104 — Large-Workspace Benchmarks

`benchmarks/benchmark_large_workspace.py` provides a reproducible workload for
validating Atlas at the 23,000-file Sygma scale. It creates a temporary,
deterministic multi-project Java workspace and exercises the production
`ProjectFileIndexer` and `WorkspaceCache` paths.

Run the standard workload:

```text
python -m benchmarks.benchmark_large_workspace
```

Use `--files` and `--projects` for smaller or larger workloads. `--workspace`
retains the generated corpus at an explicit location for profiling; otherwise
the corpus is removed automatically. The sorted JSON report contains separate
setup, indexing, and fingerprint timings, measured throughput, peak traced
memory, and a deterministic content checksum.

Timing and memory fields describe the current machine and are intentionally not
used as pass/fail thresholds. Tests assert corpus completeness, report shape,
and checksum reproducibility to avoid flaky performance gates.
