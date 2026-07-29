from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from moughorai.knowledge import KnowledgeService
from moughorai.memory import MemoryService
from moughorai.models.knowledge import (
    KnowledgeContext,
    KnowledgeDocument,
)
from moughorai.models.memory import (
    MemoryContext,
    MemoryDocument,
)
from moughorai.models.rule import (
    RuleContext,
    RuleDocument,
)
from moughorai.orchestrator import Orchestrator
from moughorai.rules import RuleSelector


def create_config() -> SimpleNamespace:
    return SimpleNamespace(
        workspace_root=Path("C:/MoughorAI"),
        paths=SimpleNamespace(
            brain=Path("brain"),
            projects=Path("projects"),
        ),
    )


def create_knowledge() -> KnowledgeContext:
    return KnowledgeContext(
        documents=(
            KnowledgeDocument(
                name="coding.md",
                path=Path("brain/coding.md"),
                category="brain",
                content="Use strong typing.",
            ),
        ),
    )


def create_knowledge_service(
    knowledge: KnowledgeContext,
) -> Mock:
    """Create a mocked knowledge service."""

    service = Mock(spec=KnowledgeService)
    service.load.return_value = knowledge
    return service


def create_memory_service(
    memory: MemoryContext,
) -> Mock:
    """Create a mocked memory service."""

    service = Mock(spec=MemoryService)
    service.load.return_value = memory
    return service


def create_memory() -> MemoryContext:
    return MemoryContext(
        documents=(
            MemoryDocument(
                name="memory.md",
                path=Path("projects/demo/memory/memory.md"),
                category="memory",
                content="Remember to use PostgreSQL.",
            ),
        ),
    )


def create_empty_memory() -> MemoryContext:
    return MemoryContext()


def create_rules() -> RuleContext:
    return RuleContext(
        documents=(
            RuleDocument(
                name="python.md",
                path=Path("rules/python.md"),
                category="language",
                content="Use Python type hints.",
            ),
        ),
    )


def test_ask_runs_complete_pipeline() -> None:
    config = create_config()
    knowledge = create_knowledge()
    empty_memory = create_empty_memory()

    knowledge_service = create_knowledge_service(knowledge)

    memory_service = create_memory_service(empty_memory)

    project_locator = Mock()
    project_locator.locate.return_value = None

    prompt_builder = Mock()
    prompt_builder.build.return_value = "Complete prompt"

    ollama_service = Mock()
    ollama_service.generate.return_value = SimpleNamespace(
        response="Generated answer",
    )

    orchestrator = Orchestrator(
        config=config,
        knowledge_service=knowledge_service,
        memory_service=memory_service,
        project_locator=project_locator,
        prompt_builder=prompt_builder,
        ollama_service=ollama_service,
    )

    result = orchestrator.ask(
        "Explain this workspace.",
    )

    assert result == "Generated answer"

    project_locator.locate.assert_called_once_with(None)

    knowledge_service.load.assert_called_once_with(
        query="Explain this workspace.",
        project=None,
    )

    memory_service.load.assert_called_once_with(
        query="Explain this workspace.",
        project=None,
    )

    prompt_builder.build.assert_called_once_with(
        "Explain this workspace.",
        rules=RuleContext(),
        knowledge=knowledge,
        memory=empty_memory,
        project=None,
    )

    ollama_service.generate.assert_called_once_with(
        "Complete prompt",
    )


def test_ask_passes_project_memory_to_prompt_builder(
    tmp_path: Path,
) -> None:
    config = create_config()
    config.workspace_root = tmp_path

    project = tmp_path / "source" / "demo"
    project.mkdir(parents=True)

    project_memory_path = (
        tmp_path
        / "projects"
        / "demo"
        / "memory"
    )
    project_memory_path.mkdir(parents=True)

    knowledge = create_knowledge()
    memory = create_memory()
    project_context = Mock()

    knowledge_service = create_knowledge_service(knowledge)

    memory_service = create_memory_service(memory)

    project_locator = Mock()
    project_locator.locate.return_value = project

    project_analyzer = Mock()
    project_analyzer.analyze.return_value = project_context

    prompt_builder = Mock()
    prompt_builder.build.return_value = "Project prompt"

    ollama_service = Mock()
    ollama_service.generate.return_value = SimpleNamespace(
        response="Project answer",
    )

    orchestrator = Orchestrator(
        config=config,
        knowledge_service=knowledge_service,
        memory_service=memory_service,
        project_locator=project_locator,
        project_analyzer=project_analyzer,
        prompt_builder=prompt_builder,
        ollama_service=ollama_service,
    )

    result = orchestrator.ask(
        "Review the project.",
        project=project,
    )

    assert result == "Project answer"

    project_locator.locate.assert_called_once_with(project)

    knowledge_service.load.assert_called_once_with(
        query="Review the project.",
        project=project,
    )

    memory_service.load.assert_called_once_with(
        query="Review the project.",
        project=project,
    )

    project_analyzer.analyze.assert_called_once_with(project)

    prompt_builder.build.assert_called_once_with(
        "Review the project.",
        rules=RuleContext(),
        knowledge=knowledge,
        memory=memory,
        project=project_context,
    )

    ollama_service.generate.assert_called_once_with(
        "Project prompt",
    )


def test_ask_strips_model_response() -> None:
    config = create_config()

    knowledge_service = create_knowledge_service(KnowledgeContext())

    memory_service = create_memory_service(MemoryContext())

    project_locator = Mock()
    project_locator.locate.return_value = None

    prompt_builder = Mock()
    prompt_builder.build.return_value = "Prompt"

    ollama_service = Mock()
    ollama_service.generate.return_value = SimpleNamespace(
        response="\n  Clean response  \n",
    )

    orchestrator = Orchestrator(
        config=config,
        knowledge_service=knowledge_service,
        memory_service=memory_service,
        project_locator=project_locator,
        prompt_builder=prompt_builder,
        ollama_service=ollama_service,
    )

    assert orchestrator.ask("Test") == "Clean response"

    project_locator.locate.assert_called_once_with(None)
    memory_service.load.assert_called_once_with(
        query="Test",
        project=None,
    )


def test_ask_passes_selected_rules_to_prompt_builder() -> None:
    config = create_config()

    rules = create_rules()
    knowledge = create_knowledge()

    rule_selector = Mock(spec=RuleSelector)
    rule_selector.retrieve.return_value = rules

    knowledge_service = create_knowledge_service(knowledge)

    memory_service = create_memory_service(MemoryContext())

    project_locator = Mock()
    project_locator.locate.return_value = None

    prompt_builder = Mock()
    prompt_builder.build.return_value = "Prompt with rules"

    ollama_service = Mock()
    ollama_service.generate.return_value = SimpleNamespace(
        response="Rule-aware answer",
    )

    orchestrator = Orchestrator(
        config=config,
        rule_selector=rule_selector,
        knowledge_service=knowledge_service,
        memory_service=memory_service,
        project_locator=project_locator,
        prompt_builder=prompt_builder,
        ollama_service=ollama_service,
    )

    result = orchestrator.ask(
        "Write Python tests.",
    )

    assert result == "Rule-aware answer"

    rule_selector.retrieve.assert_called_once_with(
        "Write Python tests.",
    )

    memory_service.load.assert_called_once_with(
        query="Write Python tests.",
        project=None,
    )

    prompt_builder.build.assert_called_once_with(
        "Write Python tests.",
        rules=rules,
        knowledge=knowledge,
        memory=MemoryContext(),
        project=None,
    )