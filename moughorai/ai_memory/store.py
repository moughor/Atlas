from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock
from typing import Callable

from .models import Conversation, ConversationMessage, ConversationRole


MEMORY_SCHEMA_VERSION = 1


class ConversationMemoryError(ValueError):
    """Raised when conversation memory is invalid or unavailable."""


class ConversationMemoryStore:
    def __init__(
        self,
        workspace_root: str | Path,
        path: str | Path | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(workspace_root).expanduser().resolve()
        self.path = Path(path or self.root / ".atlas" / "conversation.sqlite3")
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS atlas_ai_metadata (
                        key TEXT PRIMARY KEY, value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS conversations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        workspace_fingerprint TEXT NOT NULL,
                        title TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS conversation_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                        position INTEGER NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        references_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(conversation_id, position)
                    );
                    """
                )
                row = connection.execute(
                    "SELECT value FROM atlas_ai_metadata WHERE key='schema_version'"
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO atlas_ai_metadata(key,value) VALUES('schema_version',?)",
                        (str(MEMORY_SCHEMA_VERSION),),
                    )
                elif row[0] != str(MEMORY_SCHEMA_VERSION):
                    raise ConversationMemoryError(f"unsupported conversation schema: {row[0]}")
        except sqlite3.Error as exc:
            raise ConversationMemoryError(f"cannot initialize conversation memory: {exc}") from exc

    def create(self, workspace_fingerprint: str, *, title: str = "Atlas AI") -> Conversation:
        if not workspace_fingerprint.strip() or not title.strip():
            raise ConversationMemoryError("workspace fingerprint and title are required")
        timestamp = self._timestamp()
        self.initialize()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO conversations(workspace_fingerprint,title,created_at,updated_at) VALUES(?,?,?,?)",
                (workspace_fingerprint, title.strip(), timestamp, timestamp),
            )
            identifier = int(cursor.lastrowid)
        return Conversation(identifier, workspace_fingerprint, title.strip(), timestamp, timestamp)

    def append(
        self,
        conversation_id: int,
        role: ConversationRole,
        content: str,
        *,
        references: Mapping[str, str] | None = None,
    ) -> ConversationMessage:
        if not content.strip():
            raise ConversationMemoryError("message content is required")
        refs = dict(sorted((references or {}).items()))
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in refs.items()):
            raise ConversationMemoryError("message references must map strings to strings")
        timestamp = self._timestamp()
        self.initialize()
        try:
            with self._lock, self._connect() as connection:
                row = connection.execute(
                    "SELECT COALESCE(MAX(position),-1)+1 FROM conversation_messages WHERE conversation_id=?",
                    (conversation_id,),
                ).fetchone()
                position = int(row[0])
                cursor = connection.execute(
                    "INSERT INTO conversation_messages(conversation_id,position,role,content,references_json,created_at) VALUES(?,?,?,?,?,?)",
                    (conversation_id, position, role.value, content.strip(), json.dumps(refs, sort_keys=True), timestamp),
                )
                connection.execute(
                    "UPDATE conversations SET updated_at=? WHERE id=?",
                    (timestamp, conversation_id),
                )
                if connection.total_changes < 2:
                    raise ConversationMemoryError(f"unknown conversation: {conversation_id}")
                identifier = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ConversationMemoryError(f"unknown conversation: {conversation_id}") from exc
        return ConversationMessage(identifier, conversation_id, position, role, content.strip(), refs, timestamp)

    def messages(self, conversation_id: int, *, limit: int | None = None) -> tuple[ConversationMessage, ...]:
        if limit is not None and limit < 0:
            raise ConversationMemoryError("message limit must be non-negative")
        self.initialize()
        sql = "SELECT id,conversation_id,position,role,content,references_json,created_at FROM conversation_messages WHERE conversation_id=? ORDER BY position"
        params: tuple[object, ...] = (conversation_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params += (limit,)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return tuple(self._message(row) for row in rows)

    def list(self, workspace_fingerprint: str, *, limit: int = 20) -> tuple[Conversation, ...]:
        if limit < 0:
            raise ConversationMemoryError("conversation limit must be non-negative")
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,workspace_fingerprint,title,created_at,updated_at FROM conversations WHERE workspace_fingerprint=? ORDER BY updated_at DESC,id DESC LIMIT ?",
                (workspace_fingerprint, limit),
            ).fetchall()
        return tuple(Conversation(*row) for row in rows)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _timestamp(self) -> str:
        value = self.clock()
        if value.tzinfo is None:
            raise ConversationMemoryError("conversation clock must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _message(row: tuple[object, ...]) -> ConversationMessage:
        try:
            references = json.loads(str(row[5]))
            role = ConversationRole(str(row[3]))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ConversationMemoryError("stored conversation message is invalid") from exc
        if not isinstance(references, dict):
            raise ConversationMemoryError("stored message references are invalid")
        return ConversationMessage(
            int(row[0]), int(row[1]), int(row[2]), role, str(row[4]), references, str(row[6])
        )
