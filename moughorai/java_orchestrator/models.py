from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class JavaAnalysisMode(str, Enum):
    ANALYZE = "analyze"
    QUALITY_GATE = "quality_gate"
    ASK = "ask"
    FULL = "full"


class JavaAnalysisStatus(str, Enum):
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class JavaAnalysisCommand:
    projects: tuple[Any, ...]
    mode: JavaAnalysisMode = JavaAnalysisMode.FULL
    question: str | None = None
    answer_mode: Any | None = None
    policy: Any | None = None
    baseline: Any | None = None
    changed_symbols: tuple[tuple[str, str], ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.projects:
            raise ValueError("projects must not be empty")
        if self.mode in {JavaAnalysisMode.ASK, JavaAnalysisMode.FULL}:
            if self.question is not None and not self.question.strip():
                raise ValueError("question must not be blank")


@dataclass(frozen=True, slots=True)
class JavaAnalysisExecution:
    status: JavaAnalysisStatus
    workspace: Any | None = None
    knowledge_graph: Any | None = None
    baseline: Any | None = None
    quality_gate: Any | None = None
    retrieval: Any | None = None
    llm_request: Any | None = None
    llm_result: Any | None = None
    answer: str | None = None
    stages: tuple[str, ...] = ()
    error: str | None = None

    @property
    def completed(self) -> bool:
        return self.status is JavaAnalysisStatus.COMPLETED

    @property
    def blocked(self) -> bool:
        return self.status is JavaAnalysisStatus.BLOCKED
