# PR114 — Explain Engine

The Explain Engine consumes an immutable ASS artifact, builds a grounded PR109
request, calls a PR107 provider, returns Markdown, and optionally records the
question and explanation in PR113 conversation memory.

`atlas ai explain ROOT [--subject SUBJECT]` now executes this pipeline. The
provider never receives raw source from the engine; ASS remains authoritative.
