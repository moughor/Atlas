# PR114 — Explain Engine

The Explain Engine consumes an immutable ASS artifact, returns Markdown, and
optionally records the question and explanation in PR113 conversation memory.

The default workspace/repository request is rendered deterministically from a
bounded, source-free Atlas projection. It does not call the provider, and its
reported values and conclusions therefore cannot be altered by LLM output.

`atlas ai explain ROOT --subject SUBJECT` preserves the original targeted path:
it builds a grounded PR109 request and calls the configured PR107 provider. The
provider never receives raw source from the engine; ASS remains authoritative.
