# PR123 Release Notes

PR123 scopes global Java symbol identity by workspace project. Identical
default-package and fully qualified type names can coexist across independent
projects, while duplicates inside one project remain errors with both source
paths in the diagnostic.

Legacy unscoped IDs and lookups remain compatible. Snapshots, recovery,
persistence, source indexes, and concurrent access preserve project identity.
Gradle modules declared in `settings.gradle` or `settings.gradle.kts` are
discovered without executing Gradle, and nested module trees are assigned to
their most specific project.
