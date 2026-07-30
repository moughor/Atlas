# PR128 Confidence and Evidence Fix

## Scope

This narrow checkpoint corrects architecture confidence, dependency labels,
framework scope, and repository-explanation wording. It does not begin PR129
or change graph ownership.

## Architecture

Architecture name evidence is restricted to package/type and project metadata;
member names no longer establish repository architecture. Layered, clean,
hexagonal, CQRS, event-driven, and plugin conclusions require a semantic
relationship between matched evidence. Microservices require at least two
independently entered projects with server-framework evidence.

Weak findings remain possible, but the prompt must phrase confidence below
0.75 as a possibility. Modular-monolith and microservices evidence, when both
present, produces an explicit conflict requiring deployment-boundary
confirmation.

Dependency direction and cycle claims now include an execution flag and
evidence-edge count. Empty lists do not imply that checks ran.

## Dependencies

Repository summaries distinguish:

- normalized declared dependency records by ecosystem;
- total declared dependency records;
- distinct dependency manifests by ecosystem;
- total distinct dependency manifests.

The legacy `dependencies_by_ecosystem` field remains for compatibility but is
not sent in the default explanation prompt.

## Framework scope

Framework evidence records framework, project, scope, and dependency
coordinate. Scope is either `project-local` or `test-or-sample`, derived only
from project names and workspace-relative paths.

## JUnit validation

JUnit workspace validated successfully: 41 discovered projects, including the
root `junit-team` aggregator.

The regenerated snapshot reports:

- architecture finding: modular monolith, confidence 0.82;
- no microservices, CQRS, or hexagonal finding;
- dependency analysis not executed because no inter-project evidence edges
  were available;
- 35 normalized declaration records across 16 distinct manifests;
- Spring evidence limited to the `documentation` project with
  `test-or-sample` scope.
