from __future__ import annotations

import copy
import hashlib
import json

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
import moughorai.structured_explanation.service as structured_service
from moughorai.atlas_cli import app
from moughorai.ai_ask import AskEngine, AskRequest, EngineeringChatContextBuilder
from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_explain import ExplainEngine, ExplainRequest
from moughorai.repository_runtime import (
    RepositoryIntelligenceRuntime,
    RepositoryRuntimeIdentity,
    RepositoryRuntimeSession,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.subject_resolution import CanonicalSubjectResolver
from moughorai.llm import (
    LlmClient,
    LlmProviderError,
    RetryPolicy,
    ScriptedLlmProvider,
)

from test_pr159_java_code_impact import (
    _entry,
    pr159_fixture,
    pr162_high_fanout_fixture,
)


runner = CliRunner()


def _context(builder, snapshot, subject, *, project='app'):
    return builder.build(
        snapshot,
        question='If I modify this method, what can be affected?',
        subject=subject,
        kind='method',
        project=project,
        language='java',
        capabilities=('code_impact',),
        result_limit=8,
        token_budget=5_500,
    )


def test_same_snapshot_reuses_all_expensive_authorities(pr159_fixture) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    session = RepositoryRuntimeSession()
    builder = EngineeringChatContextBuilder(runtime_session=session)

    first = _context(builder, pr159_fixture['snapshot'], changed.canonical_subject_id)
    second = _context(builder, pr159_fixture['snapshot'], changed.canonical_subject_id)

    assert first.to_json() == second.to_json()
    statistics = session.statistics
    assert statistics.runtime_build_count == 1
    assert statistics.reuse_count == 1
    assert dict(statistics.component_build_counts) == {
        'canonical_subject_resolver': 1,
        'java_code_intelligence': 1,
        'semantic_search': 1,
        'structured_explanation:false': 1,
    }


def test_request_constraints_do_not_leak_across_reused_runtime(
    pr159_fixture,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    builder = EngineeringChatContextBuilder()

    first = _context(builder, pr159_fixture['snapshot'], changed.canonical_subject_id)
    wrong = _context(
        builder,
        pr159_fixture['snapshot'],
        changed.canonical_subject_id,
        project='wrong-project',
    )
    repeated = _context(builder, pr159_fixture['snapshot'], changed.canonical_subject_id)

    assert repeated.to_json() == first.to_json()
    assert wrong.subject_ids == ()
    assert not any(
        item.section_id == 'code_impact' and item.evidence_ids
        for item in wrong.sections
    )


def test_changed_snapshot_and_artifact_lineage_replace_runtime(
    pr159_fixture,
) -> None:
    session = RepositoryRuntimeSession()
    original = session.runtime_for(pr159_fixture['snapshot'])
    original_resolver = original.resolver

    payload = copy.deepcopy(pr159_fixture['payload'])
    payload['java_callable_index']['producer_version'] = 'invalid-producer'
    changed = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(payload),
        workspace_fingerprint='pr165-changed-artifact',
        analyzer_version='test-pr165/1',
    )
    replacement = session.runtime_for(changed)

    assert replacement is not original
    assert replacement.identity.snapshot_id == changed.snapshot_id
    assert session.statistics.runtime_build_count == 2
    with pytest.raises(RuntimeError, match='closed'):
        _ = original.resolver
    assert original_resolver is not replacement.resolver
    assert not replacement.java_code_intelligence.available
    assert any(
        'schema-incompatible' in item
        for item in replacement.java_code_intelligence.limitations
    )


def test_runtime_identity_includes_workspace_and_authoritative_lineage(
    pr159_fixture,
    tmp_path,
) -> None:
    snapshot = pr159_fixture['snapshot']
    first = RepositoryRuntimeIdentity.from_snapshot(
        snapshot, workspace_root=tmp_path,
    )
    second = RepositoryRuntimeIdentity.from_snapshot(
        snapshot, workspace_root=tmp_path / 'other',
    )

    assert first != second
    assert first.snapshot_id == snapshot.snapshot_id
    lineage = dict(first.artifacts)
    assert dict(lineage['java_callable_index'])['input_fingerprint'].startswith(
        'java-callable-index:'
    )
    assert dict(lineage['java_code_graph'])['input_fingerprint'].startswith(
        'java-code-graph:'
    )
    assert dict(lineage['java_test_evidence'])['input_fingerprint'].startswith(
        'java-test-evidence:'
    )


def test_failed_lazy_initialization_is_not_cached(
    pr159_fixture,
    monkeypatch,
) -> None:
    runtime = RepositoryIntelligenceRuntime(pr159_fixture['snapshot'])
    original = CanonicalSubjectResolver.from_snapshot
    attempts = 0

    def fail_once(cls, snapshot):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError('synthetic resolver failure')
        return original(snapshot)

    monkeypatch.setattr(
        CanonicalSubjectResolver,
        'from_snapshot',
        classmethod(fail_once),
    )
    with pytest.raises(ValueError, match='synthetic resolver failure'):
        _ = runtime.resolver
    assert runtime.component_build_counts == ()
    assert runtime.resolver.graph_digest != 'unavailable'
    assert runtime.component_build_counts == (('canonical_subject_resolver', 1),)


def test_explain_engine_reuses_runtime_and_preserves_exact_output(
    pr159_fixture,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    session = RepositoryRuntimeSession()
    engine = ExplainEngine(runtime_session=session)
    request = ExplainRequest(
        subject=changed.canonical_subject_id,
        kind='method',
        project='app',
        language='java',
        narrative=False,
    )

    first = engine.explain(pr159_fixture['snapshot'], request)
    second = engine.explain(pr159_fixture['snapshot'], request)

    assert first.structured_explanation is not None
    assert second.structured_explanation is not None
    assert first.structured_explanation.to_json() == second.structured_explanation.to_json()
    assert dict(session.statistics.component_build_counts) == {
        'canonical_subject_resolver': 1,
        'java_code_intelligence': 1,
        'structured_explanation:true': 1,
    }


def test_runtime_exact_subject_reuses_validated_callable_index(
    pr159_fixture,
    monkeypatch,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    session = RepositoryRuntimeSession()
    engine = ExplainEngine(runtime_session=session)
    request = ExplainRequest(
        subject=changed.canonical_subject_id,
        kind='method',
        project='app',
        language='java',
        narrative=False,
    )

    def redundant_reconstruction(_value):
        raise AssertionError('runtime exact subject reparsed the callable index')

    monkeypatch.setattr(
        structured_service,
        'callable_index_from_dict',
        redundant_reconstruction,
    )

    first = engine.explain(pr159_fixture['snapshot'], request)
    second = engine.explain(pr159_fixture['snapshot'], request)

    assert first.structured_explanation is not None
    assert second.structured_explanation is not None
    assert (
        first.structured_explanation.to_json()
        == second.structured_explanation.to_json()
    )
    assert dict(session.statistics.component_build_counts)[
        'java_code_intelligence'
    ] == 1


def test_cli_session_reuses_one_runtime_across_impact_requests(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    monkeypatch.setattr(
        atlas_cli,
        '_load_ai_snapshot',
        lambda *_args, **_kwargs: pr159_fixture['snapshot'],
    )
    monkeypatch.setattr(
        atlas_cli,
        '_ai_provider_factory',
        lambda: ScriptedLlmProvider([]),
    )

    result = runner.invoke(
        app,
        [
            'ai', 'session', str(tmp_path),
            '--subject', changed.canonical_subject_id,
            '--project', 'app',
        ],
        input=(
            f'/subject {changed.canonical_subject_id}\n'
            '/project app\n/impact\n/impact\n/stats\n/exit\n'
        ),
    )

    assert result.exit_code == 0, result.output
    assert f'subject={changed.canonical_subject_id}' in result.output
    assert 'project=app' in result.output
    assert result.output.count('Atlas Java code intelligence') == 2
    stats_line = next(
        line for line in result.output.splitlines()
        if line.startswith('{') and 'runtime_build_count' in line
    )
    statistics = json.loads(stats_line)
    assert statistics['runtime_build_count'] == 1
    assert statistics['reuse_count'] == 1
    assert statistics['component_build_counts'] == {
        'java_code_intelligence': 1,
    }
    assert 'Atlas session closed.' in result.output


def test_repeated_java_test_queries_are_byte_identical_and_reused(
    pr159_fixture,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    session = RepositoryRuntimeSession()
    runtime = session.runtime_for(pr159_fixture['snapshot'])

    outputs = tuple(
        runtime.java_code_intelligence.query(
            changed.canonical_subject_id,
            project='app',
        ).to_json()
        for _ in range(10)
    )

    assert len({hashlib.sha256(item.encode()).hexdigest() for item in outputs}) == 1
    assert dict(runtime.component_build_counts) == {
        'java_code_intelligence': 1,
    }
    report = json.loads(outputs[0])['report']
    assert report['represented_test_intelligence'][
        'direct_test_callers'
    ]['total_count'] == 1


def test_high_fanout_context_remains_bounded_across_five_warm_turns(
    pr162_high_fanout_fixture,
) -> None:
    fixture = pr162_high_fanout_fixture
    changed = _entry(fixture, 'FanoutTarget', 'changed')
    builder = EngineeringChatContextBuilder()

    contexts = tuple(
        _context(builder, fixture['snapshot'], changed.canonical_subject_id)
        for _ in range(5)
    )
    payloads = tuple(item.to_json() for item in contexts)

    assert len({hashlib.sha256(item.encode()).hexdigest() for item in payloads}) == 1
    assert all(item.estimated_tokens <= 5_500 for item in contexts)
    section = next(
        item for item in contexts[0].sections
        if item.section_id == 'code_impact'
    )
    direct = section.content['report']['direct_callees']['high_confidence']
    assert direct['included_count'] == 2
    assert direct['omitted_count'] == direct['total_count'] - 2
    statistics = builder.runtime_session.statistics
    assert statistics.runtime_build_count == 1
    assert statistics.reuse_count == 4
    assert max(dict(statistics.component_build_counts).values()) == 1


def test_runtime_close_releases_components_and_rebuilds_cleanly(
    pr159_fixture,
) -> None:
    session = RepositoryRuntimeSession()
    first = session.runtime_for(pr159_fixture['snapshot'])
    _ = first.resolver
    _ = first.java_code_intelligence
    session.close()

    with pytest.raises(RuntimeError, match='closed'):
        _ = first.java_code_intelligence
    second = session.runtime_for(pr159_fixture['snapshot'])
    assert second is not first
    assert session.statistics.runtime_build_count == 2


def test_provider_failure_fallback_reuses_runtime_and_stays_grounded(
    pr159_fixture,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    session = RepositoryRuntimeSession()
    builder = EngineeringChatContextBuilder(runtime_session=session)
    engine = AskEngine(
        LlmClient(
            ScriptedLlmProvider((
                LlmProviderError('first failure'),
                LlmProviderError('second failure'),
            )),
            RetryPolicy(maximum_attempts=1),
        ),
        context_builder=builder,
    )
    request = AskRequest(
        'If I modify this method, what can be affected?',
        subject=changed.canonical_subject_id,
        kind='method',
        project='app',
        language='java',
        capabilities=('code_impact',),
        result_limit=8,
        maximum_input_tokens=20_000,
    )

    first = engine.ask(pr159_fixture['snapshot'], request)
    second = engine.ask(pr159_fixture['snapshot'], request)

    assert first.answer.encode() == second.answer.encode()
    assert first.context is not None and second.context is not None
    assert first.context.to_json() == second.context.to_json()
    assert first.grounding_summary is not None
    assert first.grounding_summary.provider_grounded is False
    assert first.grounding_summary.delivered_answer_grounded is True
    assert first.grounding_summary.request_complete is True
    assert first.grounding_summary.fallback_used is True
    assert session.statistics.runtime_build_count == 1
    assert session.statistics.reuse_count == 1
