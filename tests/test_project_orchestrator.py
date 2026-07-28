"""Tests for optional project analysis in the orchestrator."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from moughorai.knowledge import KnowledgeService
from moughorai.models.knowledge import KnowledgeContext
from moughorai.models.memory import MemoryContext
from moughorai.models.project import ProjectContext
from moughorai.models.rule import RuleContext
from moughorai.orchestrator import Orchestrator
from moughorai.rules import RuleService


def make_config() -> SimpleNamespace:
    return SimpleNamespace(
        workspace_root=Path.cwd(),
        paths=SimpleNamespace(
            brain=Path("brain"),
            projects=Path("projects"),
        ),
    )


def make_project_context() -> ProjectContext:
    return ProjectContext(
        name="sample-project",
        root=Path("sample-project").resolve(),
        tree="src/",
    )


def make_rule_service(
    rules: RuleContext,
) -> Mock:
    """Create a mocked rule service."""

    service = Mock(spec=RuleService)
    service.load.return_value = rules
    return service


def test_ask_analyzes_supplied_project() -> None:
    knowledge = KnowledgeContext()
    project_context = make_project_context()
    project_path = Path("sample-project")

    rule_service = make_rule_service(RuleContext())

    knowledge_service = Mock(spec=KnowledgeService)
    knowledge_service.load.return_value = knowledge

    project_locator = Mock()
    project_locator.locate.return_value = project_path

    project_analyzer = Mock()
    project_analyzer.analyze.return_value = project_context

    prompt_builder = Mock()
    prompt_builder.build.return_value = "generated prompt"

    ollama_service = Mock()
    ollama_service.generate.return_value = SimpleNamespace(
        response="  Generated answer  ",
    )

    orchestrator = Orchestrator(
        config=make_config(),
        rule_service=rule_service,
        knowledge_service=knowledge_service,
        project_locator=project_locator,
        project_analyzer=project_analyzer,
        prompt_builder=prompt_builder,
        ollama_service=ollama_service,
    )

    result = orchestrator.ask(
        "Explain this project.",
        project=project_path,
    )

    assert result == "Generated answer"

    project_locator.locate.assert_called_once_with(
        project_path
    )

    rule_service.load.assert_called_once_with(
        query="Explain this project.",
    )

    project_analyzer.analyze.assert_called_once_with(
        project_path
    )

    prompt_builder.build.assert_called_once_with(
        "Explain this project.",
        rules=RuleContext(),
        knowledge=knowledge,
        memory=MemoryContext(),
        project=project_context,
    )

    ollama_service.generate.assert_called_once_with(
        "generated prompt"
    )


def test_ask_without_project_skips_analysis() -> None:
    knowledge = KnowledgeContext()

    rule_service = make_rule_service(RuleContext())

    knowledge_service = Mock(spec=KnowledgeService)
    knowledge_service.load.return_value = knowledge

    project_locator = Mock()
    project_locator.locate.return_value = None

    project_analyzer = Mock()

    prompt_builder = Mock()
    prompt_builder.build.return_value = "generated prompt"

    ollama_service = Mock()
    ollama_service.generate.return_value = SimpleNamespace(
        response="Answer",
    )

    orchestrator = Orchestrator(
        config=make_config(),
        rule_service=rule_service,
        knowledge_service=knowledge_service,
        project_locator=project_locator,
        project_analyzer=project_analyzer,
        prompt_builder=prompt_builder,
        ollama_service=ollama_service,
    )

    result = orchestrator.ask("Explain the rules.")

    assert result == "Answer"

    project_locator.locate.assert_called_once_with(
        None
    )

    rule_service.load.assert_called_once_with(
        query="Explain the rules.",
    )

    project_analyzer.analyze.assert_not_called()

    prompt_builder.build.assert_called_once_with(
        "Explain the rules.",
        rules=RuleContext(),
        knowledge=knowledge,
        memory=MemoryContext(),
        project=None,
    )