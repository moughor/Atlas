'''Concise deterministic renderers for PR175 agent artifacts.'''

from __future__ import annotations

from moughorai.story_planning import StoryRequirementStatus

from .models import AgentContextPackage, AgentGraphProjection


def render_agent_context(package: AgentContextPackage) -> str:
    if not isinstance(package, AgentContextPackage):
        raise TypeError('agent context renderer requires an AgentContextPackage')
    story = package.story
    repository = package.repository_identity
    lines = [
        '# Atlas Agent Context',
        '',
        '## Story',
        '',
        str(story['normalized_text']),
        '',
        f"Story fingerprint: `{story['fingerprint']}`",
        f"Context fingerprint: `{package.context_fingerprint}`",
        '',
        '## Repository identity',
        '',
        f"- Snapshot: `{repository['snapshot_id']}`",
        f"- Workspace fingerprint: `{repository['workspace_fingerprint']}`",
        f"- Analyzer: `{repository['analyzer_version']}`",
        f"- Authoritative project: `{package.authoritative_project}`",
        f"- Selected subject: `{package.selected_subject}`",
        '',
    ]
    if package.version >= 2:
        lines.extend(('## Discovered roots', ''))
        authoritative = tuple(
            item for item in package.discovered_roots
            if item.classification == 'resolved'
        )
        candidates = tuple(
            item for item in package.discovered_roots
            if item.classification == 'candidate'
        )
        lines.extend(('### Authoritative / resolved roots', ''))
        _append_roots(lines, authoritative)
        lines.extend(('', '### Candidate / uncertain roots', ''))
        _append_roots(lines, candidates)
        lines.append('')
    lines.extend(('## Primary implementation surface', ''))
    _append_references(lines, package.primary_implementation_surface)
    lines.extend(('', '## Important collaborators', ''))
    _append_references(lines, package.important_collaborators)
    lines.extend(('', '## Impact', ''))
    impact = package.impact_summary
    lines.append(
        '- Represented upstream consumers: '
        f"{impact['included_count']} included, {impact['omitted_count']} omitted."
    )
    for item in impact['subjects']:
        lines.append(
            f"- `{item['qualified_name']}` — depth {item['depth']}, "
            f"{item['confidence']} — `{item['source_ref']}`"
        )
    if not impact['subjects']:
        lines.append('- No represented upstream consumer was projected.')

    lines.extend(('', '### Represented callers', ''))
    _append_references(lines, package.represented_callers)
    lines.extend(('', '### Represented callees', ''))
    _append_references(lines, package.represented_callees)

    lines.extend(('', '## Represented tests', ''))
    lines.append(
        'Represented TEST reachability is inspection guidance, not runtime coverage.'
    )
    _append_references(lines, package.represented_tests)

    lines.extend(('', '## Requirement reconciliation', ''))
    for requirement in package.requirement_reconciliation:
        lines.append(
            f"- **{requirement['id']} — {requirement['status']}**: "
            f"{requirement['text']}"
        )
        linked = requirement['linked_subjects']
        if linked:
            lines.append('  - Repository anchors: ' + ', '.join(
                f'`{item}`' for item in linked
            ))
        if requirement['uncertainty']:
            lines.append('  - Uncertainty: ' + requirement['uncertainty'][0])

    lines.extend(('', '## Remediation / operational work', ''))
    if package.remediation_operational_work:
        for item in package.remediation_operational_work:
            lines.append(f"- {item['id']} — {item['status']}: {item['text']}")
    else:
        lines.append('- None explicitly supplied by the story.')

    lines.extend(('', '## Uncertainty', ''))
    if package.uncertainty:
        lines.extend(f'- {item}' for item in package.uncertainty)
    else:
        lines.append('- No additional bounded uncertainty was projected.')

    lines.extend(('', '## Recommended investigation order', ''))
    for item in package.recommended_investigation_order:
        location = f" — `{item['source_ref']}`" if item.get('source_ref') else ''
        lines.append(
            f"{item['order']}. {item['action']}{location}"
        )

    lines.extend(('', '## Validation guidance', ''))
    commands = package.validation_guidance['commands']
    if commands:
        for command in commands:
            rendered = ' '.join(_shell_display(item) for item in command['argv'])
            lines.append(f"- `{rendered}` ({command['reason']})")
    else:
        lines.append('- Select validation manually; no bounded command was derived.')
    for limitation in package.validation_guidance['limitations']:
        lines.append(f'- Note: {limitation}')

    lines.extend(('', '## Graph files', ''))
    graph = package.graph_artifacts
    lines.extend((
        f"- Machine projection: `{graph['json']}`",
        f"- Mermaid projection: `{graph['mermaid']}`",
        f"- Graph tier: `{graph['depth']}`",
        f"- Graph fingerprint: `{graph['fingerprint']}`",
        f"- Nodes: {graph['node_count']}; edges: {graph['edge_count']}",
    ))
    omitted = graph['omitted_counts']
    lines.append('- Omitted counts: ' + ', '.join(
        f'{key}={value}' for key, value in sorted(omitted.items())
    ))

    lines.extend(('', '## Instructions for external coding agent', ''))
    instructions = [
        '- Treat Atlas canonical identities, project ownership, resolved call '
        'relationships, and represented TEST identities as authoritative repository guidance.',
        '- Investigate PARTIAL and NOT_PROVEN requirements from source before editing.',
        '- Candidate edges are not resolved dependencies.',
        '- Represented TEST reachability is not runtime coverage.',
        '- Do not modify unrelated modules without explaining why.',
        '- Use Atlas-selected tests as the first validation set.',
    ]
    if package.version >= 2:
        instructions.insert(
            2,
            '- Start with Atlas ranked roots. Investigate candidate roots from source '
            'before treating them as implementation targets.',
        )
    lines.extend(instructions)
    return '\n'.join(lines).rstrip() + '\n'


def render_agent_graph_mermaid(graph: AgentGraphProjection) -> str:
    if not isinstance(graph, AgentGraphProjection):
        raise TypeError('Mermaid renderer requires an AgentGraphProjection')
    identifiers = {
        item.id: f'N{index:03d}'
        for index, item in enumerate(graph.nodes, start=1)
    }
    lines = ['flowchart LR', '']
    requirement_status = {
        str(item['id']): str(item['status']) for item in graph.requirements
    }
    for node in graph.nodes:
        label = node.simple_name
        if node.kind == 'requirement':
            requirement_id = node.simple_name
            label = f'{requirement_id} — {requirement_status.get(requirement_id, "NOT_PROVEN")}'
        elif node.kind not in {'story', 'project'}:
            label = f'{node.simple_name} — {node.role}'
        lines.append(f'  {identifiers[node.id]}["{_mermaid_text(label)}"]')
    if graph.edges:
        lines.append('')
    for edge in graph.edges:
        source = identifiers.get(edge.source)
        target = identifiers.get(edge.target)
        if source is None or target is None:
            continue
        label = _edge_label(edge.type, edge.status)
        connector = '-.->' if edge.type in {
            'story_requirement_relation', 'possible_call_target',
            'possible_dispatch_target', 'reverse_upstream',
            'forward_test_reachability',
        } else '-->'
        lines.append(
            f'  {source} {connector}|{_mermaid_text(label)}| {target}'
        )
    return '\n'.join(lines).rstrip() + '\n'


def _append_references(lines: list[str], values) -> None:
    if not values:
        lines.append('- None projected.')
        return
    for item in values:
        source = item.get('source_ref')
        location = f' — `{source}`' if source else ''
        role = f" ({item['role']})" if item.get('role') else ''
        edge = f" [{item['edge_type']}]" if item.get('edge_type') else ''
        lines.append(
            f"- `{item['qualified_name']}`{role}{edge} — "
            f"`{item['id']}`{location}"
        )


def _append_roots(lines: list[str], values) -> None:
    if not values:
        lines.append('- None discovered.')
        return
    for item in values:
        start = item.source_span['start']
        end = item.source_span['end']
        source_ref = (
            f"{item.source_path}#L{start['line']}C{start['column']}"
            f"-L{end['line']}C{end['column']}"
        )
        lines.append(
            f"{item.rank}. `{item.qualified_name}` — `{item.canonical_subject_id}`"
        )
        lines.append(
            f"   - Project: `{item.project}`; confidence: `{item.confidence}`; "
            f"authority: `{item.authority}`"
        )
        lines.append(f"   - Source: `{source_ref}`")
        if item.matched_anchors:
            lines.append(
                '   - Story anchors: '
                + ', '.join(f'`{anchor}`' for anchor in item.matched_anchors)
            )
        if item.discovery_rationale:
            lines.append(f'   - Rationale: {item.discovery_rationale[0]}')


def _edge_label(edge_type: str, status: str | None) -> str:
    labels = {
        'resolved_direct_call': 'resolved call',
        'constructor_call': 'constructor call',
        'possible_call_target': 'candidate call',
        'possible_dispatch_target': 'candidate dispatch',
        'method_reference': 'method reference',
        'reverse_upstream': 'upstream impact',
        'forward_test_reachability': 'represented TEST reachability',
        'project_ownership': 'owns',
        'story_requirement_relation': 'requirement',
    }
    base = labels.get(edge_type, edge_type.replace('_', ' '))
    return f'{base} {status}' if status else base


def _mermaid_text(value: str) -> str:
    return ' '.join(value.replace('"', "'").replace('|', '/').split())[:160]


def _shell_display(value: str) -> str:
    if any(character.isspace() for character in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value
