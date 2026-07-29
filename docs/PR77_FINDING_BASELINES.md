# PR77 — Finding Baselines

PR77 lets teams accept current findings and report only newly introduced issues.
The feature is language-neutral and works with any analyzer that returns a
`findings` array.

## Capture

```text
atlas analyze . --write-baseline .atlas/findings-baseline.json
```

The baseline uses atomic replacement, a schema version, a SHA-256 envelope
checksum, sorted unique fingerprints, and a timezone-aware creation timestamp.

## Compare

```text
atlas check . --baseline .atlas/findings-baseline.json
atlas check . --baseline .atlas/findings-baseline.json --format sarif
```

Existing findings are removed from the reported result. New findings remain in
their deterministic analyzer order. JSON values also include per-project
`new_count` and `existing_count` baseline metadata.

## Fingerprints

If a finding provides a non-empty `fingerprint`, Atlas combines it with the
project identity. Otherwise Atlas hashes these normalized fields:

- project
- rule ID
- path
- line and column
- message

This prevents identical-looking findings in different projects from colliding.
Paths normalize Windows separators to `/`.

The standalone API is available from `moughorai.finding_baseline` through
`FindingBaselineService`, `FindingBaselineStore`, and immutable baseline and
comparison models.
