"""Atlas governance policies and tamper-evident audit records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any


class GovernanceError(ValueError):
    """Raised when governance policy or audit data is invalid."""


class GovernanceRole(str, Enum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    ADMIN = "admin"


class GovernanceAction(str, Enum):
    VIEW = "view"
    ANALYZE = "analyze"
    APPLY_FIX = "apply_fix"
    DISTRIBUTE = "distribute"
    CONFIGURE = "configure"
    MANAGE_RULES = "manage_rules"


_PERMISSIONS = {
    GovernanceRole.VIEWER: frozenset({GovernanceAction.VIEW}),
    GovernanceRole.ANALYST: frozenset({
        GovernanceAction.VIEW,
        GovernanceAction.ANALYZE,
        GovernanceAction.APPLY_FIX,
    }),
    GovernanceRole.ADMIN: frozenset(GovernanceAction),
}


@dataclass(frozen=True, slots=True)
class GovernancePrincipal:
    principal_id: str
    role: GovernanceRole

    def __post_init__(self) -> None:
        if not self.principal_id.strip():
            raise GovernanceError("principal id must not be empty")


@dataclass(frozen=True, slots=True)
class GovernancePolicy:
    allowed_projects: tuple[str, ...] = ()
    maximum_workers: int = 0
    allow_force_analysis: bool = False

    def __post_init__(self) -> None:
        if self.maximum_workers < 0:
            raise GovernanceError("maximum workers must be non-negative")
        object.__setattr__(self, "allowed_projects", tuple(sorted(set(self.allowed_projects))))

    @classmethod
    def from_options(cls, options: Mapping[str, Any]) -> "GovernancePolicy":
        projects = str(options.get("governance.allowed_projects", "")).split(",")
        allowed = tuple(value.strip() for value in projects if value.strip())
        try:
            workers = int(options.get("governance.maximum_workers", 0))
        except (TypeError, ValueError) as exc:
            raise GovernanceError("governance.maximum_workers must be an integer") from exc
        force = str(options.get("governance.allow_force_analysis", "false")).lower()
        if force not in {"true", "false"}:
            raise GovernanceError("governance.allow_force_analysis must be true or false")
        return cls(allowed, workers, force == "true")


@dataclass(frozen=True, slots=True)
class GovernanceDecision:
    principal_id: str
    role: GovernanceRole
    action: GovernanceAction
    allowed: bool
    reason: str
    project: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "principal_id": self.principal_id,
            "role": self.role.value,
            "action": self.action.value,
            "allowed": self.allowed,
            "reason": self.reason,
            "project": self.project,
        }


class GovernanceEngine:
    def __init__(self, policy: GovernancePolicy | None = None) -> None:
        self.policy = policy or GovernancePolicy()

    def authorize(
        self,
        principal: GovernancePrincipal,
        action: GovernanceAction | str,
        *,
        project: str | None = None,
        workers: int = 1,
        force: bool = False,
    ) -> GovernanceDecision:
        selected = GovernanceAction(action)
        if selected not in _PERMISSIONS[principal.role]:
            return self._decision(principal, selected, False, "role-does-not-permit-action", project)
        if project is not None and self.policy.allowed_projects and project not in self.policy.allowed_projects:
            return self._decision(principal, selected, False, "project-is-not-allowed", project)
        if workers < 1:
            raise GovernanceError("workers must be at least one")
        if self.policy.maximum_workers and workers > self.policy.maximum_workers:
            return self._decision(principal, selected, False, "worker-limit-exceeded", project)
        if force and not self.policy.allow_force_analysis:
            return self._decision(principal, selected, False, "force-analysis-is-disabled", project)
        return self._decision(principal, selected, True, "allowed", project)

    @staticmethod
    def _decision(
        principal: GovernancePrincipal,
        action: GovernanceAction,
        allowed: bool,
        reason: str,
        project: str | None,
    ) -> GovernanceDecision:
        return GovernanceDecision(principal.principal_id, principal.role, action, allowed, reason, project)


@dataclass(frozen=True, slots=True)
class AuditRecord:
    sequence: int
    timestamp: str
    decision: GovernanceDecision
    previous_hash: str
    record_hash: str


class GovernanceAuditLog:
    """Append-only JSONL audit log with a SHA-256 hash chain."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self._lock = RLock()

    def append(self, decision: GovernanceDecision, *, timestamp: str | None = None) -> AuditRecord:
        with self._lock:
            records = self.load()
            sequence = len(records) + 1
            previous = records[-1].record_hash if records else "0" * 64
            value = {
                "sequence": sequence,
                "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
                "decision": decision.to_dict(),
                "previous_hash": previous,
            }
            record_hash = self._hash(value)
            line = json.dumps({**value, "record_hash": record_hash}, sort_keys=True, separators=(",", ":")) + "\n"
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
            return AuditRecord(sequence, str(value["timestamp"]), decision, previous, record_hash)

    def load(self) -> tuple[AuditRecord, ...]:
        if not self.path.exists():
            return ()
        records: list[AuditRecord] = []
        previous = "0" * 64
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            for expected, line in enumerate(lines, 1):
                raw = json.loads(line)
                decision_raw = raw["decision"]
                value = {
                    "sequence": raw["sequence"],
                    "timestamp": raw["timestamp"],
                    "decision": decision_raw,
                    "previous_hash": raw["previous_hash"],
                }
                if raw["sequence"] != expected or raw["previous_hash"] != previous:
                    raise GovernanceError(f"audit chain is inconsistent at sequence {expected}")
                if raw["record_hash"] != self._hash(value):
                    raise GovernanceError(f"audit record checksum mismatch at sequence {expected}")
                decision = GovernanceDecision(
                    str(decision_raw["principal_id"]),
                    GovernanceRole(decision_raw["role"]),
                    GovernanceAction(decision_raw["action"]),
                    bool(decision_raw["allowed"]),
                    str(decision_raw["reason"]),
                    None if decision_raw["project"] is None else str(decision_raw["project"]),
                )
                previous = str(raw["record_hash"])
                records.append(AuditRecord(expected, str(raw["timestamp"]), decision, str(raw["previous_hash"]), previous))
        except (OSError, KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
            if isinstance(exc, GovernanceError):
                raise
            raise GovernanceError(f"cannot read governance audit log: {exc}") from exc
        return tuple(records)

    def verify(self) -> int:
        return len(self.load())

    @staticmethod
    def _hash(value: Mapping[str, Any]) -> str:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
