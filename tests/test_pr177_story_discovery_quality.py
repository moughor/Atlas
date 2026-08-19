from __future__ import annotations

from moughorai.agent_context.discovery import (
    _Candidate,
    _candidate_from_source,
    _diverse_selection,
    _retain_external_anchors,
    _retain_role_candidate,
    extract_story_anchors,
)


STORY = '''
SYGMA-63059 DEV note.
In the project scope left panel add a Topic search field and Search button.
Press Enter to show matching Topics in a grid, one Topic per row, with vertical scrolling.
When a Topic is selected, retrieve Projects and load the selected Project. Reset clears both.
Technical note: Cache<Integer, Topic> cache =
    CacheService.getInstance().getTopicCacheById();
'''


def _source(name: str, project: str, package: str) -> _Candidate:
    return _candidate_from_source({
        'project': project,
        'path': f'{project}/src/main/java/{package}/{name}.java',
        'classification': 'production',
    })


def test_story_anchor_quality_prioritizes_technical_identifiers() -> None:
    first = extract_story_anchors(STORY)
    second = extract_story_anchors(STORY)

    assert first == second
    by_text = {item.text: item for item in first}
    assert by_text['CacheService'].technical_note
    assert by_text['getTopicCacheById'].anchor_type == 'exact_identifier'
    assert by_text['DEV'].anchor_type == 'weak_lexical'
    assert not by_text['DEV'].semantic_search_allowed
    assert by_text['CacheService'].strength > by_text['DEV'].strength
    invocation = next(
        item for item in first
        if item.anchor_type == 'invocation_expression'
        and 'CacheService.' in item.text
    )
    assert 'CacheService.getInstance().getTopicCacheById()' in invocation.text
    assert invocation.provenance == 'technical-note-expression'
    generic_type = next(item for item in first if item.text == 'Cache<Integer, Topic>')
    assert generic_type.anchor_type == 'technical_note'


def _ranked_fixture():
    anchors = extract_story_anchors(STORY)
    desired = (
        'ui', 'service_interface', 'service', 'persistence',
        'domain', 'integration',
    )
    values = (
        _source('PortalBOLeftPanelContent4ScopeProject', 'portal-web', 'gui'),
        _source('IProjectSearchBean', 'mod-utils-client', 'services/search'),
        _source('ProjectSearchBean', 'mod-utils-ejb', 'impl/services/search'),
        _source(
            'ProjectBaseJoinLegalGroupSummary', 'mod-utils-model',
            'domain/business/views',
        ),
        _source('DevMode', 'unrelated-web', 'gui/dev'),
        _source('CareerDevPlan', 'unrelated-model', 'domain/dev'),
    )
    candidates = {}
    for value in values:
        _retain_role_candidate(candidates, value, anchors, desired)
    _retain_external_anchors(candidates, anchors)
    return anchors, candidates, desired


def test_sygma_63059_fixture_selects_diverse_implementation_layers() -> None:
    _, candidates, desired = _ranked_fixture()
    selected, suppressed = _diverse_selection(
        tuple(candidates.values()), desired, 8,
    )
    names = [item.simple_name for item in selected]

    assert names[:3] == [
        'PortalBOLeftPanelContent4ScopeProject',
        'IProjectSearchBean',
        'ProjectSearchBean',
    ]
    assert 'ProjectBaseJoinLegalGroupSummary' in names
    assert 'CacheService' in names
    assert 'getTopicCacheById' in names
    assert not {'DevMode', 'CareerDevPlan'} & set(names)
    assert {item.role for item in selected} >= {
        'ui', 'service_interface', 'service', 'domain', 'external_symbol',
    }
    assert suppressed >= 0


def test_weak_camel_substrings_do_not_create_false_exact_matches() -> None:
    anchors, candidates, desired = _ranked_fixture()

    assert 'DevMode' not in {item.simple_name for item in candidates.values()}
    assert 'CareerDevPlan' not in {
        item.simple_name for item in candidates.values()
    }
    assert next(item for item in anchors if item.text == 'DEV').ambiguity_penalty >= 80
    first, _ = _diverse_selection(tuple(candidates.values()), desired, 8)
    second, _ = _diverse_selection(tuple(candidates.values()), desired, 8)
    assert tuple(item.canonical_id for item in first) == tuple(
        item.canonical_id for item in second
    )


def test_external_technical_concepts_are_preserved_without_fabricated_authority() -> None:
    anchors, candidates, _ = _ranked_fixture()
    external = {
        item.simple_name: item
        for item in candidates.values()
        if item.role == 'external_symbol'
    }

    assert set(external) >= {'CacheService', 'getTopicCacheById'}
    assert all(item.project is None for item in external.values())
    assert all(item.source_path is None for item in external.values())
    assert all(not item.resolved for item in external.values())
    assert all(
        item.authority == 'story-technical-anchor+validated-snapshot-non-resolution'
        for item in external.values()
    )

    local = {}
    represented = _source('CacheService', 'cache-client', 'cache')
    _retain_role_candidate(local, represented, anchors, ('service',))
    _retain_external_anchors(local, anchors)
    assert not any(
        item.role == 'external_symbol' and item.simple_name == 'CacheService'
        for item in local.values()
    )


def test_near_duplicate_roots_from_one_source_are_suppressed() -> None:
    outer = _Candidate(
        'type:outer', 'type', 'example.ProjectPanel', 'ProjectPanel',
        'portal-web', 'portal/ProjectPanel.java', None, 'ui', 500,
    )
    inner = _Candidate(
        'type:inner', 'type', 'example.ProjectPanel.Inner', 'Inner',
        'portal-web', 'portal/ProjectPanel.java', None, 'ui', 490,
    )

    selected, suppressed = _diverse_selection((outer, inner), ('ui',), 2)

    assert tuple(item.canonical_id for item in selected) == ('type:outer',)
    assert suppressed == 1
