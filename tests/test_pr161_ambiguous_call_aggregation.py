from __future__ import annotations

import json
from pathlib import Path

import pytest

from moughorai.ai_ask import (
    AskEngine,
    AskRequest,
    EngineeringChatContextBuilder,
)
from moughorai.ai_ask.context import _compact_code_impact_report
from moughorai.ai_context import SemanticContextCollector, WorkspaceSemanticContext
from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.code_intelligence import (
    CodeIntelligenceConfiguration,
    JavaCodeIntelligenceService,
    render_code_intelligence,
)
from moughorai.code_intelligence.service import _bounded_ambiguous_call_groups
from moughorai.java_code_intelligence.code_graph import (
    CodeGraphEdgeKind,
    code_graph_from_dict,
)
from moughorai.java_code_intelligence.persistence import callable_index_from_dict
from moughorai.llm import LlmClient, ScriptedLlmProvider
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.structured_explanation import (
    ExplanationRequest,
    StructuredExplanationService,
)
from moughorai.workspace import (
    Project,
    ProjectRun,
    ProjectRunStatus,
    WorkspaceRunReport,
    WorkspaceService,
)


MAIN_SOURCE = '''package demo;
class Ref { static void target() {} }
class Over {
  static void pick(String value) {}
  static void pick(Integer value) {}
  static void pick(Long value) {}
  static void pick(Double value) {}
  static void pick(Float value) {}
  static void pick(Short value) {}
  static void pick(Byte value) {}
  static void pick(Character value) {}
}
class Target {
  static void leaf() {}
  static void changed() {
    leaf();
    Over.pick(null);
    Over.pick(null);
    Ref::target;
  }
  static void upstream() { changed(); }
}
'''


TEST_SOURCE = '''package demo;
@interface Test {}
class TargetTest {
  @Test void root() { Target.upstream(); }
}
'''


@pytest.fixture(scope='module')
def pr161_fixture(tmp_path_factory):
    root = tmp_path_factory.mktemp('pr161-ambiguous-call-aggregation')
    project_root = root / 'app'
    main = project_root / 'src/main/java/demo/Target.java'
    test = project_root / 'src/test/java/demo/TargetTest.java'
    main.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    main.write_text(MAIN_SOURCE, encoding='utf-8')
    test.write_text(TEST_SOURCE, encoding='utf-8')
    (root / 'atlas.yaml').write_text(
        'projects:\n  - name: app\n    path: app\n',
        encoding='utf-8',
    )
    document = JavaLanguageAnalyzer().analyze(
        Project('app', project_root),
        (main, test),
        {},
    )
    run_report = WorkspaceRunReport(
        (ProjectRun('app', ProjectRunStatus.SUCCEEDED, document),),
        ('app',),
        ('app',),
    )
    payload = SemanticContextCollector(
        WorkspaceService(root)
    ).collect(run_report).context.to_dict()
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(payload),
        workspace_fingerprint='pr161-ambiguous-call-aggregation',
        analyzer_version='test-pr161/1',
    )
    index = callable_index_from_dict(payload['java_callable_index'])
    graph = code_graph_from_dict(payload['java_code_graph'], index)
    return {
        'root': root,
        'snapshot': snapshot,
        'payload': payload,
        'index': index,
        'graph': graph,
        'producer_index': document.require_artifact('java_callable_index'),
        'producer_graph': document.require_artifact('java_code_graph'),
    }


def _entry(fixture, owner: str, name: str):
    matches = tuple(
        item for item in fixture['index'].entries
        if item.identity.owner_type.endswith(owner)
        and item.identity.name == name
    )
    assert len(matches) == 1, (owner, name, matches)
    return matches[0]


def _service_and_report(fixture, **configuration):
    changed = _entry(fixture, 'Target', 'changed')
    service = JavaCodeIntelligenceService.from_snapshot(fixture['snapshot'])
    result = service.query(
        changed.canonical_subject_id,
        configuration=CodeIntelligenceConfiguration(**configuration),
    )
    assert result.report is not None
    return service, result, result.report


def test_outgoing_candidates_group_by_source_site_without_changing_evidence(
    pr161_fixture,
) -> None:
    service, result, report = _service_and_report(
        pr161_fixture,
        max_candidates_per_call_site=3,
    )
    machine = report.direct_callees_conservative
    groups = report.direct_callee_conservative_groups

    assert machine.total_count == len(machine.items) == 16
    assert groups.call_site_count == len(groups.items) == 2
    assert groups.candidate_projection_count == 16
    assert {item.total_candidate_count for item in groups.items} == {8}
    assert {item.included_candidate_count for item in groups.items} == {3}
    assert {item.omitted_candidate_count for item in groups.items} == {5}
    assert len({item.location.compact for item in groups.items}) == 2
    assert len({item.producer_evidence_id for item in groups.items}) == 2
    assert all(
        tuple(sorted(item.included_candidate_ids))
        == item.included_candidate_ids
        for item in groups.items
    )
    assert all(item.canonical_direction == 'caller_to_callee' for item in groups.items)
    assert all(item.relation == 'calls' for item in groups.items)

    raw = tuple(machine.items)
    rebuilt = _bounded_ambiguous_call_groups(
        reversed(raw), service._sites, 64, 3,
    )
    assert rebuilt.to_dict() == groups.to_dict()
    assert tuple(machine.items) == raw
    assert {
        (item.producer_evidence_id, item.canonical_target, item.edge_kind)
        for item in machine.items
    } == {
        (edge.evidence_id, edge.target_subject_id, edge.kind)
        for edge in pr161_fixture['graph'].edges
        if edge.caller_subject_id == report.subject.canonical_id
        and edge.kind in {
            CodeGraphEdgeKind.POSSIBLE_CALL_TARGET,
            CodeGraphEdgeKind.POSSIBLE_DISPATCH_TARGET,
        }
    }

    assert report.direct_callees_high_confidence.total_count == 1
    assert report.direct_callee_method_references.total_count == 1
    grouped_evidence = {item.producer_evidence_id for item in groups.items}
    assert not grouped_evidence.intersection(
        item.producer_evidence_id
        for item in report.direct_callees_high_confidence.items
    )
    assert not grouped_evidence.intersection(
        item.producer_evidence_id
        for item in report.direct_callee_method_references.items
    )

    payload = result.to_dict()
    assert set(payload['report']['direct_callees']) == {
        'high_confidence', 'conservative', 'method_references',
    }
    assert 'conservative_call_sites' not in result.to_json()
    assert payload['report']['direct_callees']['conservative']['total_count'] == 16
    assert (
        report.traceability.callable_index_fingerprint
        == pr161_fixture['index'].input_fingerprint
    )
    assert (
        report.traceability.code_graph_fingerprint
        == pr161_fixture['graph'].input_fingerprint
    )
    assert report.traceability.test_evidence_fingerprint == (
        pr161_fixture['payload']['java_test_evidence']['input_fingerprint']
    )


def test_group_bounds_change_presentation_only_and_render_deterministically(
    pr161_fixture,
) -> None:
    _service, first, report = _service_and_report(
        pr161_fixture,
        max_candidates_per_call_site=3,
    )
    _service, second, bounded = _service_and_report(
        pr161_fixture,
        max_candidates_per_call_site=1,
    )
    assert first.to_json() == second.to_json()
    assert report.traversal.to_dict() == bounded.traversal.to_dict()
    assert report.upstream_direct.to_dict() == bounded.upstream_direct.to_dict()
    assert report.upstream_transitive.to_dict() == bounded.upstream_transitive.to_dict()
    assert (
        report.high_confidence_test_paths.to_dict()
        == bounded.high_confidence_test_paths.to_dict()
    )

    rendered = render_code_intelligence(first)
    assert rendered == render_code_intelligence(first)
    assert 'conservative call sites: total-sites=2' in rendered
    assert 'candidate-projections=16' in rendered
    assert rendered.count('  candidate-targets:') == 2
    grouped_section_lines = 1 + 3 * 2
    raw_section_lines = 1 + 16
    estimated_legacy_lines = (
        len(rendered.splitlines()) - grouped_section_lines + raw_section_lines
    )
    assert len(rendered.splitlines()) < estimated_legacy_lines
    assert MAIN_SOURCE not in rendered
    assert str(pr161_fixture['root'].resolve()) not in rendered


def test_incoming_conservative_callers_use_the_same_site_abstraction(
    pr161_fixture,
) -> None:
    candidate = next(
        item for item in pr161_fixture['index'].entries
        if item.identity.owner_type.endswith('Over')
        and item.identity.name == 'pick'
    )
    result = JavaCodeIntelligenceService.from_snapshot(
        pr161_fixture['snapshot']
    ).query(candidate.canonical_subject_id)
    assert result.report is not None
    machine = result.report.direct_callers_conservative
    groups = result.report.direct_caller_conservative_groups
    assert machine.total_count == 2
    assert groups.call_site_count == 2
    assert groups.candidate_projection_count == 2
    assert all(item.total_candidate_count == 1 for item in groups.items)
    assert {
        item.producer_evidence_id for item in groups.items
    } == {
        item.producer_evidence_id for item in machine.items
    }


def test_explain_uses_grouped_facts_and_preserves_upstream_and_tests(
    pr161_fixture,
) -> None:
    changed = _entry(pr161_fixture, 'Target', 'changed')
    service = StructuredExplanationService(pr161_fixture['snapshot'])
    first = service.explain(ExplanationRequest(
        changed.canonical_subject_id,
        kind='method',
        project='app',
        language='java',
    ))
    second = service.explain(ExplanationRequest(
        changed.canonical_subject_id,
        kind='method',
        project='app',
        language='java',
    ))
    assert first.to_json() == second.to_json()
    group_facts = tuple(
        item for item in first.facts
        if item.title == 'Direct conservative Java callee call site'
    )
    assert len(group_facts) == 2
    assert len(group_facts) < 16
    assert sum(
        next(
            attribute.value for attribute in item.attributes
            if attribute.key == 'candidate_projection_count'
        )
        for item in group_facts
    ) == 16
    assert any('upstream' in item.title.casefold() for item in first.facts)
    assert any('TEST' in item.title for item in first.facts)
    for fact in group_facts:
        assert fact.evidence_ids
        assert any(
            ref.startswith('evidence:')
            for evidence_id in fact.evidence_ids
            for ref in first.evidence_index.get(evidence_id).source_refs
        )


class _StaticContextBuilder:
    def __init__(self, context):
        self.context = context

    def build(self, *_args, **_kwargs):
        return self.context


def test_ask_context_and_fallback_use_bounded_groups(
    pr161_fixture,
) -> None:
    changed = _entry(pr161_fixture, 'Target', 'changed')
    context = EngineeringChatContextBuilder().build(
        pr161_fixture['snapshot'],
        question='If I modify this method, what can be affected?',
        subject=changed.canonical_subject_id,
        kind='method',
        project='app',
        language='java',
        capabilities=('code_impact',),
        result_limit=8,
        token_budget=6_300,
    )
    section = next(item for item in context.sections if item.section_id == 'code_impact')
    report = section.content['report']
    conservative = report['direct_callees']['conservative_call_sites']
    assert 'conservative' not in report['direct_callees']
    assert conservative['call_site_count'] == 2
    assert conservative['candidate_projection_count'] == 16
    assert len(conservative['items']) == 2
    assert all(len(item['included_candidate_ids']) == 1 for item in conservative['items'])
    assert context.estimated_tokens <= context.selection.token_budget
    assert MAIN_SOURCE not in context.to_json()
    assert str(pr161_fixture['root'].resolve()) not in context.to_json()

    _service, _result, full = _service_and_report(
        pr161_fixture,
        max_candidates_per_call_site=3,
    )
    legacy = _compact_code_impact_report(full.to_dict())
    grouped = _compact_code_impact_report(
        full.to_dict(),
        conservative_callers=full.direct_caller_conservative_groups.to_dict(),
        conservative_callees=full.direct_callee_conservative_groups.to_dict(),
    )
    compact = lambda value: json.dumps(
        value, ensure_ascii=False, separators=(',', ':'), sort_keys=True,
    )
    assert len(compact(grouped)) < len(compact(legacy))

    def ask(prose: str):
        return AskEngine(
            LlmClient(ScriptedLlmProvider((prose,))),
            context_builder=_StaticContextBuilder(context),
        ).ask(
            pr161_fixture['snapshot'],
            AskRequest(
                'If I modify this method, what can be affected?',
                subject=changed.canonical_subject_id,
                kind='method',
                project='app',
                language='java',
                capabilities=('code_impact',),
                maximum_input_tokens=20_000,
            ),
        )

    first = ask('Unsupported provider prose.')
    second = ask('Different unsupported provider prose.')
    assert first.answer == second.answer
    assert 'conservative source call site(s)' in first.answer
    assert 'candidate projection(s)' in first.answer
    assert 'Unsupported provider prose' not in first.answer
    assert first.grounding_summary is not None
    assert first.grounding_summary.provider_grounded is False
    assert first.grounding_summary.delivered_answer_grounded is True
    assert first.grounding_summary.fallback_used is True
