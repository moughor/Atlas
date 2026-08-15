from __future__ import annotations

import hashlib
import json

from typer.testing import CliRunner

from moughorai import atlas_cli, public_api
from moughorai.ai_ask import (
    AskEngine,
    AskRequest,
    EngineeringChatContextBuilder,
)
from moughorai.code_intelligence import JavaCodeIntelligenceService
from moughorai.engineering_answer import (
    ENGINEERING_ANSWER_PRODUCER,
    EngineeringAnswerConfiguration,
    EngineeringAnswerService,
    render_engineering_answer,
)
from moughorai.llm import (
    LlmClient,
    LlmProviderError,
    RetryPolicy,
    ScriptedLlmProvider,
)
from moughorai.structured_explanation import (
    ExplanationRequest,
    StructuredExplanationService,
)

from test_pr159_java_code_impact import (
    MAIN_SOURCE,
    _entry,
    pr159_fixture,
    pr162_high_fanout_fixture,
)
from test_pr161_ambiguous_call_aggregation import pr161_fixture


runner = CliRunner()


def _synthesis(fixture, owner: str, name: str, **configuration):
    entry = _entry(fixture, owner, name)
    service = EngineeringAnswerService.from_snapshot(fixture['snapshot'])
    result = service.query(
        entry.canonical_subject_id,
        project='app',
        configuration=EngineeringAnswerConfiguration(**configuration),
    )
    assert result.answer is not None
    return entry, service, result, result.answer


def test_exact_method_synthesis_retains_identity_direction_and_bounds(
    pr159_fixture,
) -> None:
    changed, service, first, answer = _synthesis(
        pr159_fixture, 'Target', 'changed',
        max_representatives_per_section=1,
        max_limitation_representatives=1,
        max_candidates_per_call_site=1,
        max_inspect_items=8,
    )
    second = service.query(
        changed.canonical_subject_id,
        project='app',
        configuration=EngineeringAnswerConfiguration(
            max_representatives_per_section=1,
            max_limitation_representatives=1,
            max_candidates_per_call_site=1,
            max_inspect_items=8,
        ),
    )

    assert first.to_json() == second.to_json()
    assert answer.deterministic_hash == hashlib.sha256(
        answer.to_json().encode('utf-8')
    ).hexdigest()
    assert answer.subject.canonical_id == changed.canonical_subject_id
    assert answer.subject.qualified_name == changed.identity.normalized_key
    assert answer.subject.kind == 'method'
    assert answer.subject.project == 'app'
    assert answer.subject.source_ref.startswith('app/')
    assert all(
        item.canonical_target == changed.canonical_subject_id
        for item in answer.direct_callers_high_confidence.items
    )
    assert all(
        item.canonical_source == changed.canonical_subject_id
        for item in answer.direct_callees_high_confidence.items
    )
    assert answer.upstream_direct.total_count > 0
    assert answer.upstream_transitive.total_count > 0
    assert all(item.depth == 1 for item in answer.upstream_direct.items)
    assert all(item.depth > 1 for item in answer.upstream_transitive.items)
    for section in (
        answer.direct_callers_high_confidence,
        answer.upstream_direct,
        answer.upstream_transitive,
        answer.direct_callees_high_confidence,
    ):
        assert section.total_count == section.included_count + section.omitted_count

    payload = answer.to_dict()
    assert payload['schema_version'] == 1
    assert payload['producer_version'] == ENGINEERING_ANSWER_PRODUCER
    assert payload['represented_test_signal']['runtime_test_coverage_proven'] is False
    assert payload['represented_test_signal']['absence_proves_untested'] is False
    rendered = render_engineering_answer(first)
    assert 'CALLER -> CALLEE' in rendered
    assert 'represented TEST reachability is not runtime test coverage' in rendered
    assert 'does not prove this subject is untested' in rendered
    assert 'you should refactor' not in rendered.casefold()
    assert MAIN_SOURCE not in rendered
    assert str(pr159_fixture['root'].resolve()) not in rendered
    assert len(rendered.splitlines()) <= 150


def test_constructor_synthesis_uses_existing_callable_boundary(
    pr159_fixture,
) -> None:
    constructor = _entry(pr159_fixture, 'Built', '<init>')
    result = EngineeringAnswerService.from_snapshot(
        pr159_fixture['snapshot']
    ).query(
        'demo.Built#<init>', kind='constructor', project='app',
    )

    assert result.answer is not None
    assert result.answer.subject.canonical_id == constructor.canonical_subject_id
    assert result.answer.subject.kind == 'constructor'
    assert result.answer.direct_callers_high_confidence.total_count == 1
    assert 'kind: constructor' in render_engineering_answer(result)


def test_conservative_call_groups_remain_sites_not_resolved_dependencies(
    pr161_fixture,
) -> None:
    _changed, _service, result, answer = _synthesis(
        pr161_fixture, 'Target', 'changed',
        max_representatives_per_section=8,
        max_candidates_per_call_site=1,
    )
    groups = answer.direct_callee_conservative_sites

    assert groups.total_count == 2
    assert groups.candidate_projection_count == 16
    assert groups.included_candidate_count == 2
    assert groups.omitted_candidate_count == 14
    assert all(item.canonical_target is None for item in groups.items)
    assert all(item.total_candidate_count == 8 for item in groups.items)
    assert any(
        item.reason.startswith('Conservative represented dependency call site')
        for item in answer.inspect_first
    )
    rendered = render_engineering_answer(result)
    assert 'candidate targets (not resolved)' in rendered
    assert 'not resolved dependencies' in rendered


def test_uncertainty_truncation_and_inspect_first_are_truthful_and_ordered(
    pr159_fixture,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    result = EngineeringAnswerService.from_snapshot(
        pr159_fixture['snapshot']
    ).query(
        changed.canonical_subject_id,
        project='app',
        configuration=EngineeringAnswerConfiguration(
            max_depth=2,
            max_nodes=3,
            max_representatives_per_section=1,
            max_limitation_representatives=1,
            max_inspect_items=12,
        ),
    )
    assert result.answer is not None
    answer = result.answer
    uncertainty = {item.section_id: item for item in answer.uncertainty}

    assert {
        'unresolved_sites',
        'external_sites',
        'unsupported_sites',
        'ambiguous_candidates',
        'possible_dispatch_candidates',
        'method_references',
        'traversal_truncation',
    } <= set(uncertainty)
    assert uncertainty['external_sites'].total_count > 0
    assert uncertainty['unsupported_sites'].total_count > 0
    assert uncertainty['method_references'].total_count > 0
    assert uncertainty['traversal_truncation'].total_count == 1
    assert answer.traversal.truncated is True
    assert any(
        item.startswith('At least ') for item in answer.change_risk_summary
    )
    rank = {
        'Direct high-confidence represented caller': 1,
        'Direct represented TEST caller': 2,
        'High-confidence represented upstream path': 3,
        'Conservative represented caller site; candidate targets remain unproven': 4,
        'Conservative represented dependency call site; candidate targets remain unproven': 4,
    }
    observed = [
        rank.get(item.reason, 5) for item in answer.inspect_first
    ]
    assert observed == sorted(observed)
    assert [item.priority for item in answer.inspect_first] == list(
        range(1, len(answer.inspect_first) + 1)
    )
    assert all(item.source_ref and item.evidence_ids for item in answer.inspect_first)

    rendered = render_engineering_answer(result)
    assert 'were found before the configured traversal bound' in rendered
    assert 'truncated=true' in rendered
    assert 'external_sites: total=' in rendered
    assert 'unsupported_sites: total=' in rendered


def test_negative_test_signal_never_claims_coverage_or_untested(
    pr159_fixture,
) -> None:
    target = _entry(pr159_fixture, 'ReferenceTarget', 'target')
    result = EngineeringAnswerService.from_snapshot(
        pr159_fixture['snapshot']
    ).query(target.canonical_subject_id, project='app')
    assert result.answer is not None
    answer = result.answer
    rendered = render_engineering_answer(result)

    assert answer.direct_test_callers.total_count == 0
    assert answer.high_confidence_test_paths.total_count == 0
    assert answer.possible_test_paths.total_count == 0
    assert 'covered by tests' not in rendered.casefold()
    assert 'no tests cover' not in rendered.casefold()
    assert 'this code is untested' not in rendered.casefold()
    assert 'absence of a represented TEST path does not prove' in rendered


def test_pr159_machine_json_snapshot_identity_and_public_api_stay_unchanged(
    pr159_fixture,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    code_service = JavaCodeIntelligenceService.from_snapshot(
        pr159_fixture['snapshot']
    )
    before = code_service.query(changed.canonical_subject_id)
    before_bytes = before.to_json().encode('utf-8')
    snapshot_id = pr159_fixture['snapshot'].snapshot_id
    manifest = public_api.public_api_manifest()

    synthesis = EngineeringAnswerService(code_service).query(
        changed.canonical_subject_id,
    )
    after = code_service.query(changed.canonical_subject_id)

    assert synthesis.answer is not None
    assert after.to_json().encode('utf-8') == before_bytes
    assert pr159_fixture['snapshot'].snapshot_id == snapshot_id
    assert public_api.public_api_manifest() == manifest
    assert public_api.public_api_compatibility_issues() == ()
    assert 'EngineeringAnswer' not in public_api.__all__


class _StaticContextBuilder:
    def __init__(self, context):
        self.context = context

    def build(self, *_args, **_kwargs):
        return self.context


def test_ask_uses_compact_synthesis_with_pr162_budget_and_grounded_fallback(
    pr162_high_fanout_fixture,
) -> None:
    fixture = pr162_high_fanout_fixture
    changed = _entry(fixture, 'FanoutTarget', 'changed')
    context = EngineeringChatContextBuilder().build(
        fixture['snapshot'],
        question='If I modify this method, what should I worry about?',
        subject=changed.canonical_subject_id,
        kind='method',
        project='app',
        language='java',
        capabilities=('code_impact',),
        result_limit=8,
        token_budget=5_500,
    )
    section = next(
        item for item in context.sections if item.section_id == 'code_impact'
    )
    synthesis = section.content['engineering_answer']

    assert synthesis['producer_version'] == ENGINEERING_ANSWER_PRODUCER
    assert synthesis['subject']['canonical_id'] == changed.canonical_subject_id
    assert synthesis['counts']['upstream_direct']['total'] > 0
    assert synthesis['counts']['upstream_transitive']['total'] > 0
    assert synthesis['inspect_first']
    assert context.selection.estimated_tokens <= 5_500
    assert section.content['report']['direct_callers']['high_confidence'][
        'included_count'
    ] == 2

    result = AskEngine(
        LlmClient(
            ScriptedLlmProvider((LlmProviderError('scripted failure'),)),
            RetryPolicy(maximum_attempts=1),
        ),
        context_builder=_StaticContextBuilder(context),
    ).ask(
        fixture['snapshot'],
        AskRequest(
            'If I modify this method, what should I worry about?',
            subject=changed.canonical_subject_id,
            kind='method',
            project='app',
            language='java',
            capabilities=('code_impact',),
            maximum_input_tokens=20_000,
        ),
    )

    assert result.grounding_summary is not None
    assert result.grounding_summary.provider_grounded is False
    assert result.grounding_summary.delivered_answer_grounded is True
    assert result.grounding_summary.request_complete is True
    assert result.grounding_summary.fallback_used is True
    assert 'What to inspect first:' in result.answer
    assert 'Represented TEST reachability:' in result.answer
    assert 'runtime test coverage' in result.answer
    assert 'Grounding evidence:' in result.answer


def test_explain_selection_keeps_balanced_engineering_minimum(
    pr162_high_fanout_fixture,
) -> None:
    fixture = pr162_high_fanout_fixture
    changed = _entry(fixture, 'FanoutTarget', 'changed')
    explanation = StructuredExplanationService(
        fixture['snapshot']
    ).explain(
        ExplanationRequest(
            changed.canonical_subject_id,
            kind='method',
            project='app',
            language='java',
        ),
        token_budget=7_000,
    )
    titles = {item.title: item for item in explanation.facts}

    assert {
        'Represented Java callable identity',
        'Java direct caller summary',
        'Java upstream impact summary',
        'Java direct callee summary',
        'Represented TEST summary',
        'Java uncertainty summary',
    } <= set(titles)
    assert all(titles[name].priority <= 10 for name in (
        'Represented Java callable identity',
        'Java direct caller summary',
        'Java upstream impact summary',
        'Java direct callee summary',
        'Represented TEST summary',
        'Java uncertainty summary',
    ))
    assert explanation.selection.estimated_tokens <= 7_000
    assert explanation.to_json() == StructuredExplanationService(
        fixture['snapshot']
    ).explain(
        ExplanationRequest(
            changed.canonical_subject_id,
            kind='method', project='app', language='java',
        ),
        token_budget=7_000,
    ).to_json()


def test_cli_human_reference_and_interactive_discovery_reach_answer(
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

    direct = runner.invoke(
        atlas_cli.app,
        ['answer', 'demo.Target#changed', str(tmp_path), '--project', 'app', '--limit', '2'],
    )
    assert direct.exit_code == 0, direct.output
    assert 'ATLAS DETERMINISTIC ENGINEERING ANSWER' in direct.output
    assert changed.canonical_subject_id in direct.output
    assert (
        f'qualified callable: {changed.identity.normalized_key}' in direct.output
    )

    interactive = runner.invoke(
        atlas_cli.app,
        ['ai', 'session', str(tmp_path)],
        input='/search changed 1\n/use 1\n/answer\n/stats\n/exit\n',
    )
    assert interactive.exit_code == 0, interactive.output
    assert f'subject={changed.canonical_subject_id}' in interactive.output
    assert 'ATLAS DETERMINISTIC ENGINEERING ANSWER' in interactive.output
    stats = next(
        json.loads(line) for line in interactive.output.splitlines()
        if line.startswith('{') and 'runtime_build_count' in line
    )
    assert stats['runtime_build_count'] == 1
    assert stats['component_build_counts'] == {
        'canonical_subject_resolver': 1,
        'java_code_intelligence': 1,
    }
