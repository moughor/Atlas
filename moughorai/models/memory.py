"""Typed memory models used across MoughorAI."""

from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
)


class MemoryDocument(BaseModel):
    """One memory document loaded from the workspace."""

    name: str = Field(
        min_length=1,
        description="Human-readable memory document name.",
    )
    path: Path = Field(
        description="Absolute or workspace-relative source path.",
    )
    category: str = Field(
        min_length=1,
        description=(
            "Memory category such as architecture, decisions, "
            "mistakes, or todo."
        ),
    )
    content: str = Field(
        min_length=1,
        description="Full textual content of the memory document.",
    )

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    @computed_field
    @property
    def suffix(self) -> str:
        """Return the lower-case file extension."""
        return self.path.suffix.lower()

    @computed_field
    @property
    def character_count(self) -> int:
        """Return the number of characters in the document."""
        return len(self.content)

    @computed_field
    @property
    def line_count(self) -> int:
        """Return the number of logical lines in the document."""
        return len(self.content.splitlines())

    def render(self) -> str:
        """Render the memory as a structured prompt section."""
        return (
            f"## Memory: {self.name}\n"
            f"Category: {self.category}\n"
            f"Path: {self.path.as_posix()}\n\n"
            f"{self.content.strip()}"
        )


class MemoryContext(BaseModel):
    """A collection of memory documents for one AI request."""

    documents: tuple[MemoryDocument, ...] = Field(
        default_factory=tuple,
    )

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    @computed_field
    @property
    def document_count(self) -> int:
        """Return the number of loaded memory documents."""
        return len(self.documents)

    @computed_field
    @property
    def total_character_count(self) -> int:
        """Return the total number of content characters."""
        return sum(
            document.character_count
            for document in self.documents
        )

    @computed_field
    @property
    def categories(self) -> tuple[str, ...]:
        """Return sorted unique memory categories."""
        return tuple(
            sorted(
                {
                    document.category
                    for document in self.documents
                }
            )
        )

    @property
    def is_empty(self) -> bool:
        """Return whether the context contains no documents."""
        return not self.documents

    def render(self) -> str:
        """Render all memories deterministically."""
        return "\n\n---\n\n".join(
            document.render()
            for document in self.documents
        )

    def by_category(
        self,
        category: str,
    ) -> tuple[MemoryDocument, ...]:
        """Return memory documents matching one category."""
        normalized_category = category.strip().casefold()

        return tuple(
            document
            for document in self.documents
            if document.category.casefold()
            == normalized_category
        )

    def with_document(
        self,
        document: MemoryDocument,
    ) -> "MemoryContext":
        """Return a new context with one additional memory."""
        return MemoryContext(
            documents=(*self.documents, document),
        )