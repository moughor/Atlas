# PR95 — Dashboard

Generate a portable dashboard from the PR94 historical database:

```text
atlas dashboard .
atlas dashboard . --output reports/atlas.html --limit 50
```

The default output is `.atlas/dashboard.html`. It contains summary metrics,
recent run status, finding counts, and project activity. The document is
self-contained, responsive, accessible, and does not load scripts, fonts, or
styles from the network. Empty databases produce a valid empty-state report.
