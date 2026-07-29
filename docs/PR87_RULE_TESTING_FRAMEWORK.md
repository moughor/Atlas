# PR87 Rule Testing Framework

`RuleTestHarness` executes PR86 rules without requiring a third-party test
framework:

```python
result = RuleTestHarness(TodoRule(), language="python").run("# TODO")
result.assert_count(1).assert_findings((
    ExpectedFinding("ATLAS-TODO", line=1),
))
```

Cases define a name, source, path, language, and sorted configuration.
`run_cases` validates unique names and runs in deterministic name order.

Results support clean/count assertions and exact or subset expected-finding
matching by rule, line, optional column, message, and severity. Assertion
errors include missing and unexpected findings with source locations.
