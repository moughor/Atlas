# PR127 Repository Explain Integration Fix

## Investigation

The saved JUnit snapshot contains a complete `repository_summary` with 41
projects, module hierarchy, language counts, build systems, frameworks, entry
points, and dependency totals.

Before this fix, `atlas ai explain` loaded the correct snapshot and included the
summary, but serialized the entire semantic context into a generic prompt. The
13.9 MB JUnit snapshot produced an impractically large prompt in which the
summary could be displaced by provider context limits. No Atlas-side selection
prioritized repository metadata.

## Resolution

Default workspace/repository explanations now use a dedicated source-free
context containing:

- repository summary;
- compact architecture conclusions;
- discovered project count;
- dependency overview from the summary;
- explicit limitations and omitted-detail counts.

The prompt explicitly prioritizes this metadata and requests a direct overview
covering the repository name, projects, hierarchy, languages, build systems,
frameworks, major areas, entry points, dependencies, architecture, and
uncertainty.

Specific-symbol explanations preserve the previous detailed context path.

## Accuracy hardening

Large-repository validation later showed that a compact prompt alone could not
prevent a provider from substituting or inventing facts. The default repository
overview now uses a bounded deterministic projection and renderer and does not
call an LLM. Targeted subject explanations still use the detailed provider path.
The current field contract is documented in
`docs/ATLAS_AI_EXPLAIN_ACCURACY_REVIEW.md`.

## JUnit verification

JUnit workspace validated successfully: 41 discovered projects, including the
root `junit-team` aggregator.

Against that saved snapshot, the selected explanation context contains the
repository summary and project count, excludes detailed symbols, and reduces
the estimate from approximately 57,465 to 7,373 input tokens.

## Related architecture correction

Prompt-budget inspection exposed a PR128 token-matching false positive:
`SupportUtility` matched `port`. Architecture names are now tokenized across
qualified-name and camel-case boundaries, so `PaymentPort` remains evidence
while `Support` does not.
