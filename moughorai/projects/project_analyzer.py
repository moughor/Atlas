"""Analyze local software projects without invoking a language model."""

from collections.abc import Iterable
from pathlib import Path

from moughorai.models.project import (
    ProjectContext,
    ProjectFile,
)


class ProjectAnalyzerError(RuntimeError):
    """Raised when a project cannot be analyzed safely."""


class ProjectAnalyzer:
    """Inspect a project tree and load useful textual project files."""

    DEFAULT_EXCLUDED_DIRECTORIES = frozenset(
        {
            ".git",
            ".hg",
            ".idea",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".svn",
            ".tox",
            ".venv",
            ".vscode",
            "__pycache__",
            "build",
            "coverage",
            "dist",
            "htmlcov",
            "node_modules",
            "target",
            "vendor",
        }
    )

    DEFAULT_EXCLUDED_FILENAMES = frozenset(
        {
            ".env",
            ".env.local",
            ".env.production",
            ".env.development",
            "credentials.json",
            "secrets.json",
        }
    )

    DEFAULT_SUPPORTED_EXTENSIONS = frozenset(
        {
            ".c",
            ".cc",
            ".cfg",
            ".conf",
            ".cpp",
            ".cs",
            ".css",
            ".csv",
            ".go",
            ".h",
            ".hpp",
            ".html",
            ".ini",
            ".java",
            ".js",
            ".json",
            ".jsx",
            ".kt",
            ".kts",
            ".md",
            ".markdown",
            ".php",
            ".properties",
            ".ps1",
            ".py",
            ".pyi",
            ".rb",
            ".rs",
            ".scss",
            ".sh",
            ".sql",
            ".toml",
            ".ts",
            ".tsx",
            ".txt",
            ".vue",
            ".xml",
            ".yaml",
            ".yml",
        }
    )

    DEFAULT_SUPPORTED_FILENAMES = frozenset(
        {
            "dockerfile",
            "gemfile",
            "makefile",
            "procfile",
            "readme",
        }
    )

    def __init__(
        self,
        workspace_root: Path,
        *,
        excluded_directories: Iterable[str] | None = None,
        excluded_filenames: Iterable[str] | None = None,
        supported_extensions: Iterable[str] | None = None,
        max_files: int = 200,
        max_file_characters: int = 50_000,
        max_total_characters: int = 250_000,
        max_tree_entries: int = 500,
    ) -> None:
        self.workspace_root = workspace_root.resolve()

        self.excluded_directories = frozenset(
            name.casefold()
            for name in (
                excluded_directories
                if excluded_directories is not None
                else self.DEFAULT_EXCLUDED_DIRECTORIES
            )
        )

        self.excluded_filenames = frozenset(
            name.casefold()
            for name in (
                excluded_filenames
                if excluded_filenames is not None
                else self.DEFAULT_EXCLUDED_FILENAMES
            )
        )

        selected_extensions = (
            supported_extensions
            if supported_extensions is not None
            else self.DEFAULT_SUPPORTED_EXTENSIONS
        )

        self.supported_extensions = frozenset(
            self._normalize_extension(extension)
            for extension in selected_extensions
        )

        self.max_files = self._validate_positive_integer(
            max_files,
            field_name="max_files",
        )
        self.max_file_characters = self._validate_positive_integer(
            max_file_characters,
            field_name="max_file_characters",
        )
        self.max_total_characters = self._validate_positive_integer(
            max_total_characters,
            field_name="max_total_characters",
        )
        self.max_tree_entries = self._validate_positive_integer(
            max_tree_entries,
            field_name="max_tree_entries",
        )

    def analyze(
        self,
        project_path: Path | str,
    ) -> ProjectContext:
        """Analyze one local project directory."""

        root = self._resolve_path(project_path)

        if not root.exists():
            raise FileNotFoundError(
                f"Project directory not found: {root}"
            )

        if not root.is_dir():
            raise NotADirectoryError(
                f"Project path is not a directory: {root}"
            )

        discovered_files = self._discover_files(root)

        tree, tree_truncated = self._build_tree(
            root,
            discovered_files,
        )

        selected_files: list[ProjectFile] = []
        skipped_file_count = 0
        total_characters = 0

        for path in discovered_files:
            if len(selected_files) >= self.max_files:
                skipped_file_count += 1
                continue

            if not self._is_supported_file(path):
                skipped_file_count += 1
                continue

            remaining_characters = (
                self.max_total_characters
                - total_characters
            )

            if remaining_characters <= 0:
                skipped_file_count += 1
                continue

            project_file = self._load_file(
                root,
                path,
                character_limit=min(
                    self.max_file_characters,
                    remaining_characters,
                ),
            )

            if project_file is None:
                skipped_file_count += 1
                continue

            selected_files.append(project_file)
            total_characters += project_file.character_count

        return ProjectContext(
            name=root.name,
            root=root,
            tree=tree,
            files=tuple(selected_files),
            skipped_file_count=skipped_file_count,
            tree_truncated=tree_truncated,
        )

    def _discover_files(
        self,
        root: Path,
    ) -> tuple[Path, ...]:
        discovered: list[Path] = []

        try:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue

                relative_path = path.relative_to(root)

                if self._is_excluded(relative_path):
                    continue

                discovered.append(path)
        except OSError as error:
            raise ProjectAnalyzerError(
                f"Could not inspect project directory: {root}"
            ) from error

        return tuple(
            sorted(
                discovered,
                key=lambda path: path.relative_to(
                    root
                ).as_posix().casefold(),
            )
        )

    def _build_tree(
        self,
        root: Path,
        files: tuple[Path, ...],
    ) -> tuple[str, bool]:
        displayed_files = files[: self.max_tree_entries]
        tree_truncated = len(files) > len(displayed_files)

        tree = "\n".join(
            path.relative_to(root).as_posix()
            for path in displayed_files
        )

        return tree, tree_truncated

    def _load_file(
        self,
        root: Path,
        path: Path,
        *,
        character_limit: int,
    ) -> ProjectFile | None:
        try:
            content = path.read_text(
                encoding="utf-8-sig",
            )
        except UnicodeDecodeError:
            return None
        except OSError as error:
            raise ProjectAnalyzerError(
                f"Could not read project file: {path}"
            ) from error

        normalized_content = content.strip()

        if not normalized_content:
            return None

        truncated = len(normalized_content) > character_limit

        if truncated:
            normalized_content = normalized_content[
                :character_limit
            ].rstrip()

        return ProjectFile(
            path=path.relative_to(root),
            content=normalized_content,
            truncated=truncated,
        )

    def _is_excluded(
        self,
        relative_path: Path,
    ) -> bool:
        directory_parts = relative_path.parts[:-1]

        if any(
            part.casefold() in self.excluded_directories
            for part in directory_parts
        ):
            return True

        filename = relative_path.name.casefold()

        if filename in self.excluded_filenames:
            return True

        if filename.startswith(".env."):
            return True

        if filename.endswith(
            (
                ".pem",
                ".key",
                ".p12",
                ".pfx",
            )
        ):
            return True

        return False

    def _is_supported_file(
        self,
        path: Path,
    ) -> bool:
        filename = path.name.casefold()

        if filename in self.DEFAULT_SUPPORTED_FILENAMES:
            return True

        if filename.startswith("readme."):
            return True

        if filename.startswith("dockerfile."):
            return True

        return path.suffix.casefold() in self.supported_extensions

    def _resolve_path(
        self,
        path: Path | str,
    ) -> Path:
        candidate = Path(path)

        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate

        return candidate.resolve()

    @staticmethod
    def _normalize_extension(
        extension: str,
    ) -> str:
        normalized = extension.strip().casefold()

        if not normalized:
            raise ValueError(
                "Supported file extensions cannot be empty."
            )

        if not normalized.startswith("."):
            normalized = f".{normalized}"

        return normalized

    @staticmethod
    def _validate_positive_integer(
        value: int,
        *,
        field_name: str,
    ) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(
                f"{field_name} must be an integer."
            )

        if value <= 0:
            raise ValueError(
                f"{field_name} must be greater than zero."
            )

        return value