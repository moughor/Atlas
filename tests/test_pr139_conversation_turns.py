from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from moughorai.ai_memory import (
    ConversationMemoryError,
    ConversationMemoryStore,
    ConversationRole,
    ConversationTurnStatus,
)
from moughorai.ai_memory.store import MEMORY_SCHEMA_VERSION


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 4, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


def _store(tmp_path: Path) -> ConversationMemoryStore:
    return ConversationMemoryStore(tmp_path, clock=_Clock())


def _begin(
    store: ConversationMemoryStore,
    conversation_id: int,
    **overrides: object,
):
    values = {
        "workspace_fingerprint": "workspace-a",
        "snapshot_id": "snapshot-1",
        "intent": "explain",
        "resolved_subject_ids": ("type:z", "type:a", "type:z"),
        "context_digest": "digest-1",
        "evidence_ids": ("evidence:z", "evidence:a", "evidence:z"),
        "truncated": True,
        "provider": "ollama",
        "model": "model-a",
        "limitations": ("z limitation", "a limitation", "z limitation"),
    }
    values.update(overrides)
    return store.begin_turn(conversation_id, **values)


def test_schema_v1_additively_creates_turn_table_without_losing_memory(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation = store.create("workspace-a", title="Existing")
    message = store.append(
        conversation.id,
        ConversationRole.USER,
        "Existing message",
    )
    with store._connect() as connection:
        connection.execute("DROP TABLE conversation_turns")

    store.initialize()

    with store._connect() as connection:
        version = connection.execute(
            "SELECT value FROM atlas_ai_metadata WHERE key='schema_version'"
        ).fetchone()[0]
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='conversation_turns'"
        ).fetchone()
    assert MEMORY_SCHEMA_VERSION == 1
    assert version == "1"
    assert table == ("conversation_turns",)
    assert store.get(conversation.id) is not None
    assert store.messages(conversation.id) == (message,)


def test_turn_lifecycle_is_immutable_canonical_and_replayable(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation = store.create("workspace-a")

    running = _begin(store, conversation.id)

    assert running.position == 0
    assert running.status is ConversationTurnStatus.RUNNING
    assert running.resolved_subject_ids == ("type:a", "type:z")
    assert running.evidence_ids == ("evidence:a", "evidence:z")
    assert running.limitations == ("a limitation", "z limitation")
    with pytest.raises(FrozenInstanceError):
        running.intent = "changed"  # type: ignore[misc]

    completed = store.complete_turn(
        running.id,
        limitations=("completion limitation", "a limitation"),
    )

    assert completed.status is ConversationTurnStatus.COMPLETED
    assert completed.limitations == (
        "a limitation",
        "completion limitation",
        "z limitation",
    )
    assert completed.created_at == running.created_at
    assert completed.updated_at > running.updated_at
    assert store.turns(conversation.id) == (completed,)


def test_completion_atomically_records_the_assistant_message(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation = store.create("workspace-a")
    running = _begin(store, conversation.id, limitations=())

    completed = store.complete_turn(
        running.id,
        provider="scripted",
        model="deterministic",
        message_content="Evidence-backed answer.",
        message_references={"citation_status": "valid", "turn": str(running.id)},
    )

    messages = store.messages(conversation.id)
    assert completed.status is ConversationTurnStatus.COMPLETED
    assert completed.provider == "scripted"
    assert completed.model == "deterministic"
    assert len(messages) == 1
    assert messages[0].role is ConversationRole.ASSISTANT
    assert messages[0].content == "Evidence-backed answer."
    assert dict(messages[0].references) == {
        "citation_status": "valid",
        "turn": str(running.id),
    }


def test_invalid_completion_message_leaves_the_turn_running(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation = store.create("workspace-a")
    running = _begin(store, conversation.id, limitations=())

    with pytest.raises(ConversationMemoryError, match="map strings to strings"):
        store.complete_turn(
            running.id,
            message_content="Answer.",
            message_references={"invalid": 1},  # type: ignore[dict-item]
        )

    assert store.turns(conversation.id) == (running,)
    assert store.messages(conversation.id) == ()


def test_failed_turn_requires_reason_and_terminal_transitions_are_final(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation = store.create("workspace-a")
    running = _begin(store, conversation.id, limitations=())

    with pytest.raises(ConversationMemoryError, match="require a limitation"):
        store.fail_turn(running.id, limitations=())

    failed = store.fail_turn(
        running.id,
        limitations=("provider unavailable",),
    )

    assert failed.status is ConversationTurnStatus.FAILED
    assert failed.limitations == ("provider unavailable",)
    with pytest.raises(ConversationMemoryError, match="already failed"):
        store.complete_turn(running.id)
    with pytest.raises(ConversationMemoryError, match="unknown conversation turn"):
        store.complete_turn(999)


def test_workspace_ownership_is_required_for_conversations_and_turns(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation = store.create("workspace-a")

    assert store.get(conversation.id) == conversation
    assert store.get(999) is None
    assert store.require_workspace(conversation.id, "workspace-a") == conversation
    with pytest.raises(ConversationMemoryError, match="different workspace"):
        store.require_workspace(conversation.id, "workspace-b")
    with pytest.raises(ConversationMemoryError, match="unknown conversation"):
        store.require_workspace(999, "workspace-a")
    with pytest.raises(ConversationMemoryError, match="different workspace"):
        _begin(
            store,
            conversation.id,
            workspace_fingerprint="workspace-b",
        )
    assert store.turns(conversation.id) == ()


def test_turn_order_limits_and_input_order_are_deterministic(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation = store.create("workspace-a")
    first = _begin(store, conversation.id)
    second = _begin(
        store,
        conversation.id,
        snapshot_id="snapshot-2",
        resolved_subject_ids=tuple(reversed(first.resolved_subject_ids)),
        evidence_ids=tuple(reversed(first.evidence_ids)),
        limitations=tuple(reversed(first.limitations)),
    )
    third = _begin(store, conversation.id, snapshot_id="snapshot-3")

    turns = store.turns(conversation.id)
    assert [item.id for item in turns] == [first.id, second.id, third.id]
    assert second.resolved_subject_ids == first.resolved_subject_ids
    assert second.evidence_ids == first.evidence_ids
    assert second.limitations == first.limitations
    assert store.turns(conversation.id, limit=2) == (first, second)
    assert store.turns(conversation.id, limit=0) == ()
    with pytest.raises(ConversationMemoryError, match="non-negative"):
        store.turns(conversation.id, limit=-1)


def test_turn_storage_rejects_noncanonical_or_invalid_metadata(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation = store.create("workspace-a")

    with pytest.raises(ConversationMemoryError, match="context digest is required"):
        _begin(store, conversation.id, context_digest=" ")
    with pytest.raises(ConversationMemoryError, match="sequence of strings"):
        _begin(store, conversation.id, evidence_ids="evidence:a")
    with pytest.raises(ConversationMemoryError, match="truncation must be boolean"):
        _begin(store, conversation.id, truncated=1)

    running = _begin(store, conversation.id)
    with store._connect() as connection:
        connection.execute(
            "UPDATE conversation_turns SET evidence_ids_json=? WHERE id=?",
            ('["evidence:z","evidence:a"]', running.id),
        )

    with pytest.raises(ConversationMemoryError, match="stored conversation turn"):
        store.turns(conversation.id)


def test_turn_provider_metadata_rejects_machine_paths_and_private_data(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation = store.create("workspace-a")

    with pytest.raises(ConversationMemoryError, match="source-free"):
        _begin(
            store,
            conversation.id,
            model=r"C:\private\models\secret.gguf",
        )
    with pytest.raises(ConversationMemoryError, match="source-free"):
        _begin(
            store,
            conversation.id,
            provider="api_key=hunter2",
        )
