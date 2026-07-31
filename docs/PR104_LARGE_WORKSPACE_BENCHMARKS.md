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

## External repository protocol

For repeatable real-repository measurements:

1. Pin both the Atlas commit and repository commit.
2. Record the interpreter, operating system, command, worker count, and cache mode.
3. Run at least three times and retain project count, success count, elapsed time,
   and hashes of deterministic semantic context sections.
4. Compare repository hierarchy, dependency ordering, and structured explanation
   input rather than nondeterministic provider prose.
5. Keep raw outputs outside version control and publish compact summaries suitable
   for regression tracking.

Useful future benchmark families include Spring Framework, a large Gradle reactor,
Elasticsearch, Quarkus, Micronaut, OpenRewrite, and JUnit. Each should be added only
with a pinned revision, documented expected project count, and an automated compact
result schema.
