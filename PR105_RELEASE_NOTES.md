# PR105 Release Notes

PR105 introduces the versioned `moughorai.public_api` facade for external Atlas
consumers. The curated boundary re-exports existing objects without wrappers,
preserving type identity and all legacy import paths.

A deterministic constructor-signature manifest and compatibility checker make
accidental removals and incompatible signature changes visible in CI.
