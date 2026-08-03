from __future__ import annotations

from .models import SearchCapabilityState, SemanticSearchResponse


def render_semantic_search(
    response: SemanticSearchResponse,
    *,
    explain_score: bool = False,
) -> str:
    """Render one deterministic, source-free human search response."""

    interpretation = response.interpretation
    lines = [
        f"query: {interpretation.normalized_query}",
        "intent: " + ", ".join(item.value for item in interpretation.intents),
        f"results: {len(response.hits)} of {response.total_candidate_count}",
        f"omitted: {response.omitted_count}",
    ]
    if interpretation.concepts:
        lines.append("concepts: " + ", ".join(interpretation.concepts))
    if interpretation.alternatives:
        lines.append("alternatives: " + ", ".join(interpretation.alternatives))
    lines.append("")
    if not response.hits:
        lines.append("No matching structured semantic evidence.")
    for number, hit in enumerate(response.hits, start=1):
        scope = f" [{hit.project}]" if hit.project else ""
        lines.extend((
            f"{number}. {hit.display_name}{scope}",
            f"   {hit.kind.value} | score={hit.score:.4f} | confidence={hit.confidence.tier.value}",
            f"   id: {hit.canonical_subject_id}",
            f"   qualified: {hit.qualified_name}",
        ))
        if hit.matched_concepts:
            lines.append("   concepts: " + ", ".join(hit.matched_concepts))
        if hit.source_classifications:
            lines.append(
                "   source scope: " + ", ".join(hit.source_classifications)
            )
        if hit.relationships:
            lines.append("   relationships: " + ", ".join(hit.relationships))
        if hit.capability_sources:
            lines.append("   sources: " + ", ".join(hit.capability_sources))
        if hit.risk:
            lines.append(
                "   risk: " + ", ".join(
                    f"{key}={value}" for key, value in hit.risk
                )
            )
        lines.append(f"   evidence: {len(hit.evidence_ids)}")
        if hit.limitations:
            lines.append("   limitations: " + " ".join(hit.limitations))
        if explain_score:
            lines.append("   score components:")
            lines.extend(
                "     " + (
                    f"{item.name}: value={item.value:.4f}, "
                    f"weight={item.weight:.4f}, contribution={item.contribution:.4f}, "
                    f"available={'yes' if item.available else 'no'}"
                )
                for item in hit.score_components
            )

    relevant_capabilities = _relevant_capabilities(response)
    degraded = tuple(
        item for item in response.capabilities
        if item.state is not SearchCapabilityState.AVAILABLE
        and item.name in relevant_capabilities
    )
    if degraded:
        lines.extend(("", "Capability limits:"))
        for capability in degraded:
            detail = " ".join(capability.limitations)
            suffix = f" — {detail}" if detail else ""
            lines.append(f"- {capability.name}: {capability.state.value}{suffix}")
    if response.limitations:
        lines.extend(("", "Search limitations:"))
        lines.extend(f"- {item}" for item in response.limitations)
    return "\n".join(lines).rstrip() + "\n"


def _relevant_capabilities(response: SemanticSearchResponse) -> set[str]:
    names = {"canonical_graph", "canonical_identity", "structured_symbols"}
    concepts = set(response.interpretation.concepts)
    if concepts.intersection({"design_pattern", "builder_pattern", "strategy_pattern"}):
        names.add("design_patterns")
    if concepts.intersection({"dead_code", "entry_point"}):
        names.add("reachability")
    if "framework_extension" in concepts:
        names.add("reachability")
    if "risk_hotspot" in concepts:
        names.add("risk_analysis")
    if concepts.intersection({
        "authentication", "authorization", "rest_endpoint", "repository",
        "sql", "orm", "scheduling", "caching", "messaging", "kafka",
        "dependency_injection", "logging", "security", "serialization",
        "background_job", "configuration", "event_listener", "transaction",
    }):
        names.add("frameworks")
    if any(item.startswith("architecture") for item in concepts):
        names.add("architecture")
    if response.request.module or dict(response.interpretation.filters).get("module"):
        names.add("module_scope")
    if response.interpretation.relation is not None:
        names.add(f"relation.{response.interpretation.relation.value}")
    return names
