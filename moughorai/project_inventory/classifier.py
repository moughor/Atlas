"""Deterministic project file classification."""

from __future__ import annotations

from pathlib import Path

from moughorai.project_inventory.models import FileKind, ProjectFile, ScannedFile

_LANGUAGE_BY_EXTENSION = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".go": "Go",
    ".groovy": "Groovy",
    ".h": "C/C++ Header",
    ".hpp": "C++ Header",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".php": "PHP",
    ".pl": "Perl",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".scala": "Scala",
    ".sh": "Shell",
    ".sql": "SQL",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
}

_CONFIG_EXTENSIONS = {
    ".conf",
    ".config",
    ".ini",
    ".json",
    ".properties",
    ".toml",
    ".xml",
    ".yaml",
    ".yml",
}

_ARCHIVE_EXTENSIONS = {
    ".7z",
    ".ear",
    ".gz",
    ".jar",
    ".rar",
    ".tar",
    ".war",
    ".zip",
}

_BINARY_EXTENSIONS = {
    ".class",
    ".dll",
    ".dylib",
    ".exe",
    ".o",
    ".obj",
    ".pdb",
    ".pyc",
    ".so",
}

_DOCUMENTATION_EXTENSIONS = {
    ".adoc",
    ".md",
    ".rst",
    ".txt",
}

_ASSET_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".svg",
    ".webp",
    ".woff",
    ".woff2",
}

_BUILD_FILE_NAMES = {
    "build.gradle",
    "build.gradle.kts",
    "dockerfile",
    "gradle.properties",
    "makefile",
    "package-lock.json",
    "package.json",
    "pom.xml",
    "pyproject.toml",
    "requirements.txt",
    "settings.gradle",
    "settings.gradle.kts",
}

GENERATED_DIRECTORY_NAMES = frozenset({
    "generated",
    "generated-sources",
    "generated-test-sources",
    "target",
    "build",
    "dist",
    "out",
})

# Internal compatibility alias for the existing classifier implementation.
_GENERATED_DIRECTORY_NAMES = GENERATED_DIRECTORY_NAMES

TEST_SOURCE_ROOT_NAMES = frozenset({
    "test",
    "tests",
    "testing",
    "testfixture",
    "testfixtures",
    "integration-test",
    "integration-tests",
    "integrationtest",
    "integrationtests",
    "it",
    "tck",
    "spec",
    "specs",
})

TEST_TREE_DIRECTORY_NAMES = frozenset({
    *TEST_SOURCE_ROOT_NAMES,
    "__tests__",
    "example",
    "examples",
    "sample",
    "samples",
    "fixture",
    "fixtures",
})


def is_test_source_path(path: Path) -> bool:
    """Classify conventional test source paths without matching package names."""

    parts = tuple(part.casefold() for part in path.parts[:-1])
    try:
        source_root_index = parts.index("src")
    except ValueError:
        return bool(set(parts) & TEST_TREE_DIRECTORY_NAMES)
    source_kind = (
        parts[source_root_index + 1]
        if source_root_index + 1 < len(parts)
        else ""
    )
    if source_kind in TEST_SOURCE_ROOT_NAMES:
        return True
    return bool(set(parts[:source_root_index]) & TEST_TREE_DIRECTORY_NAMES)


class ProjectClassifier:
    """Classify scanned files using filenames, extensions, and paths."""

    def classify(self, file: ScannedFile) -> ProjectFile:
        """Return a classified project file."""

        language = _LANGUAGE_BY_EXTENSION.get(file.extension)
        kind = self._classify_kind(file, language)

        return ProjectFile(
            path=file.path,
            relative_path=file.relative_path,
            size=file.size,
            extension=file.extension,
            language=language,
            kind=kind,
        )

    def classify_many(
        self,
        files: tuple[ScannedFile, ...],
    ) -> tuple[ProjectFile, ...]:
        """Classify multiple scanned files while preserving order."""

        return tuple(self.classify(file) for file in files)

    def _classify_kind(
        self,
        file: ScannedFile,
        language: str | None,
    ) -> FileKind:
        path_parts = {
            part.casefold()
            for part in file.relative_path.parts[:-1]
        }
        filename = file.relative_path.name.casefold()

        if path_parts & _GENERATED_DIRECTORY_NAMES:
            return FileKind.GENERATED

        if filename in _BUILD_FILE_NAMES:
            return FileKind.BUILD

        if language is not None:
            return FileKind.SOURCE

        if file.extension in _CONFIG_EXTENSIONS:
            return FileKind.CONFIG

        if file.extension in _ARCHIVE_EXTENSIONS:
            return FileKind.ARCHIVE

        if file.extension in _BINARY_EXTENSIONS:
            return FileKind.BINARY

        if file.extension in _DOCUMENTATION_EXTENSIONS:
            return FileKind.DOCUMENTATION

        if file.extension in _ASSET_EXTENSIONS:
            return FileKind.ASSET

        return FileKind.UNKNOWN
