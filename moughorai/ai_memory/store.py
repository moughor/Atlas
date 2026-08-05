from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from threading import RLock
from typing import Callable

from moughorai.platform.safety import contains_absolute_path_text

from .models import (
    Conversation,
    ConversationMessage,
    ConversationRole,
    ConversationTurn,
    ConversationTurnStatus,
)


MEMORY_SCHEMA_VERSION = 1
_UNSAFE_PROVIDER_METADATA = re.compile(
    r"(?i)(?:\r|\n|```|[{}();=]|://|git@|"
    r"\b(?:api[ _-]?key|access[ _-]?token|auth[ _-]?token|"
    r"password|passwd|secret|credential)\b\s*[:= ]"
    r")"
)


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
                    CREATE TABLE IF NOT EXISTS conversation_turns (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                        position INTEGER NOT NULL,
                        workspace_fingerprint TEXT NOT NULL,
                        snapshot_id TEXT NOT NULL,
                        intent TEXT NOT NULL,
                        resolved_subject_ids_json TEXT NOT NULL,
                        context_digest TEXT NOT NULL,
                        evidence_ids_json TEXT NOT NULL,
                        truncated INTEGER NOT NULL,
                        provider TEXT NOT NULL,
                        model TEXT NOT NULL,
                        status TEXT NOT NULL,
                        limitations_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(conversation_id, position)
                    );
                    CREATE INDEX IF NOT EXISTS conversation_turns_workspace
                    ON conversation_turns(workspace_fingerprint, conversation_id, position);
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

    def get(self, conversation_id: int) -> Conversation | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id,workspace_fingerprint,title,created_at,updated_at "
                "FROM conversations WHERE id=?",
                (conversation_id,),
            ).fetchone()
        return None if row is None else Conversation(*row)

    def require_workspace(
        self,
        conversation_id: int,
        workspace_fingerprint: str,
    ) -> Conversation:
        fingerprint = workspace_fingerprint.strip()
        if not fingerprint:
            raise ConversationMemoryError("workspace fingerprint is required")
        conversation = self.get(conversation_id)
        if conversation is None:
            raise ConversationMemoryError(f"unknown conversation: {conversation_id}")
        if conversation.workspace_fingerprint != fingerprint:
            raise ConversationMemoryError(
                f"conversation {conversation_id} belongs to a different workspace"
            )
        return conversation

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

    def begin_turn(
        self,
        conversation_id: int,
        *,
        workspace_fingerprint: str,
        snapshot_id: str,
        intent: str,
        resolved_subject_ids: Iterable[str] = (),
        context_digest: str,
        evidence_ids: Iterable[str] = (),
        truncated: bool = False,
        provider: str = "",
        model: str = "",
        limitations: Iterable[str] = (),
    ) -> ConversationTurn:
        fingerprint = self._required_text(
            workspace_fingerprint, "workspace fingerprint"
        )
        snapshot = self._required_text(snapshot_id, "snapshot ID")
        normalized_intent = self._required_text(intent, "turn intent")
        digest = self._required_text(context_digest, "context digest")
        subjects = self._normalized_strings(
            resolved_subject_ids, "resolved subject IDs"
        )
        evidence = self._normalized_strings(evidence_ids, "evidence IDs")
        normalized_limitations = self._normalized_strings(
            limitations, "turn limitations"
        )
        normalized_provider = self._metadata_text(provider, "provider")
        normalized_model = self._metadata_text(model, "model")
        if not isinstance(truncated, bool):
            raise ConversationMemoryError("turn truncation must be boolean")
        timestamp = self._timestamp()
        self.initialize()
        try:
            with self._lock, self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                conversation = connection.execute(
                    "SELECT workspace_fingerprint FROM conversations WHERE id=?",
                    (conversation_id,),
                ).fetchone()
                if conversation is None:
                    raise ConversationMemoryError(
                        f"unknown conversation: {conversation_id}"
                    )
                if str(conversation[0]) != fingerprint:
                    raise ConversationMemoryError(
                        f"conversation {conversation_id} belongs to a different workspace"
                    )
                row = connection.execute(
                    "SELECT COALESCE(MAX(position),-1)+1 FROM conversation_turns "
                    "WHERE conversation_id=?",
                    (conversation_id,),
                ).fetchone()
                position = int(row[0])
                cursor = connection.execute(
                    "INSERT INTO conversation_turns("
                    "conversation_id,position,workspace_fingerprint,snapshot_id,"
                    "intent,resolved_subject_ids_json,context_digest,evidence_ids_json,"
                    "truncated,provider,model,status,limitations_json,created_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        conversation_id,
                        position,
                        fingerprint,
                        snapshot,
                        normalized_intent,
                        self._json_strings(subjects),
                        digest,
                        self._json_strings(evidence),
                        int(truncated),
                        normalized_provider,
                        normalized_model,
                        ConversationTurnStatus.RUNNING.value,
                        self._json_strings(normalized_limitations),
                        timestamp,
                        timestamp,
                    ),
                )
                connection.execute(
                    "UPDATE conversations SET updated_at=? WHERE id=?",
                    (timestamp, conversation_id),
                )
                identifier = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ConversationMemoryError(
                f"cannot begin conversation turn: {exc}"
            ) from exc
        return ConversationTurn(
            identifier,
            conversation_id,
            position,
            fingerprint,
            snapshot,
            normalized_intent,
            subjects,
            digest,
            evidence,
            truncated,
            normalized_provider,
            normalized_model,
            ConversationTurnStatus.RUNNING,
            normalized_limitations,
            timestamp,
            timestamp,
        )

    def complete_turn(
        self,
        turn_id: int,
        *,
        provider: str | None = None,
        model: str | None = None,
        limitations: Iterable[str] = (),
        message_content: str | None = None,
        message_references: Mapping[str, str] | None = None,
    ) -> ConversationTurn:
        return self._transition_turn(
            turn_id,
            ConversationTurnStatus.COMPLETED,
            limitations,
            provider=provider,
            model=model,
            message_content=message_content,
            message_references=message_references,
        )

    def fail_turn(
        self,
        turn_id: int,
        *,
        limitations: Iterable[str],
    ) -> ConversationTurn:
        normalized = self._normalized_strings(limitations, "turn limitations")
        if not normalized:
            raise ConversationMemoryError("failed turns require a limitation")
        return self._transition_turn(
            turn_id,
            ConversationTurnStatus.FAILED,
            normalized,
        )

    def turns(
        self,
        conversation_id: int,
        *,
        limit: int | None = None,
    ) -> tuple[ConversationTurn, ...]:
        if limit is not None and limit < 0:
            raise ConversationMemoryError("turn limit must be non-negative")
        self.initialize()
        sql = (
            "SELECT id,conversation_id,position,workspace_fingerprint,snapshot_id,"
            "intent,resolved_subject_ids_json,context_digest,evidence_ids_json,"
            "truncated,provider,model,status,limitations_json,created_at,updated_at "
            "FROM conversation_turns WHERE conversation_id=? ORDER BY position"
        )
        params: tuple[object, ...] = (conversation_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params += (limit,)
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return tuple(self._turn(row) for row in rows)

    def _transition_turn(
        self,
        turn_id: int,
        status: ConversationTurnStatus,
        limitations: Iterable[str],
        *,
        provider: str | None = None,
        model: str | None = None,
        message_content: str | None = None,
        message_references: Mapping[str, str] | None = None,
    ) -> ConversationTurn:
        additions = self._normalized_strings(limitations, "turn limitations")
        normalized_message = None
        normalized_references: dict[str, str] | None = None
        if message_content is not None:
            normalized_message = self._required_text(
                message_content, "turn message content"
            )
            normalized_references = dict(sorted(
                (message_references or {}).items()
            ))
            if any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in normalized_references.items()
            ):
                raise ConversationMemoryError(
                    "turn message references must map strings to strings"
                )
        elif message_references:
            raise ConversationMemoryError(
                "turn message references require message content"
            )
        timestamp = self._timestamp()
        self.initialize()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id,conversation_id,position,workspace_fingerprint,snapshot_id,"
                "intent,resolved_subject_ids_json,context_digest,evidence_ids_json,"
                "truncated,provider,model,status,limitations_json,created_at,updated_at "
                "FROM conversation_turns WHERE id=?",
                (turn_id,),
            ).fetchone()
            if row is None:
                raise ConversationMemoryError(f"unknown conversation turn: {turn_id}")
            current = self._turn(row)
            if current.status is not ConversationTurnStatus.RUNNING:
                raise ConversationMemoryError(
                    f"conversation turn {turn_id} is already {current.status.value}"
                )
            merged_limitations = tuple(sorted(set(
                (*current.limitations, *additions)
            )))
            updated_provider = (
                current.provider
                if provider is None
                else self._metadata_text(provider, "provider")
            )
            updated_model = (
                current.model
                if model is None
                else self._metadata_text(model, "model")
            )
            if normalized_message is not None and normalized_references is not None:
                message_position_row = connection.execute(
                    "SELECT COALESCE(MAX(position),-1)+1 "
                    "FROM conversation_messages WHERE conversation_id=?",
                    (current.conversation_id,),
                ).fetchone()
                connection.execute(
                    "INSERT INTO conversation_messages("
                    "conversation_id,position,role,content,references_json,created_at"
                    ") VALUES(?,?,?,?,?,?)",
                    (
                        current.conversation_id,
                        int(message_position_row[0]),
                        ConversationRole.ASSISTANT.value,
                        normalized_message,
                        json.dumps(normalized_references, sort_keys=True),
                        timestamp,
                    ),
                )
            connection.execute(
                "UPDATE conversation_turns SET status=?,provider=?,model=?,"
                "limitations_json=?,updated_at=? "
                "WHERE id=?",
                (
                    status.value,
                    updated_provider,
                    updated_model,
                    self._json_strings(merged_limitations),
                    timestamp,
                    turn_id,
                ),
            )
            connection.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (timestamp, current.conversation_id),
            )
        return ConversationTurn(
            current.id,
            current.conversation_id,
            current.position,
            current.workspace_fingerprint,
            current.snapshot_id,
            current.intent,
            current.resolved_subject_ids,
            current.context_digest,
            current.evidence_ids,
            current.truncated,
            updated_provider,
            updated_model,
            status,
            merged_limitations,
            current.created_at,
            timestamp,
        )

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
    def _required_text(value: object, label: str) -> str:
        normalized = ConversationMemoryStore._optional_text(value, label)
        if not normalized:
            raise ConversationMemoryError(f"{label} is required")
        return normalized

    @staticmethod
    def _optional_text(value: object, label: str) -> str:
        if not isinstance(value, str):
            raise ConversationMemoryError(f"{label} must be a string")
        normalized = value.strip()
        if "\x00" in normalized:
            raise ConversationMemoryError(f"{label} is invalid")
        return normalized

    @classmethod
    def _metadata_text(cls, value: object, label: str) -> str:
        normalized = cls._optional_text(value, label)
        if len(normalized) > 256:
            raise ConversationMemoryError(f"{label} is too long")
        if contains_absolute_path_text(normalized) or _UNSAFE_PROVIDER_METADATA.search(
            normalized
        ):
            raise ConversationMemoryError(f"{label} must be source-free")
        return normalized

    @classmethod
    def _normalized_strings(
        cls,
        values: Iterable[str],
        label: str,
    ) -> tuple[str, ...]:
        if isinstance(values, (str, bytes, bytearray)):
            raise ConversationMemoryError(f"{label} must be a sequence of strings")
        try:
            normalized = tuple(cls._required_text(value, label) for value in values)
        except TypeError as exc:
            raise ConversationMemoryError(
                f"{label} must be a sequence of strings"
            ) from exc
        return tuple(sorted(set(normalized)))

    @staticmethod
    def _json_strings(values: tuple[str, ...]) -> str:
        return json.dumps(values, ensure_ascii=False, separators=(",", ":"))

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

    @classmethod
    def _turn(cls, row: tuple[object, ...]) -> ConversationTurn:
        try:
            subjects = cls._stored_strings(
                row[6], "stored resolved subject IDs"
            )
            evidence = cls._stored_strings(row[8], "stored evidence IDs")
            limitations = cls._stored_strings(
                row[13], "stored turn limitations"
            )
            status = ConversationTurnStatus(str(row[12]))
            truncated = int(row[9])
        except (TypeError, ValueError) as exc:
            raise ConversationMemoryError(
                "stored conversation turn is invalid"
            ) from exc
        if truncated not in (0, 1):
            raise ConversationMemoryError("stored conversation turn is invalid")
        return ConversationTurn(
            int(row[0]),
            int(row[1]),
            int(row[2]),
            cls._required_text(row[3], "stored workspace fingerprint"),
            cls._required_text(row[4], "stored snapshot ID"),
            cls._required_text(row[5], "stored turn intent"),
            subjects,
            cls._required_text(row[7], "stored context digest"),
            evidence,
            bool(truncated),
            cls._metadata_text(row[10], "stored provider"),
            cls._metadata_text(row[11], "stored model"),
            status,
            limitations,
            cls._required_text(row[14], "stored turn creation timestamp"),
            cls._required_text(row[15], "stored turn update timestamp"),
        )

    @classmethod
    def _stored_strings(cls, value: object, label: str) -> tuple[str, ...]:
        try:
            decoded = json.loads(str(value))
        except json.JSONDecodeError as exc:
            raise ConversationMemoryError(f"{label} are invalid") from exc
        if not isinstance(decoded, list) or any(
            not isinstance(item, str) for item in decoded
        ):
            raise ConversationMemoryError(f"{label} are invalid")
        normalized = cls._normalized_strings(decoded, label)
        if list(normalized) != decoded:
            raise ConversationMemoryError(f"{label} are not canonical")
        return normalized
