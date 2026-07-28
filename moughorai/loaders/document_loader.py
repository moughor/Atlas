"""Generic loader for structured local documents."""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path
from typing import ClassVar, Generic, TypeVar


DocumentT = TypeVar("DocumentT")
ContextT = TypeVar("ContextT")


class DocumentLoader(
    ABC,
    Generic[DocumentT, ContextT],
):
    """Load supported text documents from local directories."""

    SUBJECT: ClassVar[str] = "Document"

    DEFAULT_EXTENSIONS: ClassVar[frozenset[str]] = frozenset(
        {
            ".md",
            ".markdown",
        }
    )

    LOADER_ERROR: ClassVar[type[RuntimeError]] = RuntimeError

    def __init__(
        self,
        workspace_root: Path,
        *,
        extensions: Iterable[str] | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()

        selected_extensions = (
            extensions
            if extensions is not None
            else self.DEFAULT_EXTENSIONS
        )

        self.extensions = frozenset(
            self._normalize_extension(extension)
            for extension in selected_extensions
        )

        if not self.extensions:
            raise ValueError(
                f"At least one {self.SUBJECT.casefold()} "
                "file extension is required."
            )

    def load(
        self,
        directory: Path | str,
        *,
        category: str,
        recursive: bool = True,
    ) -> ContextT:
        """Load all supported documents from one directory."""

        documents = self.load_directory(
            directory,
            category=category,
            recursive=recursive,
        )

        return self._create_context(documents)

    def load_directory(
        self,
        directory: Path | str,
        *,
        category: str,
        recursive: bool = True,
    ) -> tuple[DocumentT, ...]:
        """Load supported files in deterministic order."""

        normalized_category = self._normalize_category(category)
        resolved_directory = self._resolve_path(directory)

        if not resolved_directory.exists():
            raise FileNotFoundError(
                f"{self.SUBJECT} directory not found: "
                f"{resolved_directory}"
            )

        if not resolved_directory.is_dir():
            raise NotADirectoryError(
                f"{self.SUBJECT} path is not a directory: "
                f"{resolved_directory}"
            )

        pattern = "**/*" if recursive else "*"

        paths = sorted(
            (
                path
                for path in resolved_directory.glob(pattern)
                if path.is_file()
                and path.suffix.casefold() in self.extensions
            ),
            key=lambda path: path.relative_to(
                resolved_directory
            ).as_posix().casefold(),
        )

        return tuple(
            self.load_document(
                path,
                category=normalized_category,
            )
            for path in paths
        )

    def load_document(
        self,
        path: Path | str,
        *,
        category: str,
    ) -> DocumentT:
        """Load one supported document."""

        normalized_category = self._normalize_category(category)
        resolved_path = self._resolve_path(path)

        if not resolved_path.exists():
            raise FileNotFoundError(
                f"{self.SUBJECT} document not found: "
                f"{resolved_path}"
            )

        if not resolved_path.is_file():
            raise ValueError(
                f"{self.SUBJECT} document is not a file: "
                f"{resolved_path}"
            )

        if resolved_path.suffix.casefold() not in self.extensions:
            supported = ", ".join(sorted(self.extensions))

            raise ValueError(
                f"Unsupported {self.SUBJECT.casefold()} "
                f"document extension: "
                f"{resolved_path.suffix or '<none>'}. "
                f"Supported extensions: {supported}"
            )

        try:
            content = resolved_path.read_text(
                encoding="utf-8-sig",
            )
        except UnicodeDecodeError as error:
            raise self.LOADER_ERROR(
                f"{self.SUBJECT} document is not valid UTF-8: "
                f"{resolved_path}"
            ) from error
        except OSError as error:
            raise self.LOADER_ERROR(
                f"Could not read {self.SUBJECT.casefold()} "
                f"document: {resolved_path}"
            ) from error

        normalized_content = content.strip()

        if not normalized_content:
            raise self.LOADER_ERROR(
                f"{self.SUBJECT} document is empty: "
                f"{resolved_path}"
            )

        return self._create_document(
            name=resolved_path.name,
            path=self._display_path(resolved_path),
            category=normalized_category,
            content=normalized_content,
        )

    def _normalize_category(
        self,
        category: str,
    ) -> str:
        normalized_category = category.strip()

        if not normalized_category:
            raise ValueError(
                f"{self.SUBJECT} category cannot be empty."
            )

        return normalized_category

    def _resolve_path(
        self,
        path: Path | str,
    ) -> Path:
        candidate = Path(path)

        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate

        return candidate.resolve()

    def _display_path(
        self,
        path: Path,
    ) -> Path:
        try:
            return path.relative_to(self.workspace_root)
        except ValueError:
            return path

    def _normalize_extension(
        self,
        extension: str,
    ) -> str:
        normalized = extension.strip().casefold()

        if not normalized:
            raise ValueError(
                f"{self.SUBJECT} file extensions cannot be empty."
            )

        if not normalized.startswith("."):
            normalized = f".{normalized}"

        return normalized

    @abstractmethod
    def _create_document(
        self,
        *,
        name: str,
        path: Path,
        category: str,
        content: str,
    ) -> DocumentT:
        """Create the specific document model."""

    @abstractmethod
    def _create_context(
        self,
        documents: tuple[DocumentT, ...],
    ) -> ContextT:
        """Create the specific context model."""