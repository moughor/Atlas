# Atlas 2.x Performance Targets — PR130–PR139

Measured PR129 JUnit baseline: 15,418,187 snapshot bytes, 4,929,300 semantic-graph
bytes, 13,335 nodes, and 14,105 edges. Limits below are planning targets.

- Derived passes are `O(V + E)` unless explicitly bounded.
- Index storage is `O(V + E)`.
- Interactive query p95: <250 ms at 100k nodes and <1 s at 1M indexed nodes.
- AI context selection p95: <500 ms and token-bounded.
- Incremental work scales with changed subjects plus invalidated closure.
- Per-PR peak RSS growth target: <=20%; PR139 cumulative: <1.75× PR129.

| PR | Stored data | Snapshot growth | Time target |
|---|---|---:|---|
| 130 | pattern findings/evidence refs | <=8% | <=15% cold |
| 131 | reachability states/roots | <=10% | <=20% cold |
| 132 | metrics/ranks | <=6% | <=15% cold |
| 133 | repository report | <=4% | <=2 s build |
| 134 | indexes; explanations ephemeral | <=2% | <=500 ms selection |
| 135 | search indexes | <=15% disk, <=5% snapshot | <=250 ms p95/100k |
| 136 | impact summaries | <=8% | <=1 s bounded query |
| 137 | advisory findings | <=8% | <=20% cold |
| 138 | security summaries | <=10% | <=25% cold |
| 139 | metadata outside snapshot | <=2% snapshot | <=750 ms assembly |

Through PR139, JUnit snapshot target is <=1.5× PR129 and graph/derived storage <=2×.
Deduplicate evidence; never store all transitive paths, prompts, answers, or source.
Use adjacency indexes, compact IDs, bounded BFS/DFS, top-k heaps, streaming
serialization, and versioned caches. Limit hits return deterministic partial results
with coverage/truncation rather than silently dropping evidence.
