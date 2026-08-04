# PR139 Performance

## Measurement boundary

PR139 adds deterministic context construction, evidence closure, capability
selection, source-free validation, citation validation, and a typed result envelope
before and after the existing provider call. Provider latency and provider prose are
outside Atlas's deterministic performance contract.

The controlled comparison used the exact PR138 baseline commit
`73cb441ac3637430d97c27904780b1c6cd12d96d` and the final PR139 candidate. Each
process used the same Python runtime, PR138 security fixture, verified snapshot,
question (`Review repository security`), scripted zero-latency provider response,
and nine requests per cohort. Each revision ran in a fresh process, with cohorts in
zero-, five-, then twenty-finding order. The first request is reported separately;
median and p95 are calculated from the remaining eight requests. Working-set values
are the cumulative Windows process peak observed through that row, while Python
allocation peaks were reset and captured around each cohort's nine requests.

## Controlled results

### PR138 baseline

| Published findings | First request | Repeated median | Repeated p95 | Python peak | Peak working set | Prompt | Result |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0.796 ms | 0.626 ms | 0.638 ms | 254,156 B | 54,865,920 B | 26,827 B | 150 B |
| 5 | 1.166 ms | 1.140 ms | 1.162 ms | 454,936 B | 55,185,408 B | 49,161 B | 150 B |
| 20 | 2.696 ms | 2.734 ms | 2.779 ms | 1,072,256 B | 56,717,312 B | 116,233 B | 150 B |

### PR139 candidate

| Published findings | First request | Repeated median | Repeated p95 | Python peak | Peak working set | Prompt | Context | Result |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 113.774 ms | 114.852 ms | 115.562 ms | 539,268 B | 58,916,864 B | 14,472 B | 12,157 B | 12,579 B |
| 5 | 169.825 ms | 172.170 ms | 228.491 ms | 575,055 B | 59,281,408 B | 18,872 B | 16,211 B | 16,633 B |
| 20 | 238.507 ms | 233.929 ms | 330.193 ms | 711,680 B | 59,740,160 B | 18,878 B | 16,217 B | 16,639 B |

All nine serialized outputs were byte-identical within every cohort. The large
latency increase relative to PR138 is the cost of PR139's new deterministic
resolution, structured retrieval, evidence closure, sanitization, validation, and
serialization contract; it is not attributed to the scripted provider. The bounded
selector makes prompt size nearly constant between five and twenty findings, and the
twenty-finding PR139 prompt is 83.8% smaller than the equivalent PR138 full-snapshot
prompt. This comparison does not claim a causal optimization: PR139 performs a
strictly larger operation and returns a much richer result envelope.

## Large-count metadata bound

The large-count test constructs one retained fact and records metadata declaring
1,000,000 total and 999,999 omitted items. It deliberately does not construct,
search, or traverse one million candidates. Its serialized context is 1,439 bytes.
A separate 1,000-iteration serialization measurement recorded a 0.471 ms median,
0.485 ms p95, 0.859 ms maximum, and a 257,088-byte Python allocation peak. This
proves that omitted-count metadata is constant-size; it is not a one-million-node
graph latency benchmark.

## Snapshot compatibility

PR139 reads normal semantic snapshots and does not publish chat data into them. A
controlled repository analyzed from fresh state by both the PR138 baseline and PR139
produced an identical 138,998-byte snapshot with SHA-256
`0f0bedfeb886433ed72946da00cd77fcd2d87bf0a6101bad15b8d07ee00354fa`.
Snapshot growth is therefore zero bytes (0%).

PR137 refactoring output was also rendered from the same Maven snapshot by PR138 and
PR139 code. Both outputs were 2,677 bytes with SHA-256
`7d2aea37c39887efb8bf90db9ff7009fa47a406a78ecfad0704c0101c3e2763e`.

## Interpretation and limitations

- The scripted provider isolates Atlas overhead; it does not predict remote-model
  latency.
- Process peak working set includes interpreter and imported-module cost.
- The zero/few/many cohorts are controlled fixtures, not claims about vulnerability
  prevalence in the benchmark repositories.
- Context construction remains bounded, but Python latency is material. Future work
  should profile the existing resolver and structured-search path before considering
  caching; PR139 does not introduce a speculative cache.
- Ordinary analysis snapshot size is unchanged because conversation state remains in
  the existing workspace-local memory store.
