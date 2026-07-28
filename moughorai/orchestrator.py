"""Coordinate the MoughorAI request-processing pipeline."""

from __future__ import annotations

from pathlib import Path

from moughorai.config import AppConfig, load_config
from moughorai.knowledge import KnowledgeLoader, KnowledgeService
from moughorai.memory import MemoryLoader, MemoryService
from moughorai.project_locator import ProjectLocator
from moughorai.projects import ProjectAnalyzer
from moughorai.prompts import PromptBuilder
from moughorai.rules import RuleSelector, RuleService
from moughorai.services.ollama_service import OllamaService


class Orchestrator:
    """Coordinate the complete MoughorAI request pipeline."""

    def __init__(
        self,
        config: AppConfig | None = None,
        *,
        rule_service: RuleService | None = None,
        rule_selector: RuleSelector | None = None,
        knowledge_service: KnowledgeService | None = None,
        memory_service: MemoryService | None = None,
        project_analyzer: ProjectAnalyzer | None = None,
        prompt_builder: PromptBuilder | None = None,
        ollama_service: OllamaService | None = None,
        project_locator: ProjectLocator | None = None,
    ) -> None:
        self.config = config or load_config()

        self.rule_service = (
            rule_service
            if rule_service is not None
            else RuleService(rule_selector)
        )

        self.knowledge_service = (
            knowledge_service
            if knowledge_service is not None
            else KnowledgeService(KnowledgeLoader(self.config.workspace_root))
        )

        self.memory_service = (
            memory_service
            if memory_service is not None
            else MemoryService(
                self.config,
                MemoryLoader(self.config.workspace_root),
            )
        )

        self.project_analyzer = (
            project_analyzer
            if project_analyzer is not None
            else ProjectAnalyzer(self.config.workspace_root)
        )

        self.prompt_builder = prompt_builder or PromptBuilder()
        self.ollama_service = (
            ollama_service if ollama_service is not None else OllamaService(self.config)
        )
        self.project_locator = (
            project_locator
            if project_locator is not None
            else ProjectLocator(self.config.workspace_root)
        )

    def ask(self, query: str, project: str | Path | None = None) -> str:
        project_path = self.project_locator.locate(project)

        rules = self.rule_service.load(query=query)
        knowledge = self.knowledge_service.load(
            query=query,
            project=project_path,
        )
        memory = self.memory_service.load(
            query=query,
            project=project_path,
        )

        project_context = self.analyze_project(project_path)

        prompt = self.prompt_builder.build(
            query,
            rules=rules,
            knowledge=knowledge,
            memory=memory,
            project=project_context,
        )

        return self.ollama_service.generate(prompt).response.strip()

    def analyze_project(self, project_path: Path | None):
        if project_path is None:
            return None
        return self.project_analyzer.analyze(project_path)