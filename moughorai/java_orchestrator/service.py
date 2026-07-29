from __future__ import annotations

from typing import Any

from .models import (
    JavaAnalysisCommand,
    JavaAnalysisExecution,
    JavaAnalysisMode,
    JavaAnalysisStatus,
)
from .protocols import (
    BaselineService,
    KnowledgeBuilder,
    LlmContractService,
    LlmProviderService,
    QualityGateService,
    RetrievalService,
    WorkspaceBuilder,
)


class JavaProjectAnalysisOrchestrator:
    """Coordinate deterministic Java analysis and validated LLM execution.

    The orchestrator deliberately depends on protocols instead of concrete
    phase implementations. This keeps Phase 20 additive and makes every stage
    independently replaceable and testable.
    """

    def __init__(
        self,
        *,
        workspace_builder: WorkspaceBuilder,
        knowledge_builder: KnowledgeBuilder,
        baseline_service: BaselineService | None = None,
        quality_gate_service: QualityGateService | None = None,
        retrieval_service: RetrievalService | None = None,
        llm_contract_service: LlmContractService | None = None,
        llm_provider_service: LlmProviderService | None = None,
    ) -> None:
        self._workspace_builder = workspace_builder
        self._knowledge_builder = knowledge_builder
        self._baseline_service = baseline_service
        self._quality_gate_service = quality_gate_service
        self._retrieval_service = retrieval_service
        self._llm_contract_service = llm_contract_service
        self._llm_provider_service = llm_provider_service

    def execute(self, command: JavaAnalysisCommand) -> JavaAnalysisExecution:
        stages: list[str] = []
        workspace = None
        graph = None
        baseline = None
        gate = None
        retrieval = None
        request = None
        result = None

        try:
            workspace = self._workspace_builder.build(command.projects)
            stages.append("workspace")

            graph = self._knowledge_builder.build(workspace)
            stages.append("knowledge_graph")

            if self._baseline_service is not None:
                baseline = self._baseline_service.capture(
                    workspace,
                    command.policy,
                )
                stages.append("baseline")

            if command.mode in {
                JavaAnalysisMode.QUALITY_GATE,
                JavaAnalysisMode.FULL,
            }:
                self._require(
                    self._quality_gate_service,
                    "quality_gate_service",
                )
                gate = self._quality_gate_service.evaluate(
                    workspace,
                    baseline=command.baseline,
                    policy=command.policy,
                    changed_symbols=command.changed_symbols,
                )
                stages.append("quality_gate")
                if self._is_gate_blocking(gate):
                    return JavaAnalysisExecution(
                        status=JavaAnalysisStatus.BLOCKED,
                        workspace=workspace,
                        knowledge_graph=graph,
                        baseline=baseline,
                        quality_gate=gate,
                        stages=tuple(stages),
                        error="The deterministic quality gate blocked execution.",
                    )

            if command.mode in {JavaAnalysisMode.ASK, JavaAnalysisMode.FULL}:
                if command.question is None:
                    return JavaAnalysisExecution(
                        status=JavaAnalysisStatus.COMPLETED,
                        workspace=workspace,
                        knowledge_graph=graph,
                        baseline=baseline,
                        quality_gate=gate,
                        stages=tuple(stages),
                    )

                self._require(self._retrieval_service, "retrieval_service")
                self._require(
                    self._llm_contract_service,
                    "llm_contract_service",
                )
                self._require(
                    self._llm_provider_service,
                    "llm_provider_service",
                )

                retrieval = self._retrieval_service.retrieve(
                    graph,
                    command.question,
                )
                context = self._retrieval_service.context(
                    graph,
                    command.question,
                )
                stages.append("retrieval")

                request = self._llm_contract_service.request(
                    context,
                    mode=command.answer_mode,
                )
                stages.append("llm_contract")

                result = self._llm_provider_service.execute(
                    request,
                    metadata=command.metadata,
                )
                stages.append("llm_provider")

                if not bool(getattr(result, "accepted", False)):
                    return JavaAnalysisExecution(
                        status=JavaAnalysisStatus.BLOCKED,
                        workspace=workspace,
                        knowledge_graph=graph,
                        baseline=baseline,
                        quality_gate=gate,
                        retrieval=retrieval,
                        llm_request=request,
                        llm_result=result,
                        stages=tuple(stages),
                        error="No provider answer passed deterministic validation.",
                    )

                return JavaAnalysisExecution(
                    status=JavaAnalysisStatus.COMPLETED,
                    workspace=workspace,
                    knowledge_graph=graph,
                    baseline=baseline,
                    quality_gate=gate,
                    retrieval=retrieval,
                    llm_request=request,
                    llm_result=result,
                    answer=getattr(result, "answer", None),
                    stages=tuple(stages),
                )

            return JavaAnalysisExecution(
                status=JavaAnalysisStatus.COMPLETED,
                workspace=workspace,
                knowledge_graph=graph,
                baseline=baseline,
                quality_gate=gate,
                stages=tuple(stages),
            )

        except Exception as exc:
            return JavaAnalysisExecution(
                status=JavaAnalysisStatus.FAILED,
                workspace=workspace,
                knowledge_graph=graph,
                baseline=baseline,
                quality_gate=gate,
                retrieval=retrieval,
                llm_request=request,
                llm_result=result,
                stages=tuple(stages),
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _require(value: Any, name: str) -> None:
        if value is None:
            raise RuntimeError(f"{name} is required for this analysis mode")

    @staticmethod
    def _is_gate_blocking(gate: Any) -> bool:
        status = getattr(gate, "status", None)
        if status is None:
            return False
        value = getattr(status, "value", status)
        return str(value).lower() == "fail"
