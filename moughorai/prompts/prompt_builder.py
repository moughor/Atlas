"""Build deterministic prompts for MoughorAI coding requests."""

from textwrap import dedent
from typing import Protocol

from moughorai.models.knowledge import KnowledgeContext
from moughorai.models.memory import MemoryContext
from moughorai.models.project import ProjectContext
from moughorai.models.rule import RuleContext


class RenderableContext(Protocol):
    """Context that can be rendered inside a prompt section."""

    @property
    def is_empty(self) -> bool:
        """Return whether the context contains no information."""

    def render(self) -> str:
        """Render the context as structured text."""


class PromptBuilderError(ValueError):
    """Raised when a valid prompt cannot be constructed."""


class PromptBuilder:
    """Combine rules, knowledge, memory, project context, and request."""

    DEFAULT_SYSTEM_INSTRUCTIONS = dedent(
        """
        You are MoughorAI, a local AI software engineering assistant.

        Your responsibilities:
        - Understand the user's request before proposing changes.
        - Follow the supplied project knowledge and coding rules.
        - Use supplied project memory to preserve established decisions.
        - Produce correct, maintainable, and secure solutions.
        - Preserve existing behavior unless a change is requested.
        - Prefer small, focused changes over unnecessary rewrites.
        - Explain assumptions when information is missing.
        - Never claim that code was executed unless it was actually executed.

        When returning code:
        - Use complete, executable examples where practical.
        - Include relevant filenames.
        - Preserve strong typing.
        - Include error handling where appropriate.
        - Include or recommend tests for changed behavior.
        """
    ).strip()

    def __init__(
        self,
        system_instructions: str | None = None,
    ) -> None:
        selected_instructions = (
            system_instructions
            if system_instructions is not None
            else self.DEFAULT_SYSTEM_INSTRUCTIONS
        )

        self.system_instructions = self._normalize_required_text(
            selected_instructions,
            field_name="System instructions",
        )

    def build(
        self,
        user_request: str,
        *,
        rules: RuleContext | None = None,
        knowledge: KnowledgeContext | None = None,
        memory: MemoryContext | None = None,
        project: ProjectContext | None = None,
    ) -> str:
        """Build the complete prompt sent to the language model."""

        normalized_request = self._normalize_required_text(
            user_request,
            field_name="User request",
        )

        selected_rules = rules or RuleContext()
        selected_knowledge = knowledge or KnowledgeContext()
        selected_memory = memory or MemoryContext()

        sections = [
            self._render_section(
                "SYSTEM INSTRUCTIONS",
                self.system_instructions,
            ),
            self._render_optional_section(
                title="PROJECT RULES",
                context=selected_rules,
                empty_message=(
                    "No project rules were selected. "
                    "Follow the system instructions and supplied "
                    "project context."
                ),
            ),
            self._render_optional_section(
                title="PROJECT KNOWLEDGE",
                context=selected_knowledge,
                empty_message=(
                    "No project knowledge documents were supplied. "
                    "Do not invent project-specific rules."
                ),
            ),
            self._render_optional_section(
                title="PROJECT MEMORY",
                context=selected_memory,
                empty_message="No project memory is available.",
            ),
        ]

        if project is not None:
            sections.append(
                self._render_project_section(project)
            )

        sections.extend(
            [
                self._render_section(
                    "USER REQUEST",
                    normalized_request,
                ),
                self._render_section(
                    "RESPONSE INSTRUCTIONS",
                    self._response_instructions(),
                ),
            ]
        )

        return "\n\n".join(sections).strip() + "\n"

    def build_system_prompt(
        self,
        *,
        rules: RuleContext | None = None,
        knowledge: KnowledgeContext | None = None,
        memory: MemoryContext | None = None,
        project: ProjectContext | None = None,
    ) -> str:
        """Build reusable system, rules, knowledge, memory, and project parts."""

        selected_rules = rules or RuleContext()
        selected_knowledge = knowledge or KnowledgeContext()
        selected_memory = memory or MemoryContext()

        sections = [
            self._render_section(
                "SYSTEM INSTRUCTIONS",
                self.system_instructions,
            ),
            self._render_optional_section(
                title="PROJECT RULES",
                context=selected_rules,
                empty_message=(
                    "No project rules were selected. "
                    "Follow the system instructions and supplied "
                    "project context."
                ),
            ),
            self._render_optional_section(
                title="PROJECT KNOWLEDGE",
                context=selected_knowledge,
                empty_message=(
                    "No project knowledge documents were supplied. "
                    "Do not invent project-specific rules."
                ),
            ),
            self._render_optional_section(
                title="PROJECT MEMORY",
                context=selected_memory,
                empty_message="No project memory is available.",
            ),
        ]

        if project is not None:
            sections.append(
                self._render_project_section(project)
            )

        return "\n\n".join(sections).strip() + "\n"

    def _render_optional_section(
        self,
        *,
        title: str,
        context: RenderableContext,
        empty_message: str,
    ) -> str:
        """Render a context or its explicit empty-state message."""

        content = (
            empty_message
            if context.is_empty
            else context.render()
        )

        return self._render_section(
            title,
            content,
        )

    def _render_project_section(
        self,
        project: ProjectContext,
    ) -> str:
        """Render an analyzed software project."""

        return self._render_section(
            "PROJECT CONTEXT",
            project.render(),
        )

    @staticmethod
    def _response_instructions() -> str:
        return dedent(
            """
            Respond directly to the user's request.

            Clearly distinguish:
            - explanations,
            - proposed changes,
            - commands to run,
            - and code or file contents.

            Treat supplied project rules as explicit constraints.
            Do not ignore or contradict the supplied project knowledge.
            Preserve relevant decisions contained in project memory.
            If instructions conflict, mention the conflict explicitly.
            """
        ).strip()

    @staticmethod
    def _render_section(
        title: str,
        content: str,
    ) -> str:
        return (
            f"<{title}>\n"
            f"{content.strip()}\n"
            f"</{title}>"
        )

    @staticmethod
    def _normalize_required_text(
        value: str,
        *,
        field_name: str,
    ) -> str:
        if not isinstance(value, str):
            raise PromptBuilderError(
                f"{field_name} must be a string."
            )

        normalized = value.strip()

        if not normalized:
            raise PromptBuilderError(
                f"{field_name} cannot be empty."
            )

        return normalized