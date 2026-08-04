# PR142 Performance Report

Status: **executed and validated on 2026-08-04**.

This report covers the approved cycle-only PR142 slice. Measurements used Python
3.12.13 on Windows. Repository benchmark wall times were collected while other
validation work was active and are correctness observations only; they are not a
controlled performance-regression cohort.

## Execution shape and bounds

PR142 remains an ephemeral orchestration over existing services:

1. load one checksum-verified semantic snapshot;
2. restore the existing PR134 resolver and PR129 graph;
3. request bounded PR137 verified cycle seams;
4. group equivalent directed seams before impact work;
5. request bounded PR136 represented impact once per retained unique seam;
6. join compatible exact-subject PR132 risk and complexity context;
7. materialize bounded PR130 evidence and confidence, then apply PR142's local
   ordinal ordering and rendering contract.

There is no second graph, cycle detector, impact traversal, repository scan,
source parse, Git query, persistent index, feature cache, or all-pairs operation.
The request bounds are 256 evaluated upstream observations and impact depth 64.
Although the standalone `limit` field ceiling is 1,000, the invariant
`limit <= candidate_limit` makes 256 the effective maximum returned count.
Evidence-backed equivalent advice is capped at six records per item while every
evaluated advice ID and exact omission count remains explicit.

## Controlled request measurements

The retained Maven PR141 snapshot was 33,806,488 bytes. A default zero-observation
request produced 2,551 bytes of canonical JSON and 2,331 bytes of human output.

| Measurement | Observed result |
| --- | ---: |
| Cold unprofiled CLI, including snapshot load and process startup | 1,905.592 ms |
| PR142 restore plus query, seven-run median on a loaded snapshot | 1,684.368 ms |
| Equivalent PR137 cycle-only restore plus query, seven-run median | 1,527.793 ms |
| Repeated query on one already restored PR142 service, ten-run median | 0.794 ms |
| Canonical JSON size | 2,551 bytes |
| Canonical JSON SHA-256 | `e4d8326a858d8088d59a2e68b88f810892b2e67140cff0340af1d626f262b147` |
| Human output size | 2,331 bytes |
| Human output SHA-256 | `3f7a6098f758e735b8b9ca2e11710771a57f393b29841b58635e54b2c7e4b8cc` |

The alternating upstream comparison observed 156.575 ms more median restore/query
time for PR142 on this one zero-candidate snapshot. This is not presented as a
general regression: it includes construction of the existing PR136 index, has one
repository cohort, and excludes snapshot parsing equally from both services. It
does identify eager provider restoration as the dominant zero-candidate cost and a
future optimization point if a second controlled cohort justifies change.

Ten same-service responses and two independent CLI JSON responses were
byte-identical. The retained snapshot SHA-256 remained
`7b727731f28288e56c7bd91926f6e2cecc769a96e48a84905aed35287bc0e02c`
before and after snapshot-only queries.

## Zero, small, medium, and larger observations

The zero case used the retained Maven snapshot and therefore has a different method:
its cold value is an unprofiled CLI process and its repeated value is ten queries on
one already restored service. Positive cases used the deterministic synthetic cycle
construction from the focused tests; their cold values include `tracemalloc` and
their repeated medians are five unprofiled restore-and-query executions. The rows
demonstrate bounded behavior and are not presented as a cross-cohort scaling curve.

| Observations | Evaluated | Returned | Evidence | JSON bytes | Cold observation | Repeated median | Python peak | Deterministic |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | 0 | 0 | 0 | 2,551 | 1,905.592 ms CLI | 0.794 ms restored service | see M2 profile | yes |
| 3 | 3 | 3 | 10 | 26,007 | 50.771 ms | 15.055 ms | 100,016 bytes | yes |
| 12 | 12 | 10 | 33 | 97,001 | 323.207 ms | 101.123 ms | 240,535 bytes | yes |
| 40 | 16 | 10 | 61 | 158,910 | 473.065 ms | 147.340 ms | 381,399 bytes | yes |

The 40-observation case proves that candidate work is bounded before impact:
40 upstream observations, 16 evaluated, and 10 returned. Five repeated outputs at
each positive size had one SHA-256 digest per cohort.

## Filter and limit costs

A 40-observation fixture containing an explicit repository node compared repository
scope with an exact project scope under identical bounds. Nine same-service runs
produced medians of 53.013 ms and 53.068 ms respectively; both retained 5 of 8
evaluated observations from 40 upstream observations. The 0.055 ms difference is
measurement noise, not a causal claim.

Increasing `candidate_limit` from 8 to 16 at `limit=5` and depth 2 increased the
seven-run median from 55.701 ms to 91.616 ms. Keeping 16 candidates and increasing
the result limit from 5 to 10 plus depth from 2 to 4 produced a 140.376 ms median.
The corresponding output sizes were 94,003, 94,007, and 158,910 bytes. These
measurements demonstrate that work and output follow explicit request bounds.

## M2 measurement profile

An opt-in profiled Maven CLI request recorded 13 successful M2 phases. Profiling
with process-memory and Python-allocation collection took 7,416.665 ms and preserved
the exact unprofiled canonical output.

| Phase or metric | Observed result |
| --- | ---: |
| `technical_debt.prepare` | 5,062.051 ms |
| `technical_debt.query` | 4.776 ms |
| `technical_debt.cycle_candidates` | 3.172 ms |
| `technical_debt.impact` | 0.008 ms |
| `technical_debt.render` | 0.228 ms |
| maximum sampled RSS | 378,769,408 bytes |
| maximum Python peak allocated bytes | 172,378,550 bytes |
| measurement sidecar size | 142,820 bytes |

The profiled timings include `tracemalloc` and must not be compared directly with
unprofiled wall times. Queue and idle metrics were explicitly reported unsupported;
missing metrics were not converted to zero.

## Snapshot and persistence impact

Maven, Spring, and Elasticsearch fresh PR142 analyses produced raw `.ass` files
byte-for-byte identical to the retained PR141 artifacts. Maven remained 33,806,488
bytes, Spring remained 146,059,842 bytes, and Elasticsearch remained 546,013,434
bytes. For all three controlled repositories:

- raw snapshot SHA-256 and snapshot identity matched;
- portable semantic, repository-report, risk, graph, and project-order hashes
  matched;
- `semantic_context` had no `technical_debt` key;
- ordinary snapshot growth was exactly **0 bytes / 0.0%**.

Quarkus also retained its 359,125,800-byte snapshot size and all canonical artifact
hashes, with no `technical_debt` key. PR142 adds no durable report, recovery field,
history record, conversation state, alternate index, or cache.

## Scalability observations and limitations

- Snapshot loading and PR134 graph restoration dominate cold zero-candidate cost.
- PR136 work is per retained unique seam; candidate count, traversal depth, result
  limit, visited nodes, and visited edges remain bounded and observable.
- Equivalent seams are grouped before traversal, and PR136 path evidence is reduced
  to one non-reversible fingerprinted adapter rather than copied wholesale.
- Resolver restoration retains the canonical graph and existing indexes; PR142 does
  not materialize a second graph.
- The largest synthetic cohort is a bound test, not an enterprise repository
  performance claim.
- No controlled PR141-versus-PR142 ordinary-analysis timing or memory regression is
  claimed. Concurrent official benchmark wall times establish correctness only.

The measured implementation satisfies the PR142 performance contract without a new
cache or speculative optimization.
