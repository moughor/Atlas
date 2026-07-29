# PR91 SARIF 2.1.0

`SarifExporter` converts a `WorkspaceRunReport` into deterministic SARIF 2.1.0
data or JSON. Runs include Atlas 1.0 tool identity, Unicode code-point columns,
invocation success, requested projects, and analysis order.

Findings support direct or nested locations, normalized properties, severity
mapping, explicit or generated stable fingerprints, and optional replacement
fixes. Results are sorted by location and rule.

Supplying a PR88 `RuleCatalog` enriches descriptors with titles, descriptions,
default severity, category, tags, languages, enablement/deprecation, and help
URLs. Catalog rules without findings remain in the tool descriptor.

`validate_sarif` enforces the Atlas structural contract. The PR76 CLI `sarif`
format now uses this exporter without changing its invocation.
