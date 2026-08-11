# PR155: Multi-capability grounding and delivered-answer truth

## Decision

Atlas preserves the PR139 AskResult.grounded contract. That legacy boolean
continues to mean that the selected context, canonical subject requirements, and
every requested optional capability satisfy the existing all-request grounding
rules.

PR155 adds an optional, versioned grounding_summary record to new AskResult
payloads produced by AskEngine. The summary distinguishes:

- whether the original provider response passed the legacy grounding contract;
- whether every claim in the final delivered answer is known to be grounded;
- whether the delivered grounded result covers every requested dimension;
- whether Atlas replaced provider prose with a deterministic fallback;
- which requested deterministic capabilities were delivered or omitted; and
- deterministic per-capability requested, computed, delivered, and grounded
  state.

Legacy payloads without the summary remain readable. The summary schema version
is independent of the chat-context, semantic-snapshot, ASS, and public API v1
schemas.

## Semantics

provider_grounded records the original provider result before fallback.

delivered_answer_grounded concerns only the final answer shown to the user.
Atlas is conservative for arbitrary provider prose: provider content is not
parsed to infer claim-to-capability delivery. A provider answer is treated as
delivered-grounded only when it passes the existing PR139 contract.

For an Atlas-owned deterministic impact fallback, Atlas knows the exact output
scope and verifies that the delivered citations include retained impact
aggregate evidence. Only impact_prediction is marked delivered by that
fallback.

request_complete records whether the final grounded result satisfies the legacy
all-request contract. It is intentionally distinct from delivered-answer
grounding. A mixed impact and refactoring request can therefore be represented
truthfully as:

    provider_grounded = false
    delivered_answer_grounded = true
    request_complete = false
    fallback_used = true
    delivered_capabilities = [impact_prediction]
    omitted_requested_capabilities = [refactoring_advisor]
    legacy grounded = false

The impact answer is safe and grounded; the request is incomplete because Atlas
did not deterministically synthesize refactoring advice.

## Persistence and CLI

No conversation database migration is required. The existing message reference
map retains the legacy citation_status value and adds bounded string references
for delivered-answer grounding, request completeness, fallback use, and
delivered/omitted capability names. Existing rows remain readable.

JSON output preserves every legacy top-level key, including grounded, and adds
the optional nested summary.

Text output distinguishes an unsafe delivered answer from a grounded but
incomplete result. The latter identifies omitted requested dimensions and does
not claim that the delivered deterministic answer is ungrounded.

## Compatibility boundaries

PR155 does not change citation validation, fallback eligibility, fallback
rendering, capability execution, prompt construction, chat-context identity,
conversation storage schema, semantic snapshots, ASS, public API v1, graph
identity, Maven topology, architecture intelligence, or Benchmark Intelligence.

The model does not perform provider-prose entailment analysis. Consequently,
unsupported provider claims remain conservatively ungrounded, and only
Atlas-owned deterministic output receives exact delivered-capability
classification.
