from moughorai.java_llm_contract import (
    AnswerMode,
    JavaLlmAnswerValidator,
    JavaLlmContractService,
    ValidationSeverity,
)
from moughorai.java_retrieval.models import LlmContext


def context(text=None, unresolved=()):
    return LlmContext(
        "What depends on UserService?",
        text or "\n".join((
            "QUERY: What depends on UserService?",
            "",
            "PRIMARY SYMBOLS:",
            "[S1] type: com.acme.UserService; facets=service",
            "",
            "RELATED SYMBOLS:",
            "[R1] type: com.acme.UserController; facets=rest-controller",
            "",
            "RELATIONSHIPS:",
            "[E1] com.acme.UserController --injects--> com.acme.UserService",
        )),
        ("com.acme.UserService", "com.acme.UserController"),
        unresolved,
    )


def test_request_extracts_stable_evidence_ids():
    request = JavaLlmContractService().request(context())
    assert request.allowed_evidence_ids == ("S1", "R1", "E1")
    assert request.evidence[2].kind == "relationship"


def test_request_contains_strict_grounding_contract():
    request = JavaLlmContractService().request(context(), mode=AnswerMode.IMPACT)
    assert "Use only the supplied evidence" in request.system_prompt
    assert "ANSWER MODE: impact" in request.user_prompt
    assert "ALLOWED EVIDENCE IDS: S1, R1, E1" in request.user_prompt


def test_valid_cited_answer_passes():
    service = JavaLlmContractService()
    request = service.request(context())
    report = service.validate(request, "UserController depends on UserService. [E1]")
    assert report.valid
    assert report.cited_evidence_ids == ("E1",)


def test_unknown_citation_is_rejected():
    service = JavaLlmContractService()
    report = service.validate(service.request(context()), "A dependency exists. [E99]")
    assert not report.valid
    assert report.errors[0].code == "unknown-citation"


def test_substantive_uncited_answer_is_rejected():
    service = JavaLlmContractService()
    report = service.validate(service.request(context()), "UserController depends on UserService.")
    assert not report.valid
    assert any(item.code == "missing-citation" for item in report.findings)


def test_no_evidence_requires_insufficient_evidence_answer():
    empty = context("QUERY: Unknown symbol\n\nPRIMARY SYMBOLS:")
    service = JavaLlmContractService()
    request = service.request(empty)
    accepted = service.validate(request, "Insufficient evidence to answer this question.")
    rejected = service.validate(request, "The symbol has no dependencies.")
    assert accepted.valid
    assert not rejected.valid
    assert any(item.severity is ValidationSeverity.ERROR for item in rejected.findings)
