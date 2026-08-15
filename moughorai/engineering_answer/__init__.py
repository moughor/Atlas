"""Deterministic engineering-answer synthesis over authoritative evidence."""

from .models import (
    ENGINEERING_ANSWER_PRODUCER,
    ENGINEERING_ANSWER_SCHEMA_VERSION,
    EngineeringAnswer,
    EngineeringAnswerItem,
    EngineeringAnswerSection,
    EngineeringAnswerSubject,
    EngineeringAnswerSynthesis,
    EngineeringAnswerTraceability,
    EngineeringInspectItem,
    EngineeringTraversalSummary,
)
from .renderer import render_engineering_answer
from .service import EngineeringAnswerConfiguration, EngineeringAnswerService

__all__ = [
    "ENGINEERING_ANSWER_PRODUCER",
    "ENGINEERING_ANSWER_SCHEMA_VERSION",
    "EngineeringAnswer",
    "EngineeringAnswerConfiguration",
    "EngineeringAnswerItem",
    "EngineeringAnswerSection",
    "EngineeringAnswerService",
    "EngineeringAnswerSubject",
    "EngineeringAnswerSynthesis",
    "EngineeringAnswerTraceability",
    "EngineeringInspectItem",
    "EngineeringTraversalSummary",
    "render_engineering_answer",
]
