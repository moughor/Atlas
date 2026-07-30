from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from moughorai.ai_context import WorkspaceSemanticContext
from moughorai.ai_memory import ConversationMemoryStore, ConversationRole
from moughorai.llm import LlmClient
from moughorai.prompts import SemanticPromptBuilder
from moughorai.semantic_snapshot import AtlasSemanticSnapshot


@dataclass(frozen=True, slots=True)
class ExplainRequest:
    subject: str = "workspace"
    question: str = "Explain this workspace."
    conversation_id: int | None = None


@dataclass(frozen=True, slots=True)
class ExplainResult:
    markdown: str
    snapshot_id: str
    estimated_input_tokens: int
    conversation_id: int | None = None


class ExplainEngine:
    def __init__(
        self,
        client: LlmClient,
        *,
        prompt_builder: SemanticPromptBuilder | None = None,
        memory: ConversationMemoryStore | None = None,
    ) -> None:
        self.client = client
        self.prompts = prompt_builder or SemanticPromptBuilder()
        self.memory = memory

    def explain(self, snapshot: AtlasSemanticSnapshot, request: ExplainRequest | None = None) -> ExplainResult:
        selected = request or ExplainRequest()
        subject = selected.subject.strip()
        question = selected.question.strip()
        if not subject or not question:
            raise ValueError("explanation subject and question are required")
        repository_default = self._is_repository_default(selected)
        context = (
            self._repository_context(snapshot)
            if repository_default and snapshot.semantic_context.get("repository_summary")
            else snapshot.to_context()
        )
        prompt = self.prompts.build(
            question,
            context,
            template=(
                "atlas-repository-explanation-v1"
                if repository_default and snapshot.semantic_context.get("repository_summary")
                else "atlas-grounded-v1"
            ),
            variables={"subject": subject},
            model="",
        )
        conversation_id = selected.conversation_id
        if self.memory is not None:
            if conversation_id is None:
                conversation_id = self.memory.create(
                    snapshot.workspace_fingerprint,
                    title=f"Explain {subject}",
                ).id
            self.memory.append(
                conversation_id,
                ConversationRole.USER,
                question,
                references={"snapshot": snapshot.snapshot_id, "subject": subject},
            )
        response = self.client.complete(prompt.request)
        markdown = response.text.strip()
        if not markdown:
            raise ValueError("explanation provider returned empty output")
        if self.memory is not None and conversation_id is not None:
            self.memory.append(
                conversation_id,
                ConversationRole.ASSISTANT,
                markdown,
                references={"snapshot": snapshot.snapshot_id, "kind": "explanation"},
            )
        return ExplainResult(
            markdown,
            snapshot.snapshot_id,
            prompt.estimated_input_tokens,
            conversation_id,
        )

    @staticmethod
    def _is_repository_default(request: ExplainRequest) -> bool:
        return (
            request.subject.strip().casefold() in {"workspace", "repository"}
            and request.question.strip() == ExplainRequest().question
        )

    @staticmethod
    def _repository_context(snapshot: AtlasSemanticSnapshot) -> WorkspaceSemanticContext:
        source = snapshot.semantic_context
        summary = source.get("repository_summary")
        architecture = source.get("architecture", {})
        graph = source.get("semantic_graph", {})
        projects = summary.get("projects", ()) if isinstance(summary, Mapping) else ()
        findings = architecture.get("findings", ()) if isinstance(architecture, Mapping) else ()
        limitations = [
            "Context is source-free; no raw source code is included.",
            f"Detailed symbols omitted from this repository overview: {len(source.get('symbols', ()))} available.",
            f"Semantic graph summarized: {len(graph.get('nodes', ()))} nodes and {len(graph.get('edges', ()))} edges.",
        ]
        if not findings:
            limitations.append("No high-confidence architecture finding is available.")
        return WorkspaceSemanticContext({
            "schema_version": source.get("schema_version"),
            "workspace": {
                "root": source.get("workspace", {}).get("root"),
                "project_count": len(projects),
            },
            "repository_summary": summary,
            "architecture": ExplainEngine._compact_architecture(architecture),
            "limitations": limitations,
        })

    @staticmethod
    def _compact_architecture(value: object) -> object:
        if not isinstance(value, Mapping):
            return {}
        ports = tuple(value.get("ports", ()))
        adapters = tuple(value.get("adapters", ()))
        infrastructure = tuple(value.get("infrastructure_layers", ()))
        return {
            "schema_version": value.get("schema_version"),
            "findings": value.get("findings", ()),
            "dependency_directions": value.get("dependency_directions", ()),
            "dependency_cycles": value.get("dependency_cycles", ()),
            "bounded_contexts": value.get("bounded_contexts", ()),
            "ports": ports[:25],
            "port_count": len(ports),
            "adapters": adapters[:25],
            "adapter_count": len(adapters),
            "infrastructure_layers": infrastructure[:25],
            "infrastructure_layer_count": len(infrastructure),
        }
