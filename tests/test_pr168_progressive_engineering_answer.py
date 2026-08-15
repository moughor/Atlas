from __future__ import annotations

import hashlib
import json
import re

from typer.testing import CliRunner

from moughorai import atlas_cli, public_api
from moughorai.engineering_answer import (
    EngineeringAnswerConfiguration,
    EngineeringAnswerService,
    EngineeringAnswerView,
    render_engineering_answer,
)
from moughorai.llm import ScriptedLlmProvider

from test_pr159_java_code_impact import (
    _entry,
    pr159_fixture,
    pr162_high_fanout_fixture,
)
from test_pr161_ambiguous_call_aggregation import pr161_fixture


runner = CliRunner()


def _resolver(fixture):
    names = {
        item.canonical_subject_id: item.identity.normalized_key
        for item in fixture['index'].entries
    }
    return names.get


def _answer(fixture, owner: str, name: str, **configuration):
    entry = _entry(fixture, owner, name)
    result = EngineeringAnswerService.from_snapshot(
        fixture['snapshot']
    ).query(
        entry.canonical_subject_id,
        kind=entry.identity.kind.value,
        project=entry.project_id,
        configuration=EngineeringAnswerConfiguration(**configuration),
    )
    assert result.answer is not None
    return entry, result


def _section(output: str, heading: str, next_heading: str) -> tuple[str, ...]:
    lines = output.splitlines()
    start = lines.index(heading) + 1
    end = lines.index(next_heading, start)
    return tuple(item for item in lines[start:end] if item)


def test_render_modes_are_deterministic_progressive_and_json_neutral(
    pr162_high_fanout_fixture,
) -> None:
    fixture = pr162_high_fanout_fixture
    changed, result = _answer(
        fixture,
        'FanoutTarget',
        'changed',
        max_representatives_per_section=8,
        max_limitation_representatives=3,
        max_inspect_items=12,
    )
    resolver = _resolver(fixture)
    json_before = result.to_json()

    summary = render_engineering_answer(
        result, view=EngineeringAnswerView.SUMMARY,
        name_resolver=resolver,
    )
    detail = render_engineering_answer(
        result, view=EngineeringAnswerView.DETAIL,
        name_resolver=resolver,
    )
    legacy_full = render_engineering_answer(result)
    explicit_full = render_engineering_answer(
        result, view=EngineeringAnswerView.FULL,
        name_resolver=resolver,
    )

    assert legacy_full == explicit_full
    assert result.to_json() == json_before
    assert result.answer.deterministic_hash == hashlib.sha256(
        result.answer.to_json().encode('utf-8')
    ).hexdigest()
    assert summary == render_engineering_answer(
        result, view='summary', name_resolver=resolver,
    )
    assert detail == render_engineering_answer(
        result, view='detail', name_resolver=resolver,
    )
    assert explicit_full == render_engineering_answer(
        result, view='full', name_resolver=resolver,
    )

    answer = result.answer
    assert 'FanoutTarget#changed()' in summary
    assert changed.canonical_subject_id in summary
    assert f'{answer.direct_callers_high_confidence.total_count} high-confidence represented direct callers' in summary
    assert f'{answer.upstream_direct.total_count} direct represented upstream consumers' in summary
    assert f'{answer.upstream_transitive.total_count} transitive represented upstream consumers' in summary
    assert f'{answer.direct_callees_high_confidence.total_count} high-confidence represented direct callees' in summary
    assert f'{answer.direct_test_callers.total_count} direct represented TEST callers' in summary
    assert f'{answer.high_confidence_test_paths.total_count} high-confidence represented TEST paths' in summary
    assert 'Represented TEST reachability is not runtime coverage' in summary
    assert 'Runtime dispatch, reflection, dependency injection' in summary
    assert 'evidence:' not in summary
    assert 'CALLER -> CALLEE=' not in summary
    assert len(summary.splitlines()) <= 60

    inspect = _section(summary, 'INSPECT FIRST', 'LIMITS')
    assert len(inspect) <= 5
    assert all(re.match(r'\d+\. ', item) for item in inspect)
    assert not any('method:' in item for item in inspect)

    assert 'DETAIL REPRESENTATIVES' in detail
    assert 0 < detail.count('evidence=') <= 15
    assert len(detail.splitlines()) < len(explicit_full.splitlines())
    assert 'TRACEABILITY' in explicit_full
    assert 'PR159 input:' in explicit_full
    assert 'deterministic hash:' in explicit_full


def test_summary_prominently_reports_truthful_truncation_and_uncertainty(
    pr159_fixture,
) -> None:
    _changed, result = _answer(
        pr159_fixture,
        'Target',
        'changed',
        max_depth=2,
        max_nodes=3,
        max_representatives_per_section=2,
        max_limitation_representatives=1,
        max_inspect_items=8,
    )
    answer = result.answer
    assert answer is not None
    summary = render_engineering_answer(
        result,
        view=EngineeringAnswerView.SUMMARY,
        name_resolver=_resolver(pr159_fixture),
    )
    uncertainty = {
        item.section_id: item.total_count for item in answer.uncertainty
    }
    external = uncertainty['external_sites']
    unsupported = uncertainty['unsupported_sites']
    method_references = uncertainty['method_references']

    assert 'truncated=true — TRAVERSAL TRUNCATED' in summary
    assert (
        f'At least {answer.upstream_direct.total_count + answer.upstream_transitive.total_count:,} '
        'represented upstream consumers were found before the configured traversal bound.'
    ) in summary
    assert f'{external:,} external' in summary
    assert f'{unsupported:,} unsupported' in summary
    assert f'{method_references:,} method references' in summary
    assert '0 ambiguous' not in summary


def test_summary_exposes_conservative_dependency_sites_without_candidates(
    pr161_fixture,
) -> None:
    _changed, result = _answer(
        pr161_fixture,
        'Target',
        'changed',
        max_representatives_per_section=8,
        max_candidates_per_call_site=1,
        max_inspect_items=12,
    )
    summary = render_engineering_answer(
        result,
        view=EngineeringAnswerView.SUMMARY,
        name_resolver=_resolver(pr161_fixture),
    )

    assert '2 conservative dependency sites (candidate targets unproven)' in summary
    assert 'Conservative represented dependency call site' in summary
    assert 'candidate targets=' not in summary
    assert 'evidence:' not in summary


def test_constructor_summary_has_no_method_only_assumption(
    pr159_fixture,
) -> None:
    constructor = _entry(pr159_fixture, 'Built', '<init>')
    result = EngineeringAnswerService.from_snapshot(
        pr159_fixture['snapshot']
    ).query(
        'demo.Built#<init>', kind='constructor', project='app',
    )
    assert result.answer is not None

    summary = render_engineering_answer(
        result,
        view=EngineeringAnswerView.SUMMARY,
        name_resolver=_resolver(pr159_fixture),
    )
    assert 'Built#<init>()' in summary
    assert 'kind: constructor' in summary
    assert constructor.canonical_subject_id in summary


def test_cli_defaults_to_summary_and_json_stays_complete(
    pr159_fixture, tmp_path, monkeypatch,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    monkeypatch.setattr(
        atlas_cli, '_load_ai_snapshot',
        lambda *_args, **_kwargs: pr159_fixture['snapshot'],
    )

    common = [
        'answer', 'demo.Target#changed', str(tmp_path),
        '--project', 'app', '--limit', '2',
    ]
    summary = runner.invoke(atlas_cli.app, common)
    detail = runner.invoke(atlas_cli.app, [*common, '--detail'])
    full = runner.invoke(atlas_cli.app, [*common, '--full'])
    machine = runner.invoke(atlas_cli.app, [*common, '--json'])
    invalid = runner.invoke(atlas_cli.app, [*common, '--detail', '--full'])

    assert summary.exit_code == 0, summary.output
    assert detail.exit_code == 0, detail.output
    assert full.exit_code == 0, full.output
    assert machine.exit_code == 0, machine.output
    assert invalid.exit_code != 0
    assert 'MORE' in summary.output
    assert 'DETAIL REPRESENTATIVES' not in summary.output
    assert 'DETAIL REPRESENTATIVES' in detail.output
    assert 'PR159 input:' not in summary.output
    assert 'PR159 input:' in full.output
    assert changed.canonical_subject_id in summary.output
    payload = json.loads(machine.output)
    assert payload['answer']['section_priority'] == [
        'subject_identity',
        'upstream_direct_count',
        'upstream_transitive_count',
        'direct_callers',
        'represented_test_summary',
        'direct_callees',
        'conservative_call_groups',
        'uncertainty',
        'representative_paths',
    ]
    assert payload['answer']['traceability']
    assert payload['answer']['direct_callers']['high_confidence']['items']


def test_interactive_views_reuse_selected_subject_and_one_runtime(
    pr159_fixture, tmp_path, monkeypatch,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    monkeypatch.setattr(
        atlas_cli, '_load_ai_snapshot',
        lambda *_args, **_kwargs: pr159_fixture['snapshot'],
    )
    monkeypatch.setattr(
        atlas_cli, '_ai_provider_factory',
        lambda: ScriptedLlmProvider([]),
    )

    result = runner.invoke(
        atlas_cli.app,
        ['ai', 'session', str(tmp_path)],
        input=(
            '/search changed 1\n/use 1\n/answer\n/answer detail\n'
            '/answer full\n/stats\n/exit\n'
        ),
    )
    assert result.exit_code == 0, result.output
    assert f'subject={changed.canonical_subject_id}' in result.output
    assert result.output.count('ATLAS DETERMINISTIC ENGINEERING ANSWER') == 3
    assert 'DETAIL REPRESENTATIVES' in result.output
    assert 'PR159 input:' in result.output
    stats = next(
        json.loads(line) for line in result.output.splitlines()
        if line.startswith('{') and 'runtime_build_count' in line
    )
    assert stats['runtime_build_count'] == 1
    assert stats['component_build_counts'] == {
        'canonical_subject_resolver': 1,
        'java_code_intelligence': 1,
        'semantic_search': 1,
    }
    assert stats['reuse_count'] >= 4


def test_public_api_and_source_safety_remain_unchanged(
    pr159_fixture,
) -> None:
    _changed, result = _answer(pr159_fixture, 'Target', 'changed')
    manifest = public_api.public_api_manifest()
    outputs = tuple(
        render_engineering_answer(
            result,
            view=view,
            name_resolver=_resolver(pr159_fixture),
        )
        for view in EngineeringAnswerView
    )

    assert public_api.public_api_manifest() == manifest
    assert public_api.public_api_compatibility_issues() == ()
    assert all(str(pr159_fixture['root'].resolve()) not in item for item in outputs)
    assert all('class Target {' not in item for item in outputs)
