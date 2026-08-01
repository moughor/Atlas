"""Stable public facade for Atlas AI 1.0."""

from moughorai.ai_ask import AskEngine, AskRequest, AskResult
from moughorai.ai_explain import (
    ExplainEngine,
    ExplainRequest,
    ExplainResult,
    ExplanationAvailability,
    StructuredExplanation,
    StructuredExplanationRequest,
)
from moughorai.ai_git_context import GitContext, GitContextService
from moughorai.ai_ide import IdeAction, IdeAssistant, IdeRequest, IdeResponse, SupportedIde
from moughorai.ai_memory import ConversationMemoryStore, ConversationRole
from moughorai.ai_patch import GitPatchValidator, PatchEngine, PatchProposal, PatchRequest
from moughorai.ai_review import ReviewEngine, ReviewRequest, ReviewResult
from moughorai.semantic_snapshot import AtlasSemanticSnapshot, SemanticSnapshotStore

from .capabilities import ATLAS_AI_VERSION, AtlasAiCapabilities, atlas_ai_capabilities

__all__ = [
    "ATLAS_AI_VERSION", "AtlasAiCapabilities", "atlas_ai_capabilities",
    "AtlasSemanticSnapshot", "SemanticSnapshotStore",
    "ConversationMemoryStore", "ConversationRole",
    "ExplainEngine", "ExplainRequest", "ExplainResult",
    "ExplanationAvailability", "StructuredExplanation", "StructuredExplanationRequest",
    "ReviewEngine", "ReviewRequest", "ReviewResult",
    "AskEngine", "AskRequest", "AskResult",
    "PatchEngine", "PatchRequest", "PatchProposal", "GitPatchValidator",
    "GitContext", "GitContextService",
    "IdeAction", "IdeAssistant", "IdeRequest", "IdeResponse", "SupportedIde",
]
