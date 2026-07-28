"""Knowledge loading service."""

from __future__ import annotations

from pathlib import Path

from moughorai.config import AppConfig
from moughorai.knowledge.knowledge_loader import KnowledgeLoader
from moughorai.knowledge.retriever import KnowledgeRetriever
from moughorai.models.knowledge import KnowledgeContext


class KnowledgeService:
    """Load knowledge for one request."""

    def __init__(
        self,
        config: AppConfig,
        loader: KnowledgeLoader,
        retriever: KnowledgeRetriever | None = None,
    ) -> None:
        self.config = config
        self.loader = loader
        self.retriever = retriever

    def load(
        self,
        *,
        query: str = "",
        project: Path | None = None,
    ) -> KnowledgeContext:
        """Load relevant knowledge with a full-knowledge fallback."""

        full_knowledge = self._load_full_knowledge(project)

        if (
            self.retriever is None
            or not query.strip()
        ):
            return full_knowledge

        retrieved_knowledge = self.retriever.retrieve(query)

        if retrieved_knowledge.documents:
            return retrieved_knowledge

        return full_knowledge

    def _load_full_knowledge(
        self,
        project: Path | None,
    ) -> KnowledgeContext:
        """Load global and optional project-specific knowledge."""

        global_knowledge = self.loader.load(
            self.config.paths.brain,
            category="brain",
        )

        if project is None:
            return global_knowledge

        project_knowledge_path = (
            self.config.paths.projects
            / project.name
        )

        resolved_project_knowledge_path = (
            self._resolve_workspace_path(
                project_knowledge_path,
            )
        )

        if not resolved_project_knowledge_path.is_dir():
            return global_knowledge

        project_knowledge = self.loader.load(
            project_knowledge_path,
            category="project",
        )

        return KnowledgeContext(
            documents=(
                *global_knowledge.documents,
                *project_knowledge.documents,
            ),
        )

    def _resolve_workspace_path(
        self,
        path: Path,
    ) -> Path:
        """Resolve a path relative to the configured workspace."""

        if path.is_absolute():
            return path.resolve()

        return (
            self.config.workspace_root
            / path
        ).resolve()