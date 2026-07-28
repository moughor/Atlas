from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from moughorai.knowledge import KnowledgeService
from moughorai.models.memory import MemoryContext
from moughorai.models.rule import RuleContext
from moughorai.orchestrator import Orchestrator


def create_config(workspace_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        workspace_root=workspace_root,
        paths=SimpleNamespace(
            brain=Path("brain"),
            projects=Path("projects"),
        ),
    )


def create_orchestrator(
    tmp_path: Path,
    *,
    project_locator: Mock,
    project_analyzer: Mock,
) -> tuple[Orchestrator, Mock, Mock]:
    knowledge_service = Mock(spec=KnowledgeService)
    knowledge_service.load.return_value = Mock()

    prompt_builder = Mock()
    prompt_builder.build.return_value = "generated prompt"

    ollama_service = Mock()
    ollama_service.generate.return_value = SimpleNamespace(
        response=" model response ",
    )

    orchestrator = Orchestrator(
        config=create_config(tmp_path),
        knowledge_service=knowledge_service,
        project_locator=project_locator,
        project_analyzer=project_analyzer,
        prompt_builder=prompt_builder,
        ollama_service=ollama_service,
    )

    return orchestrator, prompt_builder, ollama_service


def test_explicit_project_is_resolved_before_analysis(
    tmp_path: Path,
) -> None:
    requested_project = tmp_path / "requested"
    located_project = tmp_path / "located"
    project_context = Mock()

    project_locator = Mock()
    project_locator.locate.return_value = located_project

    project_analyzer = Mock()
    project_analyzer.analyze.return_value = project_context

    orchestrator, prompt_builder, _ = create_orchestrator(
        tmp_path,
        project_locator=project_locator,
        project_analyzer=project_analyzer,
    )

    result = orchestrator.ask(
        "Explain this project.",
        project=requested_project,
    )

    assert result == "model response"

    project_locator.locate.assert_called_once_with(
        requested_project,
    )

    project_analyzer.analyze.assert_called_once_with(
        located_project,
    )

    prompt_builder.build.assert_called_once_with(
        "Explain this project.",
        rules=RuleContext(),
        knowledge=orchestrator.knowledge_service.load.return_value,
        memory=MemoryContext(),
        project=project_context,
    )


def test_automatic_project_discovery_is_used(
    tmp_path: Path,
) -> None:
    located_project = tmp_path / "automatically-located"
    project_context = Mock()

    project_locator = Mock()
    project_locator.locate.return_value = located_project

    project_analyzer = Mock()
    project_analyzer.analyze.return_value = project_context

    orchestrator, prompt_builder, _ = create_orchestrator(
        tmp_path,
        project_locator=project_locator,
        project_analyzer=project_analyzer,
    )

    orchestrator.ask("Review the architecture.")

    project_locator.locate.assert_called_once_with(None)

    project_analyzer.analyze.assert_called_once_with(
        located_project,
    )

    prompt_builder.build.assert_called_once_with(
        "Review the architecture.",
        rules=RuleContext(),
        knowledge=orchestrator.knowledge_service.load.return_value,
        memory=MemoryContext(),
        project=project_context,
    )


def test_no_discovered_project_preserves_old_behavior(
    tmp_path: Path,
) -> None:
    project_locator = Mock()
    project_locator.locate.return_value = None

    project_analyzer = Mock()

    orchestrator, prompt_builder, _ = create_orchestrator(
        tmp_path,
        project_locator=project_locator,
        project_analyzer=project_analyzer,
    )

    result = orchestrator.ask("Explain the rules.")

    assert result == "model response"

    project_locator.locate.assert_called_once_with(None)
    project_analyzer.analyze.assert_not_called()

    prompt_builder.build.assert_called_once_with(
        "Explain the rules.",
        rules=RuleContext(),
        knowledge=orchestrator.knowledge_service.load.return_value,
        memory=MemoryContext(),
        project=None,
    )


def test_explicit_project_has_priority_over_discovery(
    tmp_path: Path,
) -> None:
    explicit_project = tmp_path / "explicit"
    explicit_project.mkdir()

    project_context = Mock()

    project_locator = Mock()
    project_locator.locate.return_value = explicit_project.resolve()

    project_analyzer = Mock()
    project_analyzer.analyze.return_value = project_context

    orchestrator, _, _ = create_orchestrator(
        tmp_path,
        project_locator=project_locator,
        project_analyzer=project_analyzer,
    )

    orchestrator.ask(
        "Inspect the project.",
        project=explicit_project,
    )

    project_locator.locate.assert_called_once_with(
        explicit_project,
    )

    project_analyzer.analyze.assert_called_once_with(
        explicit_project.resolve(),
    )