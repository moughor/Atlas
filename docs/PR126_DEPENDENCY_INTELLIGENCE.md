# PR126 — Dependency Intelligence

Atlas now normalizes declared dependencies from Maven `pom.xml`, Gradle Groovy
and Kotlin scripts, `requirements.txt`, Poetry `pyproject.toml`, npm
`package.json`, and Cargo `Cargo.toml`.

Each deterministic record contains ecosystem, package coordinate/name, declared
version, scope, optionality, and manifest path. Parsers use Python standard
library formats and regular expressions; Atlas never executes package managers
or build scripts.

Dependencies are persisted through workspace recovery and published in
`semantic_context.dependencies`. Invalid manifests are isolated and do not
abort source analysis.
