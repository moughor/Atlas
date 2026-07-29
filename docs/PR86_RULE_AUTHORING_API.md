# PR86 Rule Authoring API

Rules implement a small protocol:

```python
class TodoRule:
    rule_id = "ATLAS-TODO"
    default_severity = RuleSeverity.LOW

    def analyze(self, context, reporter):
        if "TODO" in context.source:
            reporter.report("TODO marker", line=1, column=1)
```

`RuleContext` supplies the source path, text, language, and resolved
configuration. `RuleReporter` binds findings to the current rule and validates
one-based source locations, severity, message, and sorted properties.

`RuleRunner` orders rules and findings deterministically, removes exact
duplicates, rejects duplicate IDs, and attributes analyzer exceptions.
`RuleRegistry` provides conflict-safe registration and execution.

PR86 deliberately contains only the runtime authoring contract. PR87 adds the
test harness, PR88 adds rich metadata, and PR89 adds fixes.
