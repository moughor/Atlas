"""Typed models describing an analyzed software project."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, computed_field


class ProjectFile(BaseModel):
    """One text file selected from an analyzed project."""

    path: Path = Field(
        description="Path relative to the analyzed project root.",
    )
    content: str = Field(
        min_length=1,
        description="Normalized textual content of the file.",
    )
    truncated: bool = Field(
        default=False,
        description="Whether the original content exceeded the size limit.",
    )

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    @computed_field
    @property
    def suffix(self) -> str:
        """Return the lowercase file extension."""
        return self.path.suffix.casefold()

    @computed_field
    @property
    def character_count(self) -> int:
        """Return the number of loaded characters."""
        return len(self.content)

    @computed_field
    @property
    def line_count(self) -> int:
        """Return the number of logical lines."""
        return len(self.content.splitlines())

    def render(self) -> str:
        """Render the file as a structured project-context section."""

        truncation_note = (
            "\n[Content truncated by ProjectAnalyzer]"
            if self.truncated
            else ""
        )

        return (
            f"## Project File: {self.path.as_posix()}\n\n"
            f"{self.content.strip()}"
            f"{truncation_note}"
        )


class ProjectContext(BaseModel):
    """Structured information collected from one software project."""

    name: str = Field(
        min_length=1,
        description="Project directory name.",
    )
    root: Path = Field(
        description="Absolute path of the analyzed project.",
    )
    tree: str = Field(
        description="Deterministic textual representation of the project tree.",
    )
    files: tuple[ProjectFile, ...] = Field(
        default_factory=tuple,
    )
    skipped_file_count: int = Field(
        default=0,
        ge=0,
    )
    tree_truncated: bool = Field(
        default=False,
    )

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
    )

    @computed_field
    @property
    def file_count(self) -> int:
        """Return the number of loaded project files."""
        return len(self.files)

    @computed_field
    @property
    def total_character_count(self) -> int:
        """Return the total number of loaded characters."""
        return sum(
            project_file.character_count
            for project_file in self.files
        )

    @computed_field
    @property
    def truncated_file_count(self) -> int:
        """Return how many loaded files were truncated."""
        return sum(
            1
            for project_file in self.files
            if project_file.truncated
        )

    @property
    def is_empty(self) -> bool:
        """Return whether no useful text files were loaded."""
        return not self.files

    def render(self) -> str:
        """Render the complete project context."""

        metadata = (
            f"Project: {self.name}\n"
            f"Root: {self.root.as_posix()}\n"
            f"Loaded files: {self.file_count}\n"
            f"Skipped files: {self.skipped_file_count}\n"
            f"Loaded characters: {self.total_character_count}\n"
            f"Truncated files: {self.truncated_file_count}"
        )

        tree_note = (
            "\n[Project tree truncated]"
            if self.tree_truncated
            else ""
        )

        tree_section = (
            "## Project Structure\n\n"
            f"{self.tree or '[No files found]'}"
            f"{tree_note}"
        )

        if self.is_empty:
            files_section = (
                "## Selected Project Files\n\n"
                "No supported text files were loaded."
            )
        else:
            rendered_files = "\n\n---\n\n".join(
                project_file.render()
                for project_file in self.files
            )

            files_section = (
                "## Selected Project Files\n\n"
                f"{rendered_files}"
            )

        return "\n\n".join(
            [
                metadata,
                tree_section,
                files_section,
            ]
        )