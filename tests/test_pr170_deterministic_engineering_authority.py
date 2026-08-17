from __future__ import annotations

import json

import pytest

from moughorai.ai_ask import (
    AskEngine,
    AskRequest,
    EngineeringChatContextBuilder,
)
from moughorai.ai_context import (
    SemanticContextCollector,
    WorkspaceSemanticContext,
)
from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.engineering_answer import (
    EngineeringAnswerConfiguration,
    EngineeringAnswerService,
    EngineeringAnswerView,
    render_engineering_answer,
)
from moughorai.engineering_answer.renderer import _select_summary_inspect
from moughorai.java_code_intelligence.persistence import callable_index_from_dict
from moughorai.llm import (
    LlmClient,
    LlmProviderError,
    RetryPolicy,
    ScriptedLlmProvider,
)
from moughorai.semantic_snapshot import AtlasSemanticSnapshot
from moughorai.workspace import (
    Project,
    ProjectRun,
    ProjectRunStatus,
    WorkspaceRunReport,
    WorkspaceService,
)


PROJECT = "sygma-it-sygma-it-services"
QUESTION = (
    "If I modify this method, which represented tests should I inspect first "
    "and why?"
)
FORBIDDEN_TEST = "testImportProjectWithEvents"
EXPECTED_TESTS = (
    "shouldImportValidProjectsUsingProposalV2AndEarlySession",
    "shouldImportValidProjectsUsingProposalV2",
    "shouldImportAndInviteValidMff2127ProjectWithReportingPeriodDataDimension",
    "shouldImportValidMff2127ProjectsUsingProposalV3",
    "limitNumberOfFeaturesWhenAgreementTypeIsCertificate",
)


MAIN_SOURCE = """package synthesis;
class Target {
  static void mapEventToSepJmsEvent() {}
}
"""


TEST_SOURCE = """package synthesis;
@interface Test {}
class SEPProjectImportSpec {
  static void sendSEPEventProcessAndAssert() {
    Target.mapEventToSepJmsEvent();
  }
  @Test void shouldImportValidProjectsUsingProposalV2AndEarlySession() {
    sendSEPEventProcessAndAssert();
  }
  @Test void shouldImportValidProjectsUsingProposalV2() {
    sendSEPEventProcessAndAssert();
  }
  @Test void shouldImportAndInviteValidMff2127ProjectWithReportingPeriodDataDimension() {
    sendSEPEventProcessAndAssert();
  }
  @Test void shouldImportValidMff2127ProjectsUsingProposalV3() {
    sendSEPEventProcessAndAssert();
  }
  @Test void limitNumberOfFeaturesWhenAgreementTypeIsCertificate() {
    sendSEPEventProcessAndAssert();
  }
}
"""


class _StaticContextBuilder:
    def __init__(self, context) -> None:
        self.context = context

    def build(self, *_args, **_kwargs):
        return self.context


@pytest.fixture(scope="module")
def five_root_fixture(tmp_path_factory):
    root = tmp_path_factory.mktemp("pr170-five-root")
    project_root = root / "app"
    main = project_root / "src/main/java/synthesis/Target.java"
    test = project_root / "src/test/java/synthesis/SEPProjectImportSpec.java"
    main.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    main.write_text(MAIN_SOURCE, encoding="utf-8")
    test.write_text(TEST_SOURCE, encoding="utf-8")
    (root / "atlas.yaml").write_text(
        f"projects:\n  - name: {PROJECT}\n    path: app\n",
        encoding="utf-8",
    )
    document = JavaLanguageAnalyzer().analyze(
        Project(PROJECT, project_root),
        (main, test),
        {},
    )
    run_report = WorkspaceRunReport(
        (ProjectRun(PROJECT, ProjectRunStatus.SUCCEEDED, document),),
        (PROJECT,),
        (PROJECT,),
    )
    payload = SemanticContextCollector(
        WorkspaceService(root)
    ).collect(run_report).context.to_dict()
    snapshot = AtlasSemanticSnapshot.create(
        WorkspaceSemanticContext(payload),
        workspace_fingerprint="pr170-five-root",
        analyzer_version="test-pr170/1",
    )
    index = callable_index_from_dict(payload["java_callable_index"])
    entries = {
        (item.identity.owner_type.rsplit(".", 1)[-1], item.identity.name): item
        for item in index.entries
    }
    return {
        "snapshot": snapshot,
        "index": index,
        "changed": entries[("Target", "mapEventToSepJmsEvent")],
        "helper": entries[("SEPProjectImportSpec", "sendSEPEventProcessAndAssert")],
        "roots": tuple(
            entries[("SEPProjectImportSpec", name)] for name in EXPECTED_TESTS
        ),
    }


def _configuration() -> EngineeringAnswerConfiguration:
    return EngineeringAnswerConfiguration(
        max_depth=6,
        max_nodes=1_024,
        max_representatives_per_section=8,
        max_limitation_representatives=2,
        max_candidates_per_call_site=2,
        max_inspect_items=12,
    )


def _synthesis(fixture, *, project: str = PROJECT):
    return EngineeringAnswerService.from_snapshot(fixture["snapshot"]).query(
        fixture["changed"].canonical_subject_id,
        kind="method",
        project=project,
        configuration=_configuration(),
    )


def _resolver(fixture):
    names = {
        item.canonical_subject_id: item.identity.normalized_key
        for item in fixture["index"].entries
    }
    return names.get


def _context(fixture, *, project: str = PROJECT):
    return EngineeringChatContextBuilder().build(
        fixture["snapshot"],
        question=QUESTION,
        subject=fixture["changed"].canonical_subject_id,
        kind="method",
        project=project,
        language="java",
        capabilities=("code_impact",),
        result_limit=8,
        token_budget=7_000,
    )


def _ask(fixture, context, outcome):
    return AskEngine(
        LlmClient(
            ScriptedLlmProvider((outcome,)),
            RetryPolicy(maximum_attempts=1),
        ),
        context_builder=_StaticContextBuilder(context),
    ).ask(
        fixture["snapshot"],
        AskRequest(
            QUESTION,
            subject=fixture["changed"].canonical_subject_id,
            kind="method",
            project=PROJECT,
            language="java",
            capabilities=("code_impact",),
            maximum_input_tokens=20_000,
            result_limit=8,
        ),
    )


def test_default_answer_names_all_five_roots_and_separates_helper(
    five_root_fixture,
) -> None:
    first = _synthesis(five_root_fixture)
    second = _synthesis(five_root_fixture)
    assert first.answer is not None
    answer = first.answer

    expected_ids = {
        item.canonical_subject_id for item in five_root_fixture["roots"]
    }
    root_ids = {
        item.canonical_reference
        for item in answer.high_confidence_test_paths.items
    }
    helper_ids = {
        item.canonical_reference for item in answer.direct_test_callers.items
    }
    assert root_ids == expected_ids
    assert len(root_ids) == 5
    assert answer.high_confidence_test_paths.total_count == 5
    assert answer.possible_test_paths.total_count == 0
    assert all(item.depth == 2 for item in answer.high_confidence_test_paths.items)
    assert helper_ids == {
        five_root_fixture["helper"].canonical_subject_id
    }
    assert not root_ids.intersection(helper_ids)

    rendered = render_engineering_answer(
        first,
        view=EngineeringAnswerView.SUMMARY,
        name_resolver=_resolver(five_root_fixture),
    )
    assert "REPRESENTED TEST ROOTS TO INSPECT" in rendered
    assert "TEST-SCOPED HELPER CONTEXT" in rendered
    assert "sendSEPEventProcessAndAssert" in rendered
    assert "not a represented TEST root" in rendered
    assert all(name in rendered for name in EXPECTED_TESTS)
    assert FORBIDDEN_TEST not in rendered
    assert first.to_json().encode("utf-8") == second.to_json().encode("utf-8")
    assert answer.traceability.snapshot_id == five_root_fixture["snapshot"].snapshot_id
    assert all(
        item.evidence_ids for item in answer.high_confidence_test_paths.items
    )


def test_grounded_provider_cannot_replace_or_inject_test_identities(
    five_root_fixture,
) -> None:
    context = _context(five_root_fixture)
    section = next(
        item for item in context.sections if item.section_id == "code_impact"
    )
    projected = section.content["engineering_answer"]
    roots = projected["represented_test_roots"]
    helpers = projected["test_scoped_helpers"]
    assert {item["name"] for item in roots} == set(EXPECTED_TESTS)
    assert [item["name"] for item in helpers] == [
        "sendSEPEventProcessAndAssert"
    ]
    assert all(item["represented_test_root"] is False for item in helpers)
    root_evidence = {
        evidence
        for item in roots
        for evidence in item["evidence_ids"]
    }
    assert root_evidence <= set(section.evidence_ids)

    valid = section.evidence_ids[0]
    provider_text = (
        f"{FORBIDDEN_TEST} is the only test to inspect. {valid}"
    )
    result = _ask(five_root_fixture, context, provider_text)

    assert result.grounding_summary is not None
    assert result.grounding_summary.provider_grounded is True
    assert result.grounding_summary.fallback_used is False
    assert result.answer != provider_text
    assert FORBIDDEN_TEST not in result.answer
    assert all(name in result.answer for name in EXPECTED_TESTS)
    assert "sendSEPEventProcessAndAssert" in result.answer
    assert "not a represented TEST root" in result.answer


def test_provider_failure_keeps_authoritative_five_root_answer(
    five_root_fixture,
) -> None:
    first = _ask(
        five_root_fixture,
        _context(five_root_fixture),
        LlmProviderError("provider unavailable"),
    )
    second = _ask(
        five_root_fixture,
        _context(five_root_fixture),
        LlmProviderError("different provider failure"),
    )

    assert first.grounding_summary is not None
    assert first.grounding_summary.provider_grounded is False
    assert first.grounding_summary.fallback_used is True
    assert first.grounding_summary.delivered_answer_grounded is True
    assert all(name in first.answer for name in EXPECTED_TESTS)
    assert "sendSEPEventProcessAndAssert" in first.answer
    assert FORBIDDEN_TEST not in first.answer
    assert first.answer.encode("utf-8") == second.answer.encode("utf-8")


def test_wrong_project_remains_fail_closed(five_root_fixture) -> None:
    result = _synthesis(five_root_fixture, project="wrong-project")
    assert result.resolution_status == "not_found"
    assert result.answer is None
    assert result.total_candidate_count == 0

    context = _context(five_root_fixture, project="wrong-project")
    section = next(
        item for item in context.sections if item.section_id == "code_impact"
    )
    assert "engineering_answer" not in section.content
    assert "report" not in section.content


def test_progressive_views_and_diverse_inspection_remain_bounded(
    five_root_fixture,
) -> None:
    result = _synthesis(five_root_fixture)
    assert result.answer is not None
    resolver = _resolver(five_root_fixture)
    json_before = result.to_json()
    summary = render_engineering_answer(
        result, view=EngineeringAnswerView.SUMMARY, name_resolver=resolver,
    )
    detail = render_engineering_answer(
        result, view=EngineeringAnswerView.DETAIL, name_resolver=resolver,
    )
    full = render_engineering_answer(
        result, view=EngineeringAnswerView.FULL, name_resolver=resolver,
    )

    assert "MORE" in summary
    assert "DETAIL REPRESENTATIVES" not in summary
    assert "DETAIL REPRESENTATIVES" in detail
    assert "TRACEABILITY" in full
    assert result.to_json() == json_before
    inspect = summary.split("INSPECT FIRST", 1)[1].split("LIMITS", 1)[0]
    inspect_lines = tuple(
        line for line in inspect.splitlines() if line[:1].isdigit()
    )
    assert 1 <= len(inspect_lines) <= 5
    assert len({line.split(" â€” ", 1)[-1] for line in inspect_lines}) > 1
    inspect_items = _select_summary_inspect(result.answer, maximum=5)
    assert 1 <= len(inspect_items) <= 5
    assert len({item.category for item in inspect_items}) > 1
    assert all(name in summary for name in EXPECTED_TESTS)
    assert len(json.loads(result.to_json())["answer"]["traceability"]) > 0
