# M2.0 Performance Measurement Validation

Status: implementation candidate validated on 2026-08-03

Atlas baseline: `17ba50864b5fd7dd737eb5a722c823ff9b964d90`

## Decision

M2.0 adds measurement infrastructure only. It does not optimize Atlas, alter the
roadmap, modify an accepted benchmark golden, add a persistent cache, or change the
workspace, graph, snapshot, report, Explain, duplicate-detection, or scheduling
contracts.

The implementation is disabled by default and publishes operational observations only
to a separate versioned sidecar. Semantic comparisons performed below matched exactly
where a successful snapshot existed. The raw ASS envelope is not used as the semantic
gate because its history lineage intentionally changes between runs.

## Runtime and protocol

- OS: Windows 11 `10.0.26200`, AMD64.
- Runtime: CPython 3.12.13.
- Logical CPUs: 24.
- Atlas invocation: bundled Codex Python with the candidate worktree on `PYTHONPATH`.
- Analysis mode unless stated otherwise: fresh `--force --no-recover --workers 1`.
- Profiler producer: `atlas-performance-measurement/1.0`; schema version 1.
- Filesystem cache state: uncontrolled/warm. Portable Atlas code did not attempt to
  flush the operating-system cache.
- M2 observations are inclusive and are not summed as an exclusive pipeline total.

The raw sidecar intentionally omits repository identity and runtime provenance. This
document pairs each retained sidecar digest with its repository revision and execution
mode. Complete environment inventory was captured from `python -m pip freeze`; the
runtime contained 56 distributions and its newline-normalized inventory SHA-256 was
`a7598b385ec63c9c431ddc0153900153963fb0f2bed0997416b708021ceb1a06`.
It included Atlas editable at the baseline above, pytest 9.1.1, Typer 0.27.0,
PyYAML 6.0.3, and jsonschema 4.26.0.

## Overhead cohort

Apache Maven was measured in alternating order. The retained comparable three-sample
cohort was:

| Mode | Samples |
| --- | --- |
| Measurement disabled | 34,035 ms; 36,762 ms; 37,280 ms |
| `--profile` | 37,649 ms; 37,751 ms; 37,735 ms |

The medians are 36,762 ms disabled and 37,735 ms profiled: +973 ms, or **+2.65%**.
The immediately bracketed normal/profile/normal batch was 36,762 / 37,735 / 37,280
ms; comparing its profiled sample with the mean of its two normal neighbors gives
+1.93%. The conservative repeated-median result exceeds the requested 2% target, so
M2.0 does not claim that target as proven.

The measured profiler work explains the small positive cost: 1,271 sampled scopes,
26,691 metric observations, 19,873 observed content-read events with bounded
source-free identity correlation, deterministic aggregation, and an atomic 4,293,917
byte JSON sidecar. Run-to-run filesystem-cache noise is material, as the bracketed
result demonstrates. Single A/B pairs on the larger repositories are therefore
compatibility diagnostics, not standalone overhead baselines.

An additional Maven `--profile-memory` run completed successfully in 28,943 ms. Its
4,144,248-byte sidecar (`9f9628369c078eb5eb52251d510becf124ce8256949168c6c360ccfa6288ff75`)
contained measured RSS, Windows working-set, and commit values for all 1,271 samples.
The maximum sampled RSS/working-set was 247,173,120 bytes and maximum sampled commit
was 234,782,720 bytes. These are scope-boundary maxima, not operating-system peak
claims; the elapsed time is not used as an overhead sample because cache state was not
controlled.

## Apache Maven

- Repository revision: `3e01a12e9eacd2b336f4db786d54e35647ce268c`.
- Result in every observed run: 92 projects, 92 succeeded.
- Deterministic text-output SHA-256: `c0a1651f0c296be88b9c619b6653334c2dc42effb21c6436cc67e7aae23a5f0e`.
- Semantic payload: `c6415b606939812bc58b2b08ddafe75041e7fc4e9228fcd08f60e561999e497f`.
- Portable semantic projection: `a591962406d5f5f784d491e025652aa73043478bbacebe52638052181ec8e1f5`.
- Knowledge graph: `2df64026aed0e7b76ea471dfb9690374f45937b04a0b5655f3f820badaeaae16`.
- Repository report: `c424e5245e1d20bd645da6c41067bc617c40bc2527d5a791a0540d3d8589f37f`.
- Risk analysis: `94e87be3bd79c3866a824e36764ead060ed6debd1ea5a875557a01e261e8ee08`.
- Explain projection: `f479818fa2fac4f22bfba40996f935b479bbbcccf3064464be8dedf3234dc740`.
- Workspace order: `3d747b9bfe7ac27ce8f367ad9287fb43ab1704e2ecfb2a23a8d0fae4230561e6`.
- Latest raw ASS size: 33,715,786 bytes. Its raw digest and snapshot ID vary with
  history lineage; the semantic hashes above remained exact.

The retained default profile sidecar is 4,293,917 bytes with SHA-256
`b4a15ac274b956613111abfb1668ee0ee78f7688d662b5be92ba6df7bedf0b57`.
All 1,271 eligible scopes were sampled. Twenty phases were measured; Explain,
Kotlin, Python, persistence, and recovery were explicitly unavailable because those
producers were not exercised by this command.

Filesystem coverage is explicitly partial: 24,871 directory enumerations, 14,184
metadata lookups, 19,873 content reads, 10,005 observed unique resources, 9,868
repeated reads, 28,639,084 known bytes, and zero untracked reads. The largest inclusive
sample sums were project analysis (15.655 s), Java parsing (13.913 s), repository
summary (8.291 s), inventory (6.248 s), filesystem traversal (4.407 s), and snapshot
construction (2.927 s). These values overlap.

## Recovery-on diagnostic

A separate Maven run used `--force --workers 1 --profile-output
.atlas/measurements/recovery-on.json` with recovery enabled. It completed 92/92 in
257,790 ms. Recovery was measured rather than reported unavailable.

Compared with the no-recovery profile, the run recorded:

| Observation | No recovery | Recovery enabled |
| --- | ---: | ---: |
| Samples | 1,271 | 18,847 |
| Content reads | 19,873 | 950,338 |
| Repeated resource reads | 9,868 | 940,333 |
| Directory enumerations | 24,871 | 788,494 |
| Hashes | 10,005 | 940,470 |
| Sidecar bytes | 4,293,917 | 61,357,307 |

The recovery run recorded 187 recovery scopes and 185 persistence scopes. Persistence
processed 1,730,943,150 bytes and had a 200.073 s inclusive wall-time sample sum. Its
sidecar SHA-256 is
`fade99ed4c090187ec2a5958f208cf9ce10f23f1de5035a37f90a14cdf6562fe`.
This comparison mixes the real recovery mechanism with its measurement and is not a
profiler-overhead estimate.

## Spring Framework

- Actual checkout: `C:\AITest\spring\spring-framework`; the parent directory is a
  three-project wrapper, not the accepted benchmark root.
- Repository revision: `eceebb3077dda9e1b19d73c0398ef022cd91f99c`.
- Normal: 29/29, 95.348 s. Profiled: 29/29, 131.093 s.
- Command stdout was byte-identical: SHA-256
  `57b73ac827d778fd070788d74961d781e56d8a57e603364d7dfc256072f7882b`.
- Semantic payload, portable semantic projection, graph, report, risk, Explain,
  project order, and deterministic-ordering hashes matched exactly.
- Snapshot size in both modes: 146,029,292 bytes.
- Profile sidecar: 1,514,462 bytes; SHA-256
  `66a1e1be31442cfccf70e3f95539b8a151099c89b03bbbfdf4ef16cc927f19bb`;
  414/414 successful samples; exact model and canonical-byte round trip.
- Filesystem observations: 29,803 reads, 11,343 unique resources, 18,460 repeated,
  zero untracked.

The single profile-first/normal-second pair reports +37.49%. It is not attributed
entirely to instrumentation because order and filesystem-cache state were uncontrolled
and no alternating cohort was collected. It remains an honest diagnostic warning.

## Quarkus

- Repository revision: `bbc0853aef94c567bac2cc4a98d51c90fb423648`.
- Normal: 1,442/1,442, 582.731 s. Profiled: 1,442/1,442, 415.331 s.
- Command stdout was byte-identical: 73,572 bytes, SHA-256
  `78d97b8a9added1c36a8947f831bbdb491440a23f3de5ebad032f4f78e0931b7`.
- Semantic payload: `93c4457de9df30992b3afa589cb0800f54da01e503d0bdb1a9297f873a8a9ead`.
- Portable semantic projection: `9297de564e0a091ffc5e497a40ab238ba33ef904e74973fb0af9f51a117d3943`.
- Knowledge graph: `0a0834f8dae5509d9a0b019b2038d982df52e7ed3f609e48937fff7a60aa792f`.
- Repository report: `a810c528ab3033d7450dc524cad036544518b8abbfe00bb6c67913c39a56a2e6`.
- Risk analysis: `2114615c0a28973a2eb4545a1154f3ebd6f856f81c4ef18caa26c91f4299370b`.
- Explain projection: `06fb1bc9bc36ccf11273a90774694a89c2f0a275a3d9148537fedb9e43b7fc86`.
- Workspace order: `da5919e2741e32d054d3d673c071d71ea9b3370ddf6789aea08d3cb09c339f6f`.
- Both snapshots were 358,304,086 bytes; all semantic and ordering gates above
  matched exactly. Raw envelopes differed only in run-specific lineage.

The profile sidecar is 61,837,557 bytes with SHA-256
`fb229b41f4fa20ee40ff6196210253ff7cd989ef226edffe16572c60de682d79`.
It passed the normative Draft 2020-12 schema, exact model round trip, and source-free
checks. All 18,942 eligible scopes were sampled, producing 397,782 metric
observations across 22 measured phases; Explain, Kotlin, persistence, and recovery
were explicitly unavailable. The filesystem ledger recorded 80,999 reads, 31,229
unique resources, 49,770 repeats, 127,853,431 known bytes, and zero untracked reads.
The sidecar is 17.26% of the ASS size, so all-scope capture is itself a material
operational artifact at this scale.

The single pair appears 28.73% faster when profiled. That is environmental/cache
variance, not a profiler speedup, and it cannot establish the 2% target in either
direction.

## Elasticsearch

- Checkout: `C:\b\es`; repository revision:
  `273e03a8a7149170fac16761af3fbf522b52f9fe`. The alternative checkout at
  `C:\AITest\elasticsearch` was not used because it had mass tracked deletions.
- Normal: 545/545, 660.225 s. Profiled: 545/545, 522.606 s.
- Normalized UTF-8 command output was identical: SHA-256
  `80f46778cc950aa2322d981a1400de2ad5cd9000c0c4e5beb6618168c2df5ec8`.
- Semantic payload: `bb0fa2eb03f326b2ffb1c36fc3bd0e9f889ee7d0e2f87e152dc21e1894ddb467`.
- Portable semantic projection: `f01cddf387c693325511a096dfd43b0a4476036e146292dcfd6d12951c47f416`.
- Knowledge graph: `0f06c041c3933c4a6bd0d7cbbd7eb5bb2bc8ababe70e2fb58c881004ba5d07f6`.
- Repository report: `16db65d6477446b76e71d2675a411ee6a38c68bd58fe24b4de26becd35971e0d`.
- Risk analysis: `e0c96448da34e51162cf1522ce61c0481ed0e80988f8cb095abd3f1bb354fb15`.
- Explain projection: `434b3c850746cf82288a2131f1cbfc893c14dc9f7fb6f3f3c814f2a9159ad254`.
- Workspace and analysis order:
  `4395ec3a5341ff79b7ffacd97d85932480391b2469b6883339fe9daae53b4c07`.
- Both snapshots were 544,047,044 bytes. Raw ASS hashes differed because of history
  lineage; every semantic and ordering projection above matched exactly.

The profile sidecar is 24,243,695 bytes with SHA-256
`47104ccfc85fde61d50eaa66cfa152f69ae786d39985b38516e5451a83cedde3`.
It passed the normative schema, exact model/canonical-byte round trip, and source-free
scan. All 7,394 eligible scopes were sampled, producing 155,274 metric observations
across 21 measured phases. The filesystem ledger recorded 109,972 reads, 46,215
unique resources, 63,757 repeats, 444,758,270 known bytes, and zero untracked reads.
Java parsing was the largest inclusive phase sample sum at 328.781 s; repository
summary followed at 53.683 s. These values overlap and are not an exclusive total.

The profiled run appears 20.84% faster. As with Quarkus, this single sequential pair
is cache/noise-confounded and does not establish profiler overhead. Both commands
reported this pre-existing benchmark-source warning exactly:

```text
C:\b\es\x-pack\plugin\sql\connectors\tableau\tdvt\tdvt_run.py:150:
SyntaxWarning: invalid escape sequence '\.'
  if re.match("^Tableau 202[0-9]\.[0-9]$", dirname):
```

## IntelliJ Community diagnostic

- Repository revision: `6affce35cb2aad82747b36e886836c44e0188e46`.
- Both modes discovered 119 projects: 118 succeeded and the root `idea` project
  failed with the accepted duplicate
  `com.intellij.testFramework.TestDataFile` across two legitimate module scopes.
- Normal: 351,221 ms. Profiled: 304,837 ms. The profile result is not interpreted as
  a speedup because this was a single uncontrolled pair.
- No snapshot existed before or after either run, as required for failed analysis.
- Both command reports had the same project count and success state. Their combined
  stdout/stderr hashes differ because profile summaries are intentionally emitted on
  stderr; focused CLI tests separately verify unchanged stdout.
- The partial-failure sidecar is 2,259,392 bytes with SHA-256
  `fa1c6271120ee47cb8dd1d45b6a2de37815b930138cbf384e9ed013696bd0a12`.
  It contains 665/665 samples and records 49,239 content reads without retaining the
  duplicate type, file names, paths, or source.
- The profiled run is present in normal history but run 14 is marked
  `performance-measurement` and excluded from adaptive scheduling inputs.

## Source-free and schema checks

Retained Maven, Spring, Quarkus, Elasticsearch, and IntelliJ sidecars were checked for literal,
slash-normalized, and encoded checkout roots and common source declarations. No path
or source marker was found. The measurement tests additionally cover rejected
non-portable identifiers, deterministic sampling without retained sampling keys,
strict status/reason combinations, exact `from_dict()` round trips, and formal Draft
2020-12 JSON Schema validation of an emitted report.

Sidecar atomic publication is fail-safe: an existing non-M2 file is not overwritten,
and publication failure cannot change or mask the Atlas command result. Timing data is
recorded in history for observability but is marked in an additive table so adaptive
scheduling never consumes instrumented duration values.

## Test and static validation

The retained focused command was executed after implementation:

```text
python -m pytest -q -p no:cacheprovider --basetemp .pytest_m2_targeted_final tests/test_m2_measurement_core.py tests/test_m2_measurement_cli.py tests/test_m2_measurement_integration.py tests/test_m2_semantic_phase_measurement.py tests/test_pr94_history_database.py
```

Result: **91 passed in 2.14 s**.

The complete Atlas suite was executed exactly once for final validation:

```text
python -m pytest -q -p no:cacheprovider --basetemp .pytest_m2_full_20260803
```

Result: **3,907 passed, 3 skipped in 27.35 s**. Pytest reported no warnings.

Static validation:

```text
python -m compileall -q moughorai tests benchmarks
git diff --check
```

Both commands returned exit code 0. `git diff --check` emitted only Git's Windows
working-copy notices that LF will be replaced by CRLF when Git next touches existing
modified tracked files; it reported no whitespace error.

## First measured optimization candidate

The first candidate for a future controlled optimization experiment is **recovery
checkpoint amplification**. This choice is based only on new M2 measurements: enabling
recovery on Maven increased content-read events by about 47.8 times and exposed 185
persistence captures with about 200 seconds of inclusive persistence time. Code review
traces the measured behavior to per-project durable state capture, which fingerprints
the valid workspace repeatedly.

M2.0 does not change that behavior. A later experiment may evaluate a deterministic
delta or bounded checkpoint strategy only if crash durability, stale-data invalidation,
replay, source-free persistence, and exact semantic outputs remain unchanged.

## Remaining limitations

- The conservative Maven median overhead is 2.65%, above the 2% target.
- Single-pair large-repository timings cannot isolate profiler cost from filesystem
  cache and environmental variance.
- Filesystem counts cover explicit Atlas boundaries, not operating-system I/O.
- Boundary memory samples are not continuous peak-RSS measurements.
- Per-core topology, GIL contention, page faults, storage latency, energy, and OS I/O
  counters remain unsupported.
- Kotlin has no authoritative production analyzer and remains unavailable.
- Resource identity tracking is bounded to 100,000 entries. Consumer-overlap
  construction is quadratic in the number of consumers touching one resource; Atlas
  currently uses a small fixed trusted consumer set.
- Timing samples are observations and make complete sidecar bytes nondeterministic;
  they never participate in semantic identity.
