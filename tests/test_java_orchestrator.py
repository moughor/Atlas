from dataclasses import dataclass

from moughorai.java_orchestrator import (
    JavaAnalysisCommand,
    JavaAnalysisMode,
    JavaAnalysisStatus,
    JavaProjectAnalysisOrchestrator,
)


class WorkspaceBuilder:
    def build(self, projects):
        return {"projects": projects}


class KnowledgeBuilder:
    def build(self, workspace):
        return {"workspace": workspace}


class BaselineService:
    def capture(self, workspace, policy=None):
        return {"captured": True, "policy": policy}


@dataclass(frozen=True)
class Gate:
    status: str


class QualityGateService:
    def __init__(self, status="pass"):
        self.status = status

    def evaluate(self, workspace, **kwargs):
        return Gate(self.status)


class RetrievalService:
    def retrieve(self, graph, query):
        return {"query": query}

    def context(self, graph, query):
        return f"context:{query}"


class ContractService:
    def request(self, context, *, mode=None):
        return {"context": context, "mode": mode}


@dataclass(frozen=True)
class ProviderResult:
    accepted: bool
    answer: str | None = None


class ProviderService:
    def __init__(self, accepted=True):
        self.accepted = accepted

    def execute(self, request, *, metadata=None):
        return ProviderResult(
            accepted=self.accepted,
            answer="Validated answer. [E1]" if self.accepted else None,
        )


def make_orchestrator(*, gate="pass", provider=True):
    return JavaProjectAnalysisOrchestrator(
        workspace_builder=WorkspaceBuilder(),
        knowledge_builder=KnowledgeBuilder(),
        baseline_service=BaselineService(),
        quality_gate_service=QualityGateService(gate),
        retrieval_service=RetrievalService(),
        llm_contract_service=ContractService(),
        llm_provider_service=ProviderService(provider),
    )


def test_analysis_mode_builds_workspace_graph_and_baseline():
    result = make_orchestrator().execute(
        JavaAnalysisCommand(
            projects=("api", "core"),
            mode=JavaAnalysisMode.ANALYZE,
        )
    )

    assert result.completed
    assert result.stages == ("workspace", "knowledge_graph", "baseline")
    assert result.baseline["captured"] is True


def test_quality_gate_mode_returns_completed_when_gate_passes():
    result = make_orchestrator(gate="pass").execute(
        JavaAnalysisCommand(
            projects=("api",),
            mode=JavaAnalysisMode.QUALITY_GATE,
        )
    )

    assert result.status is JavaAnalysisStatus.COMPLETED
    assert "quality_gate" in result.stages


def test_quality_gate_failure_blocks_later_execution():
    result = make_orchestrator(gate="fail").execute(
        JavaAnalysisCommand(
            projects=("api",),
            mode=JavaAnalysisMode.FULL,
            question="What depends on UserService?",
        )
    )

    assert result.blocked
    assert result.answer is None
    assert "retrieval" not in result.stages


def test_full_mode_returns_only_validated_provider_answer():
    result = make_orchestrator().execute(
        JavaAnalysisCommand(
            projects=("api", "core"),
            mode=JavaAnalysisMode.FULL,
            question="What depends on UserService?",
            metadata={"run_id": "test"},
        )
    )

    assert result.completed
    assert result.answer == "Validated answer. [E1]"
    assert result.stages[-3:] == (
        "retrieval",
        "llm_contract",
        "llm_provider",
    )


def test_invalid_provider_answer_is_blocked():
    result = make_orchestrator(provider=False).execute(
        JavaAnalysisCommand(
            projects=("api",),
            mode=JavaAnalysisMode.ASK,
            question="Explain UserService",
        )
    )

    assert result.status is JavaAnalysisStatus.BLOCKED
    assert result.answer is None
    assert "deterministic validation" in result.error


def test_missing_required_service_becomes_failed_execution():
    orchestrator = JavaProjectAnalysisOrchestrator(
        workspace_builder=WorkspaceBuilder(),
        knowledge_builder=KnowledgeBuilder(),
    )

    result = orchestrator.execute(
        JavaAnalysisCommand(
            projects=("api",),
            mode=JavaAnalysisMode.ASK,
            question="Explain UserService",
        )
    )

    assert result.status is JavaAnalysisStatus.FAILED
    assert "retrieval_service is required" in result.error
