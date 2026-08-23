# Fire Strike Scoring V1

## Scope

`calculate_fire_strike_score` is Atlas Benchmark Intelligence's deterministic
Fire Strike Standard calculator for three positive integral component scores:

- Graphics score, in marks;
- Physics score, in marks;
- Combined score, in marks.

It returns an immutable `FireStrikeScoreCalculationV1` containing the exact
normalized inputs, calculated overall score, benchmark identity, method
identity, unit, schema version, rounding policy, canonical serialization, and
canonical SHA-256.

The calculator is a pure offline derivation. It performs no acquisition,
parsing, filesystem access, networking, persistence, or external-calculator
call.

## Formula

UL publishes the Fire Strike overall score as the weighted harmonic mean of
Graphics, Physics, and Combined scores, with weights `0.75`, `0.15`, and
`0.10` respectively:

```text
raw overall = 1 / (0.75 / graphics + 0.15 / physics + 0.10 / combined)
```

PR150 evaluates the equivalent expression using exact integer arithmetic:

```text
numerator   = 20 * graphics * physics * combined
denominator = 15 * physics * combined
            +  3 * graphics * combined
            +  2 * graphics * physics
overall     = numerator // denominator
```

This has no binary floating-point or Decimal-context boundary. Python's
arbitrary-precision integers preserve the exact quotient before the explicit
floor operation.

Method identity:

```text
scoring:ul:3dmark:fire-strike-standard:integral-components-v1
```

Rounding policy:

```text
floor-weighted-harmonic-mean
```

## Rounding evidence and limitation

UL's support prose says Fire Strike scores are rounded to the nearest integer.
Observed result behavior does not follow that wording for displayed integral
component scores.

Across 24 inspected public UL Fire Strike Standard results, flooring the exact
weighted harmonic mean of the displayed component scores matched every
displayed overall. Conventional nearest-integer rounding disagreed for 10 of
those results. The authorized PR149 capture is a decisive example:

```text
Graphics  22447
Physics   56270
Combined   7668

exact weighted harmonic value  20358.734616...
Atlas floor                     20358
UL displayed overall            20358
nearest integer                 20359
```

The public Elmor calculator independently uses integral component inputs and
floors the weighted harmonic result. It is corroboration only: Atlas does not
copy its code, depend on it at runtime, or treat it as authority for benchmark
identity or validity.

The method name and rounding field deliberately identify this observed
integral-component presentation behavior. PR150 does not claim that UL's prose
has been reconciled, or that displayed component scores preserve hidden FPS or
intermediate precision.

## Input contract

Accepted inputs are exact positive integral values supplied as:

- Python `int` values other than booleans;
- strict finite decimal strings;
- finite `Decimal` values whose numeric value is integral.

Equivalent values such as `22447`, `"22447.0"`, and `Decimal("22447.00")`
produce the same canonical result. Strings do not accept whitespace, signs,
grouping, exponent notation, Unicode digits, or non-finite values. Binary
floating-point is rejected. Fractional, zero, and negative values are rejected.

Zero is not converted to an overall score. It represents an unavailable input
for the reciprocal formula, rather than observed zero performance.

## Authority and interpretation

The result is an Atlas deterministic derivation from caller-supplied component
scores. It is not observed source evidence and does not mutate or replace any
`FieldEvidenceV1`.

A matching calculated overall does not establish:

- UL result validity;
- driver approval;
- HWBOT eligibility;
- benchmark stability;
- same-run linkage between sources;
- full-precision formula reconciliation;
- hardware performance, safety, or tuning headroom.

The benchmark identity remains exactly Fire Strike Standard. The method is not
admitted for Extreme, Ultra, Custom, stress tests, unknown variants, or missing
or conflicting component evidence.

## Explicit exclusions

PR150 does not calculate component scores from FPS, ingest submissions, select
evidence alternatives, compare sources, solve component targets, model
hardware, call Elmor, implement formulas for other variants, provide a CLI or
web UI, or add an Atlas Platform contract.
