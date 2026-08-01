# PR114 — Explain Engine

The Explain Engine consumes an immutable ASS artifact, returns Markdown, and
optionally records the question and explanation in PR113 conversation memory.

The default workspace/repository request prefers the persisted PR133
`repository_report` and renders its deterministic 7,000-token, source-free
projection. The selector retains complete report items and their citations, records
exact omitted counts, and leaves unavailable sections explicit. A snapshot that
predates PR133 continues through the accepted bounded PR127–PR132 fallback, with
machine-specific absolute paths omitted from rendered context.

The default path does not construct or call a provider, so its reported values and
conclusions cannot be altered by LLM output.

`atlas ai explain ROOT --subject SUBJECT` preserves the original targeted path:
it builds a grounded PR109 request and calls the configured PR107 provider. The
provider never receives raw source from the engine; ASS remains authoritative.
