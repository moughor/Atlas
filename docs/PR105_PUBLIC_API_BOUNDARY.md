# PR105 — Public API Boundary

Atlas embedders should import compatibility-guaranteed symbols from
`moughorai.public_api`. Existing module imports remain available, so this
boundary is backwards compatible; other modules are considered internal or
provisional unless separately documented.

The facade starts at `PUBLIC_API_VERSION = "1.0"` and covers core workspace
models and orchestration, analysis requests/results, persistent indexing, rule
authoring, and plugin integration primitives. `PUBLIC_API_SIGNATURES` is the
frozen constructor contract. CI compares it with `public_api_manifest()` so a
removal or signature change requires an explicit compatibility decision.

Compatible changes may add exports or optional parameters. Removing or
renaming an export, changing required parameters, or changing documented
behavior requires a major public API version. Deprecations must remain for at
least one minor release and emit `DeprecationWarning` before removal.
