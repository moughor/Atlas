# PR88 Rule Metadata

`RuleMetadata` describes an authored rule with validated identity, title,
description, default severity, category, sorted tags/languages, documentation
and reference URLs, default enablement, and deprecation/replacement state.

Attach metadata with:

```python
@rule_metadata(RuleMetadata(...))
class MyRule:
    ...
```

Metadata identity and severity must match the rule runtime fields. Existing
PR86 rules without metadata remain compatible: `metadata_for` synthesizes a
minimal record.

`RuleCatalog` validates unique IDs, sorts entries, serializes deterministically,
and filters by category, tag, language, or deprecation status. PR88 contains no
fix definitions; those begin in PR89.
