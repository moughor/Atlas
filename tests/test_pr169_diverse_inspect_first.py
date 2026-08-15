from __future__ import annotations

from dataclasses import replace

from moughorai.engineering_answer import (
    EngineeringAnswerConfiguration,
    EngineeringAnswerService,
    EngineeringAnswerView,
    render_engineering_answer,
)
from moughorai.engineering_answer.models import (
    EngineeringAnswer,
    EngineeringAnswerItem,
    EngineeringAnswerSection,
    EngineeringAnswerSynthesis,
)
from moughorai.engineering_answer.renderer import _select_summary_inspect

from test_pr159_java_code_impact import _entry, pr159_fixture
from test_pr161_ambiguous_call_aggregation import pr161_fixture


def _answer(fixture, owner: str, name: str) -> EngineeringAnswerSynthesis:
    entry = _entry(fixture, owner, name)
    result = EngineeringAnswerService.from_snapshot(fixture['snapshot']).query(
        entry.canonical_subject_id,
        kind=entry.identity.kind.value,
        project=entry.project_id,
        configuration=EngineeringAnswerConfiguration(
            max_representatives_per_section=8,
            max_limitation_representatives=3,
            max_inspect_items=16,
        ),
    )
    assert result.answer is not None
    return result


def _item(
    reference: str,
    category: str,
    source: str,
    evidence: str,
    *,
    confidence: str = 'high_confidence',
) -> EngineeringAnswerItem:
    return EngineeringAnswerItem(
        reference,
        category,
        confidence,
        source,
        (evidence,),
    )


def _section(
    section_id: str,
    *items: EngineeringAnswerItem,
    total: int | None = None,
) -> EngineeringAnswerSection:
    return EngineeringAnswerSection(
        section_id,
        len(items) if total is None else total,
        tuple(items),
    )


def _diversity_answer(base: EngineeringAnswer) -> EngineeringAnswer:
    shared = _item(
        'method:shared', 'caller', 'src/SharedTest.java:10:1-10:8', 'edge:shared',
    )
    caller_second = _item(
        'method:caller-2', 'caller', 'src/Caller.java:11:1-11:8', 'edge:caller-2',
    )
    duplicate_test = _item(
        'method:shared', 'test', 'src/SharedTest.java:10:1-10:8', 'edge:shared',
    )
    test_unique = _item(
        'method:test-2', 'test', 'src/OtherTest.java:12:1-12:8', 'edge:test-2',
    )
    test_fill = _item(
        'method:test-3', 'test', 'src/ThirdTest.java:13:1-13:8', 'edge:test-3',
    )
    duplicate_upstream = _item(
        'method:shared',
        'upstream',
        'src/Path.java:14:1-14:8',
        'edge:shared',
        confidence='high_confidence_represented_path',
    )
    upstream_unique = _item(
        'method:upstream-2',
        'upstream',
        'src/Upstream.java:15:1-15:8',
        'edge:upstream-2',
        confidence='high_confidence_represented_path',
    )
    dependency = _item(
        'method:subject', 'dependency', 'src/Subject.java:16:1-16:8', 'site:dependency',
        confidence='conservative_call_site',
    )
    hotspot = _item(
        'method:subject', 'unresolved_sites', 'src/Subject.java:17:1-17:8', 'site:unresolved',
        confidence='limitation_evidence',
    )
    return replace(
        base,
        direct_callers_high_confidence=_section(
            'direct_callers_high_confidence', shared, caller_second,
        ),
        direct_test_callers=_section(
            'direct_test_callers', duplicate_test, test_unique, test_fill,
        ),
        upstream_direct=_section(
            'upstream_direct', duplicate_upstream, upstream_unique,
        ),
        upstream_transitive=_section('upstream_transitive'),
        direct_caller_conservative_sites=_section(
            'direct_caller_conservative_sites',
        ),
        direct_callee_conservative_sites=_section(
            'direct_callee_conservative_sites', dependency,
        ),
        uncertainty=(_section('unresolved_sites', hotspot, total=1),),
    )


def test_diverse_selection_uses_two_passes_and_deduplicates_relationships(
    pr159_fixture,
) -> None:
    result = _answer(pr159_fixture, 'Target', 'changed')
    assert result.answer is not None
    answer = _diversity_answer(result.answer)

    selected = _select_summary_inspect(answer, maximum=5)
    assert tuple(item.category for item in selected) == (
        'high_confidence_callers',
        'direct_represented_test_callers',
        'high_confidence_upstream_paths',
        'conservative_dependency_sites',
        'uncertainty_hotspots',
    )
    assert tuple(item.canonical_reference for item in selected) == (
        'method:shared',
        'method:test-2',
        'method:upstream-2',
        'method:subject',
        'method:subject',
    )
    assert sum(item.canonical_reference == 'method:shared' for item in selected) == 1
    assert selected == _select_summary_inspect(answer, maximum=5)

    filled = _select_summary_inspect(answer, maximum=7)
    assert tuple(item.category for item in filled) == (
        'high_confidence_callers',
        'direct_represented_test_callers',
        'high_confidence_upstream_paths',
        'conservative_dependency_sites',
        'uncertainty_hotspots',
        'high_confidence_callers',
        'direct_represented_test_callers',
    )
    assert len(_select_summary_inspect(answer, maximum=0)) == 0


def test_summary_splits_neighborhood_uncertainty_from_workspace_limitations(
    pr159_fixture,
) -> None:
    result = _answer(pr159_fixture, 'Target', 'changed')
    assert result.answer is not None
    hotspot = _item(
        'method:subject', 'unresolved_sites', 'src/Subject.java:20:1-20:8', 'site:20',
        confidence='limitation_evidence',
    )
    uncertainty = (
        _section('unresolved_sites', hotspot, total=20),
        _section('external_sites', total=316),
        _section('unsupported_sites', total=52),
        _section('ambiguous_candidates', total=14),
        _section('possible_dispatch_candidates', total=17),
        _section('method_references', total=6),
        _section('call_extraction_failures', total=3_729),
        _section('callable_bodies_unavailable', total=10_185),
        _section('omitted_callable_diagnostics', total=89_670),
        _section('unindexed_callables', total=1),
        _section('traversal_truncation'),
    )
    answer = replace(result.answer, uncertainty=uncertainty)
    projected = replace(result, answer=answer)

    summary = render_engineering_answer(
        projected, view=EngineeringAnswerView.SUMMARY,
    )
    call_start = summary.index('UNCERTAINTY IN REPRESENTED CALL EVIDENCE')
    workspace_start = summary.index('WORKSPACE ARTIFACT LIMITATIONS')
    inspect_start = summary.index('INSPECT FIRST')
    call_scope = summary[call_start:workspace_start]
    workspace_scope = summary[workspace_start:inspect_start]

    for expected in (
        '20 unresolved', '316 external', '52 unsupported', '14 ambiguous',
        '17 possible dispatch', '6 method references',
    ):
        assert expected in call_scope
        assert expected not in workspace_scope
    for expected in (
        '3,729 call extraction failures',
        '10,185 callable bodies unavailable',
        '89,670 omitted callable diagnostics',
        '1 unindexed callable',
    ):
        assert expected in workspace_scope
        assert expected not in call_scope
    assert 'loaded workspace artifact, not only this subject' in workspace_scope
    assert summary == render_engineering_answer(
        projected, view=EngineeringAnswerView.SUMMARY,
    )
    assert len(summary.splitlines()) <= 60


def test_empty_categories_add_no_inspect_placeholder(pr159_fixture) -> None:
    result = _answer(pr159_fixture, 'Target', 'changed')
    assert result.answer is not None
    caller = _item(
        'method:only', 'caller', 'src/Only.java:1:1-1:2', 'edge:only',
    )
    answer = replace(
        result.answer,
        direct_callers_high_confidence=_section(
            'direct_callers_high_confidence', caller,
        ),
        direct_test_callers=_section('direct_test_callers'),
        upstream_direct=_section('upstream_direct'),
        upstream_transitive=_section('upstream_transitive'),
        direct_caller_conservative_sites=_section(
            'direct_caller_conservative_sites',
        ),
        direct_callee_conservative_sites=_section(
            'direct_callee_conservative_sites',
        ),
        uncertainty=(),
    )
    selected = _select_summary_inspect(answer, maximum=5)
    assert len(selected) == 1
    assert selected[0].canonical_reference == 'method:only'


def test_conservative_dependency_remains_visible_in_summary_and_detail(
    pr161_fixture,
) -> None:
    result = _answer(pr161_fixture, 'Target', 'changed')
    assert result.answer is not None
    model_json = result.to_json()
    model_hash = result.answer.deterministic_hash

    summary = render_engineering_answer(
        result, view=EngineeringAnswerView.SUMMARY,
    )
    detail = render_engineering_answer(
        result, view=EngineeringAnswerView.DETAIL,
    )
    selected = _select_summary_inspect(result.answer, maximum=5)

    assert any(
        item.category == 'conservative_dependency_sites'
        for item in selected
    )
    assert 'Conservative represented dependency call site' in summary
    assert 'candidate targets=' not in summary
    assert 'candidate targets=' in detail
    assert '(not resolved)' in detail
    assert 'evidence=' in detail
    assert result.to_json() == model_json
    assert result.answer.deterministic_hash == model_hash


def test_full_and_json_are_unchanged_while_summary_language_stays_safe(
    pr159_fixture,
) -> None:
    result = _answer(pr159_fixture, 'Target', 'changed')
    json_before = result.to_json()
    legacy_full = render_engineering_answer(result)
    explicit_full = render_engineering_answer(
        result, view=EngineeringAnswerView.FULL,
    )
    summary = render_engineering_answer(
        result, view=EngineeringAnswerView.SUMMARY,
    )

    assert explicit_full == legacy_full
    assert result.to_json() == json_before
    assert 'Represented TEST reachability is not runtime coverage' in summary
    assert 'untested' not in summary.casefold()
    assert 'source body' not in summary.casefold()
    assert 'C:\\' not in summary
