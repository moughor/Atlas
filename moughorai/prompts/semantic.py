from __future__ import annotations

from dataclasses import dataclass
import re
from string import Formatter
from types import MappingProxyType
from typing import Mapping

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.llm import LlmMessage, LlmRequest


class PromptTemplateError(ValueError):
    """Raised when a semantic prompt template cannot be rendered safely."""


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    name: str
    system: str
    user: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.system.strip() or not self.user.strip():
            raise PromptTemplateError("template name, system, and user text are required")


@dataclass(frozen=True, slots=True)
class PromptBuildResult:
    request: LlmRequest
    estimated_input_tokens: int
    template: str


class TokenEstimator:
    """Provider-neutral, deterministic token budgeting heuristic."""

    def __init__(self, *, characters_per_token: int = 4) -> None:
        if characters_per_token < 1:
            raise ValueError("characters_per_token must be positive")
        self.characters_per_token = characters_per_token

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        return (len(text) + self.characters_per_token - 1) // self.characters_per_token


class SemanticPromptBuilder:
    DEFAULT_TEMPLATE = PromptTemplate(
        name="atlas-grounded-v1",
        system=(
            "You are an Atlas assistant. Treat the supplied deterministic Atlas "
            "context as authoritative. Clearly identify any missing information."
        ),
        user="Request:\n{request}\n\nAtlas context (JSON):\n{context}",
    )
    REPOSITORY_EXPLANATION_TEMPLATE = PromptTemplate(
        name="atlas-repository-explanation-v1",
        system=(
            "You are an Atlas repository architect. Treat the supplied source-free "
            "Atlas metadata as authoritative. Prioritize repository_summary, then "
            "architecture and dependency metadata. Give a direct repository overview "
            "instead of asking what to inspect. Cover, when available: repository or "
            "workspace name, discovered project count, module hierarchy, primary "
            "languages, build systems, frameworks, major repository areas, entry "
            "points, dependency overview, and high-level architecture. End with "
            "important limitations or uncertainty. Never invent missing facts and "
            "never request or reproduce raw source code."
        ),
        user=(
            "Repository explanation request:\n{request}\n\n"
            "Subject: {subject}\n\n"
            "Prioritized Atlas repository context (JSON):\n{context}"
        ),
    )

    def __init__(
        self,
        templates: Mapping[str, PromptTemplate] | None = None,
        *,
        estimator: TokenEstimator | None = None,
    ) -> None:
        values = {
            self.DEFAULT_TEMPLATE.name: self.DEFAULT_TEMPLATE,
            self.REPOSITORY_EXPLANATION_TEMPLATE.name: self.REPOSITORY_EXPLANATION_TEMPLATE,
        }
        for name, template in sorted((templates or {}).items()):
            if name != template.name:
                raise PromptTemplateError("template registry key must match template name")
            values[name] = template
        self.templates = MappingProxyType(values)
        self.estimator = estimator or TokenEstimator()

    def build(
        self,
        request: str,
        context: WorkspaceSemanticContext,
        *,
        template: str = "atlas-grounded-v1",
        variables: Mapping[str, str] | None = None,
        model: str = "",
        maximum_input_tokens: int | None = None,
    ) -> PromptBuildResult:
        normalized = request.strip()
        if not normalized:
            raise PromptTemplateError("request must not be empty")
        try:
            selected = self.templates[template]
        except KeyError as exc:
            raise PromptTemplateError(f"unknown prompt template: {template}") from exc
        values = {"request": normalized, "context": context.to_json()}
        values.update(dict(sorted((variables or {}).items())))
        system = self._render(selected.system, values)
        user = self._render(selected.user, values)
        estimated = self.estimator.estimate(system) + self.estimator.estimate(user)
        if maximum_input_tokens is not None and estimated > maximum_input_tokens:
            raise PromptTemplateError(
                f"estimated input tokens {estimated} exceed limit {maximum_input_tokens}"
            )
        return PromptBuildResult(
            LlmRequest(
                (LlmMessage("system", system), LlmMessage("user", user)),
                model=model,
                metadata={"prompt_template": selected.name},
            ),
            estimated,
            selected.name,
        )

    @staticmethod
    def _render(template: str, values: Mapping[str, str]) -> str:
        fields = [
            field for _, field, _, _ in Formatter().parse(template) if field is not None
        ]
        invalid = [field for field in fields if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field)]
        if invalid:
            raise PromptTemplateError(f"invalid template fields: {sorted(invalid)}")
        missing = sorted(set(fields).difference(values))
        if missing:
            raise PromptTemplateError(f"missing template variables: {missing}")
        try:
            return template.format_map(values).strip()
        except (ValueError, KeyError) as exc:
            raise PromptTemplateError(f"invalid prompt template: {exc}") from exc
