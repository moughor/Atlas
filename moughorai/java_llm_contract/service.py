"""High-level facade for prompt construction and grounded-answer validation."""
from __future__ import annotations

from moughorai.java_retrieval.models import LlmContext
from moughorai.java_llm_contract.builder import JavaLlmRequestBuilder
from moughorai.java_llm_contract.models import AnswerMode, AnswerValidationReport, JavaLlmAnswer, JavaLlmRequest
from moughorai.java_llm_contract.validator import JavaLlmAnswerValidator


class JavaLlmContractService:
    def __init__(
        self,
        builder: JavaLlmRequestBuilder | None = None,
        validator: JavaLlmAnswerValidator | None = None,
    ) -> None:
        self._builder = builder or JavaLlmRequestBuilder()
        self._validator = validator or JavaLlmAnswerValidator()

    def request(self, context: LlmContext, *, mode: AnswerMode = AnswerMode.FACTUAL) -> JavaLlmRequest:
        return self._builder.build(context, mode=mode)

    def validate(self, request: JavaLlmRequest, answer: JavaLlmAnswer | str) -> AnswerValidationReport:
        return self._validator.validate(request, answer)
