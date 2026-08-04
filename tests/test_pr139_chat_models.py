from __future__ import annotations

import json

import pytest

from moughorai.ai import AtlasAiCapabilities
from moughorai.ai_ask import (
    AskEngine,
    AskRequest,
    AskResult,
    ChatCapability,
    ChatCapabilityState,
    ChatContext,
    ChatContextSection,
    ChatIntent,
    ChatSelection,
    CitationValidation,
    ChatEngine,
    ChatRequest,
    ChatResult,
)
from moughorai.semantic_evidence import EvidenceIndex, EvidenceKind, EvidenceRecord


SNAPSHOT_ID = "snapshot:pr139-models"
WORKSPACE_FINGERPRINT = "workspace:pr139-models"
SUBJECT_ID = "type:demo.Service"


def _evidence(subject_id: str, statement: str) -> EvidenceRecord:
    return EvidenceRecord.create(
        EvidenceKind.SEMANTIC_FACT,
        subject_id,
        "atlas-pr134/1",
        SNAPSHOT_ID,
        scope=subject_id,
        language="java",
        detail={"statement": statement},
    )


def _context(*, reverse: bool = False) -> ChatContext:
    service = _evidence(SUBJECT_ID, "Service participates in the API module.")
    project = _evidence("project:api", "The API project owns the service.")
    capabilities = (
        ChatCapability(
            "canonical_explanation",
            ChatCapabilityState.AVAILABLE,
            producer_ids=("atlas-pr134/1",),
        ),
        ChatCapability(
            "semantic_search",
            ChatCapabilityState.AVAILABLE,
            producer_ids=("atlas-pr135/1",),
        ),
        ChatCapability(
            "impact",
            ChatCapabilityState.NOT_REQUESTED,
            limitations=("Impact analysis was not requested.",),
        ),
    )
    sections = (
        ChatContextSection(
            "explain:subject",
            "canonical_explanation",
            "Resolved subject",
            {
                "subject": SUBJECT_ID,
                "facts": ("Service participates in the API module.",),
            },
            evidence_ids=(service.evidence_id,),
            priority=10,
            total_item_count=1,
            included_item_count=1,
        ),
        ChatContextSection(
            "explain:project",
            "semantic_search",
            "Project context",
            {
                "facts": ("The API project owns the service.",),
                "project": "project:api",
            },
            evidence_ids=(project.evidence_id,),
            priority=20,
            total_item_count=1,
            included_item_count=1,
        ),
    )
    section_ids = tuple(section.section_id for section in sections)
    return ChatContext(
        SNAPSHOT_ID,
        WORKSPACE_FINGERPRINT,
        ChatIntent.EXPLAIN,
        "Explain the API service.",
        tuple(reversed((SUBJECT_ID, "project:api"))) if reverse else (
            SUBJECT_ID,
            "project:api",
        ),
        tuple(reversed(capabilities)) if reverse else capabilities,
        tuple(reversed(sections)) if reverse else sections,
        EvidenceIndex(tuple(reversed((service, project))) if reverse else (
            service,
            project,
        )),
        ChatSelection(
            512,
            96,
            included_section_ids=(
                tuple(reversed(section_ids)) if reverse else section_ids
            ),
        ),
        limitations=("No raw source was selected.", "Call evidence is unavailable."),
        stale_history_count=1,
        history_message_count=3,
    )


def test_chat_leaf_models_have_exact_round_trips() -> None:
    capability = ChatCapability(
        "impact",
        ChatCapabilityState.NOT_REQUESTED,
        producer_ids=("atlas-pr136/1",),
        limitations=("Impact analysis was not requested.",),
    )
    capability_payload = {
        "name": "impact",
        "state": "not_requested",
        "producer_ids": ["atlas-pr136/1"],
        "limitations": ["Impact analysis was not requested."],
    }
    assert capability.to_dict() == capability_payload
    assert ChatCapability.from_dict(capability_payload) == capability

    selection = ChatSelection(
        512,
        96,
        included_section_ids=("explain:subject", "explain:project"),
        omitted_section_count=2,
        truncated=True,
    )
    selection_payload = {
        "token_budget": 512,
        "estimated_tokens": 96,
        "included_section_ids": ["explain:project", "explain:subject"],
        "omitted_section_count": 2,
        "truncated": True,
        "policy": "engineering-chat-context.v1",
    }
    assert selection.to_dict() == selection_payload
    assert ChatSelection.from_dict(selection_payload) == selection


def test_chat_context_round_trip_and_reordered_inputs_are_deterministic() -> None:
    context = _context()
    reordered = _context(reverse=True)

    assert reordered == context
    assert reordered.to_dict() == context.to_dict()
    assert reordered.to_json() == context.to_json()
    assert json.loads(context.to_json()) == context.to_dict()
    assert ChatContext.from_dict(context.to_dict()) == context
    assert ChatContext.from_dict(context.to_dict()).to_dict() == context.to_dict()
    assert context.context_digest
    assert len(context.context_digest) == 64


def test_chat_context_rejects_absolute_paths_at_source_free_boundary() -> None:
    with pytest.raises(ValueError, match="source-free|absolute path"):
        ChatContextSection(
            "explain:unsafe",
            "explain",
            "Unsafe context",
            {"path": r"C:\Users\alice\private\Secret.java"},
        )

    payload = _context().to_dict()
    payload["question"] = "/home/alice/private/Secret.java"
    payload["context_digest"] = ""
    with pytest.raises(ValueError, match="source-free|absolute path"):
        ChatContext.from_dict(payload)


def test_chat_context_rejects_missing_section_evidence() -> None:
    section = ChatContextSection(
        "explain:missing-evidence",
        "explain",
        "Missing evidence",
        {"status": "insufficient"},
        evidence_ids=("evidence:" + "f" * 64,),
        total_item_count=1,
        included_item_count=1,
    )
    with pytest.raises(ValueError, match="evidence"):
        ChatContext(
            SNAPSHOT_ID,
            WORKSPACE_FINGERPRINT,
            ChatIntent.EXPLAIN,
            "Explain the unresolved subject.",
            (),
            (
                ChatCapability(
                    "explain",
                    ChatCapabilityState.PARTIAL,
                    limitations=("Evidence is incomplete.",),
                ),
            ),
            (section,),
            EvidenceIndex(),
            ChatSelection(
                256,
                24,
                included_section_ids=(section.section_id,),
            ),
        )


def test_chat_context_rejects_an_inconsistent_context_digest() -> None:
    payload = _context().to_dict()
    original_digest = payload["context_digest"]
    payload["question"] = "Explain a different subject."

    with pytest.raises(ValueError, match="context digest"):
        ChatContext.from_dict(payload)

    assert payload["context_digest"] == original_digest


def test_citation_validation_preserves_unknown_citations() -> None:
    known = "evidence:" + "a" * 64
    unknown = "evidence:" + "b" * 64
    validation = CitationValidation(
        cited_evidence_ids=(unknown, known),
        accepted_evidence_ids=(known,),
        unknown_citation_ids=(unknown,),
    )
    expected = {
        "cited_evidence_ids": [known, unknown],
        "accepted_evidence_ids": [known],
        "unknown_citation_ids": [unknown],
        "missing_required": False,
        "valid": False,
    }

    assert validation.valid is False
    assert validation.to_dict() == expected
    assert CitationValidation.from_dict(expected) == validation
    assert CitationValidation(
        cited_evidence_ids=(known,),
        accepted_evidence_ids=(known,),
    ).valid is True
    assert CitationValidation(missing_required=True).valid is False


def test_grounded_result_requires_an_accepted_atlas_evidence_id() -> None:
    assert AskResult("Unavailable.", SNAPSHOT_ID, None).grounded is False

    context = _context()
    known = context.evidence_index.records[0].evidence_id
    result = AskResult(
        f"Supported by {known}.",
        SNAPSHOT_ID,
        None,
        context,
        citations=CitationValidation(
            cited_evidence_ids=(known,),
            accepted_evidence_ids=(known,),
        ),
    )
    assert result.grounded is True

    payload = result.to_dict()
    payload["grounded"] = False
    with pytest.raises(ValueError, match="grounding is inconsistent"):
        AskResult.from_dict(payload)


def test_grounding_requires_retained_required_and_requested_sections() -> None:
    base = _context()
    explanation = next(
        section
        for section in base.sections
        if section.capability == "canonical_explanation"
    )
    explanation_evidence = EvidenceIndex(tuple(
        record
        for record in base.evidence_index.records
        if record.evidence_id in explanation.evidence_ids
    ))
    without_search = ChatContext(
        base.snapshot_id,
        base.workspace_fingerprint,
        base.intent,
        base.question,
        base.subject_ids,
        base.capabilities,
        (explanation,),
        explanation_evidence,
        ChatSelection(512, 96, (explanation.section_id,), 1, True),
        base.limitations,
    )
    known = explanation.evidence_ids[0]
    citation = CitationValidation((known,), (known,))

    assert AskResult(
        f"Supported by {known}.",
        SNAPSHOT_ID,
        None,
        without_search,
        citation,
    ).grounded is False

    optional_omitted = ChatContext(
        base.snapshot_id,
        base.workspace_fingerprint,
        base.intent,
        base.question,
        base.subject_ids,
        (*base.capabilities, ChatCapability(
            "security_intelligence",
            ChatCapabilityState.AVAILABLE,
        )),
        base.sections,
        base.evidence_index,
        ChatSelection(
            512,
            96,
            tuple(section.section_id for section in base.sections),
            1,
            True,
        ),
        base.limitations,
    )
    assert AskResult(
        f"The service is secure. {known}",
        SNAPSHOT_ID,
        None,
        optional_omitted,
        citation,
    ).grounded is False


def test_ask_result_rejects_citations_outside_the_selected_context() -> None:
    foreign = "evidence:" + "f" * 64
    with pytest.raises(ValueError, match="selected context"):
        AskResult(
            f"Unsupported {foreign}.",
            SNAPSHOT_ID,
            None,
            _context(),
            CitationValidation(
                cited_evidence_ids=(foreign,),
                accepted_evidence_ids=(foreign,),
            ),
        )


def test_context_bearing_result_rejects_unsafe_answer_and_limitations() -> None:
    context = _context()
    known = context.evidence_index.records[0].evidence_id
    citations = CitationValidation((known,), (known,))

    with pytest.raises(ValueError, match="answer must be source-free"):
        AskResult(
            f"password=hunter2 {known}",
            SNAPSHOT_ID,
            None,
            context,
            citations,
        )
    with pytest.raises(ValueError, match="limitations must be source-free"):
        AskResult(
            f"Supported by {known}.",
            SNAPSHOT_ID,
            None,
            context,
            citations,
            limitations=(r"Model at C:\private\secret.gguf",),
        )

    payload = AskResult(
        f"Supported by {known}.",
        SNAPSHOT_ID,
        None,
        context,
        citations,
    ).to_dict()
    payload["answer"] = f"secret hunter2 {known}"
    with pytest.raises(ValueError, match="answer must be source-free"):
        AskResult.from_dict(payload)


def test_million_candidate_metadata_remains_a_compact_bounded_context() -> None:
    evidence = _evidence(SUBJECT_ID, "One selected fact.")
    context = ChatContext(
        SNAPSHOT_ID,
        WORKSPACE_FINGERPRINT,
        ChatIntent.SEARCH,
        "Find the selected fact.",
        (SUBJECT_ID,),
        (ChatCapability("semantic_search", ChatCapabilityState.PARTIAL),),
        (
            ChatContextSection(
                "semantic_search",
                "semantic_search",
                "Bounded search",
                {"hits": [{"subject_id": SUBJECT_ID}]},
                (evidence.evidence_id,),
                total_item_count=1_000_000,
                included_item_count=1,
                omitted_item_count=999_999,
            ),
        ),
        EvidenceIndex((evidence,)),
        ChatSelection(
            7_000,
            256,
            ("semantic_search",),
            truncated=True,
        ),
    )

    encoded = context.to_json().encode("utf-8")
    assert len(encoded) < 4_096
    assert ChatContext.from_dict(context.to_dict()).to_json() == context.to_json()


def test_nested_chat_section_content_is_deeply_immutable() -> None:
    section = ChatContextSection(
        "immutable",
        "semantic_search",
        "Immutable content",
        {"nested": {"value": 1}, "values": [1, 2]},
    )

    nested = section.content["nested"]
    values = section.content["values"]
    with pytest.raises(TypeError):
        nested["value"] = 2  # type: ignore[index]
    with pytest.raises(AttributeError):
        values.append(3)  # type: ignore[union-attr]
    assert ChatContextSection.from_dict(section.to_dict()) == section


def test_ai_capability_addition_preserves_the_legacy_positional_signature() -> None:
    capabilities = AtlasAiCapabilities(
        True,
        True,
        True,
        True,
        True,
        True,
        False,
        False,
        False,
        ("legacy-provider",),
    )

    assert capabilities.patch is False
    assert capabilities.git_context is False
    assert capabilities.ide_protocol is False
    assert capabilities.providers == ("legacy-provider",)
    assert capabilities.engineering_chat is True


@pytest.mark.parametrize(
    "payload",
    (
        {"question": 42},
        {"question": "Explain.", "history_limit": True},
        {"question": "Explain.", "result_limit": 1.9},
        {"question": "Explain.", "capabilities": [1]},
    ),
)
def test_ask_request_deserialization_rejects_coercible_invalid_types(
    payload: dict[str, object],
) -> None:
    with pytest.raises(TypeError):
        AskRequest.from_dict(payload)


def test_chat_section_rejects_non_finite_json_values() -> None:
    with pytest.raises(TypeError, match="deterministic JSON"):
        ChatContextSection(
            "invalid",
            "semantic_search",
            "Invalid",
            {"score": float("nan")},
        )


@pytest.mark.parametrize(
    "unsafe",
    (
        'package main\nfunc main() { fmt.Println("secret") }',
        'password="alpha beta"',
        'void run() { doThing(); }',
        'String value = service.load();',
        'credential="alpha beta"',
        'client_secret="alpha beta"',
        'DATABASE_PASSWORD="alpha beta"',
        "override fun run() = service.execute()",
        "private def run(): Unit = service.execute()",
        "https://private.example/repo.git",
    ),
)
def test_structured_chat_content_rejects_source_secrets_and_private_remotes(
    unsafe: str,
) -> None:
    with pytest.raises(ValueError, match="unsafe source or private data"):
        ChatContextSection(
            "unsafe",
            "semantic_search",
            "Unsafe",
            {"value": unsafe},
        )


def test_full_chat_envelope_rejects_unsafe_capabilities_and_evidence() -> None:
    with pytest.raises(ValueError, match="source-free"):
        ChatCapability(
            "unsafe",
            ChatCapabilityState.PARTIAL,
            limitations=('client_secret="alpha beta"',),
        )

    unsafe_evidence = EvidenceRecord.create(
        EvidenceKind.SEMANTIC_FACT,
        SUBJECT_ID,
        "atlas-pr134/1",
        SNAPSHOT_ID,
        scope=SUBJECT_ID,
        detail={"statement": "password=hunter2; def leak(): return secret"},
    )
    section = ChatContextSection(
        "unsafe_evidence",
        "semantic_search",
        "Unsafe evidence",
        {"status": "partial"},
        (unsafe_evidence.evidence_id,),
    )
    with pytest.raises(ValueError, match="unsafe source or private data"):
        ChatContext(
            SNAPSHOT_ID,
            WORKSPACE_FINGERPRINT,
            ChatIntent.SEARCH,
            "Find the subject.",
            (SUBJECT_ID,),
            (
                ChatCapability(
                    "semantic_search",
                    ChatCapabilityState.PARTIAL,
                ),
                ChatCapability(
                    "canonical_explanation",
                    ChatCapabilityState.PARTIAL,
                ),
            ),
            (section,),
            EvidenceIndex((unsafe_evidence,)),
            ChatSelection(1_024, 128, ("unsafe_evidence",)),
        )


def test_security_capability_wording_is_not_mistaken_for_a_secret() -> None:
    capability = ChatCapability(
        "security_intelligence",
        ChatCapabilityState.PARTIAL,
        limitations=(
            "Token validation is unavailable.",
            "Secret detection is unavailable.",
        ),
    )
    assert capability.state is ChatCapabilityState.PARTIAL


def test_existing_ask_contract_is_extended_additively_and_round_trips() -> None:
    legacy = AskRequest("Explain Service", 7, 3)
    restored = AskRequest.from_dict(legacy.to_dict())
    assert restored == legacy
    assert legacy.subject is None
    assert legacy.capabilities == ()
    assert ChatEngine is AskEngine
    assert ChatRequest is AskRequest
    assert ChatResult is AskResult

    result = AskResult(
        "Grounded response.",
        SNAPSHOT_ID,
        7,
        _context(),
        CitationValidation(missing_required=True),
        "scripted",
        "test",
        ("Provider response did not cite selected evidence.",),
    )
    assert AskResult.from_dict(result.to_dict()) == result
    assert result.grounded is False

    legacy_result = AskResult(
        "Legacy prose may mention evidence:" + "a" * 64,
        SNAPSHOT_ID,
        7,
    )
    assert legacy_result.grounded is False
