"""Tests for the knowledge service."""

from pathlib import Path
from unittest.mock import Mock

from moughorai.config import AppConfig, PathSettings
from moughorai.knowledge.service import KnowledgeService
from moughorai.models.knowledge import (
    KnowledgeContext,
    KnowledgeDocument,
)


def create_config(
    workspace_root: Path,
) -> AppConfig:
    """Create a test configuration."""

    return AppConfig(
        workspace_root=workspace_root,
        paths=PathSettings(
            brain=Path("brain"),
            projects=Path("projects"),
        ),
    )


def create_document(
    name: str,
    *,
    category: str = "brain",
) -> KnowledgeDocument:
    """Create a test knowledge document."""

    return KnowledgeDocument(
        name=name,
        path=Path(name),
        category=category,
        content=f"Content for {name}",
    )


def test_load_returns_global_knowledge_without_project(
    tmp_path: Path,
) -> None:
    """Global knowledge should load when no project is supplied."""

    config = create_config(tmp_path)
    global_context = KnowledgeContext(
        documents=(create_document("global.md"),),
    )

    loader = Mock()
    loader.load.return_value = global_context

    service = KnowledgeService(
        config,
        loader,
    )

    result = service.load()

    assert result is global_context
    loader.load.assert_called_once_with(
        config.paths.brain,
        category="brain",
    )


def test_load_merges_project_knowledge(
    tmp_path: Path,
) -> None:
    """Project knowledge should be merged with global knowledge."""

    config = create_config(tmp_path)
    project = tmp_path / "demo"
    project.mkdir()

    project_knowledge_directory = (
        tmp_path
        / config.paths.projects
        / project.name
    )
    project_knowledge_directory.mkdir(parents=True)

    global_document = create_document("global.md")
    project_document = create_document(
        "project.md",
        category="project",
    )

    loader = Mock()
    loader.load.side_effect = [
        KnowledgeContext(
            documents=(global_document,),
        ),
        KnowledgeContext(
            documents=(project_document,),
        ),
    ]

    service = KnowledgeService(
        config,
        loader,
    )

    result = service.load(
        project=project,
    )

    assert result.documents == (
        global_document,
        project_document,
    )

    assert loader.load.call_count == 2
    loader.load.assert_any_call(
        config.paths.brain,
        category="brain",
    )
    loader.load.assert_any_call(
        config.paths.projects / project.name,
        category="project",
    )


def test_load_returns_retrieved_knowledge(
    tmp_path: Path,
) -> None:
    """Relevant retrieved knowledge should take priority."""

    config = create_config(tmp_path)

    full_context = KnowledgeContext(
        documents=(create_document("global.md"),),
    )
    retrieved_context = KnowledgeContext(
        documents=(create_document("selected.md"),),
    )

    loader = Mock()
    loader.load.return_value = full_context

    retriever = Mock()
    retriever.retrieve.return_value = retrieved_context

    service = KnowledgeService(
        config,
        loader,
        retriever,
    )

    result = service.load(
        query="selected topic",
    )

    assert result is retrieved_context
    retriever.retrieve.assert_called_once_with(
        "selected topic"
    )


def test_load_falls_back_when_retrieval_is_empty(
    tmp_path: Path,
) -> None:
    """Empty retrieval should fall back to full knowledge."""

    config = create_config(tmp_path)

    full_context = KnowledgeContext(
        documents=(create_document("global.md"),),
    )

    loader = Mock()
    loader.load.return_value = full_context

    retriever = Mock()
    retriever.retrieve.return_value = KnowledgeContext()

    service = KnowledgeService(
        config,
        loader,
        retriever,
    )

    result = service.load(
        query="missing topic",
    )

    assert result is full_context