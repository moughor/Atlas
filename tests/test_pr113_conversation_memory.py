from datetime import datetime, timezone
from pathlib import Path

import pytest

from moughorai.ai_memory import (
    ConversationMemoryError,
    ConversationMemoryStore,
    ConversationRole,
)


NOW = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _store(tmp_path: Path) -> ConversationMemoryStore:
    return ConversationMemoryStore(tmp_path, clock=lambda: NOW)


def test_default_database_and_workspace_scoping(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.create("workspace-a", title="Architecture")
    store.create("workspace-b")
    assert store.path == tmp_path / ".atlas" / "conversation.sqlite3"
    assert store.list("workspace-a") == (first,)


def test_messages_preserve_order_and_structured_references(tmp_path: Path) -> None:
    store = _store(tmp_path)
    conversation = store.create("fingerprint")
    store.append(conversation.id, ConversationRole.USER, "Why?", references={"diagnostic": "A1"})
    store.append(conversation.id, ConversationRole.ASSISTANT, "Because.", references={"snapshot": "abc"})
    messages = store.messages(conversation.id)
    assert [message.position for message in messages] == [0, 1]
    assert dict(messages[0].references) == {"diagnostic": "A1"}


def test_unknown_conversation_and_empty_content_are_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ConversationMemoryError, match="content"):
        store.append(1, ConversationRole.USER, " ")
    with pytest.raises(ConversationMemoryError, match="unknown conversation"):
        store.append(999, ConversationRole.USER, "Hello")


def test_limits_are_deterministic(tmp_path: Path) -> None:
    store = _store(tmp_path)
    conversation = store.create("fingerprint")
    for value in ("one", "two", "three"):
        store.append(conversation.id, ConversationRole.USER, value)
    assert [item.content for item in store.messages(conversation.id, limit=2)] == ["one", "two"]
    with pytest.raises(ConversationMemoryError, match="non-negative"):
        store.messages(conversation.id, limit=-1)


def test_schema_mismatch_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.initialize()
    with store._connect() as connection:
        connection.execute("UPDATE atlas_ai_metadata SET value='99' WHERE key='schema_version'")
    with pytest.raises(ConversationMemoryError, match="unsupported"):
        store.initialize()
