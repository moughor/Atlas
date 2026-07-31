# PR132 Design — Risk and Hotspot Analysis

PR132 joins existing complexity, canonical fan-in/fan-out, PR129 ownership, Git churn
and change frequency, structured size, and resolved test-density evidence. It does
not build another graph or interpret missing test mapping as zero tests.

Raw values retain units, window, cohort, producer, coverage, and evidence. Normalize
by deterministic percentile within comparable language/kind/scope cohorts; cohorts
under 20 use documented absolute bands and low-coverage labeling.

Default risk:

`0.25 complexity + 0.20 fan-in + 0.15 fan-out + 0.15 churn/change frequency +
0.10 ownership concentration + 0.10 low test density + 0.05 size`.

Only available metrics participate and weights renormalize. Confidence remains
separate. Ties use canonical ID; top-k/hotspot reports expose raw/normalized factors,
rank, trend, confidence, and limitations.

Degree collection is `O(V+E)` and ranking `O(V log k)`; no unbounded all-pairs
centrality. AI receives score, cohort, factors, evidence, and missing signals and must
say “risk indicator,” not “bug.” Tests cover formula/missing values, cohorts, ties,
generated/test scopes, ownership ambiguity, absent test mapping, shuffled inputs,
incremental Git, exact round-trip, JUnit, and scale. Predictive ML and developer
performance scoring are deferred.
