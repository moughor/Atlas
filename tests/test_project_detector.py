from pathlib import Path

from moughorai.project_inventory.detector import ProjectTechnologyDetector
from moughorai.project_inventory.detection_models import TechnologyCategory
from moughorai.project_inventory.models import (
    FileKind,
    ProjectFile,
    ProjectInventory,
)


def project_file(
    relative_path: str,
    *,
    language: str | None = None,
    kind: FileKind = FileKind.UNKNOWN,
) -> ProjectFile:
    relative = Path(relative_path)
    return ProjectFile(
        path=Path("/project") / relative,
        relative_path=relative,
        size=10,
        extension=relative.suffix.casefold(),
        language=language,
        kind=kind,
    )


def inventory(*files: ProjectFile) -> ProjectInventory:
    return ProjectInventory(
        root=Path("/project"),
        total_files=len(files),
        total_directories=1,
        total_size=sum(file.size for file in files),
        average_file_size=10.0 if files else 0.0,
        largest_file=files[0] if files else None,
        files=files,
        languages=(),
        extensions=(),
        kinds=(),
        largest_directories=(),
    )


def test_detector_detects_maven_java_and_ear() -> None:
    result = ProjectTechnologyDetector().detect(
        inventory(
            project_file("pom.xml", kind=FileKind.BUILD),
            project_file(
                "src/App.java",
                language="Java",
                kind=FileKind.SOURCE,
            ),
            project_file("dist/app.ear", kind=FileKind.ARCHIVE),
        )
    )

    assert result.has("Maven")
    assert result.has("Java")
    assert result.has("EAR")


def test_detector_detects_gradle_from_kotlin_build_file() -> None:
    result = ProjectTechnologyDetector().detect(
        inventory(
            project_file(
                "build.gradle.kts",
                language="Kotlin",
                kind=FileKind.BUILD,
            )
        )
    )

    assert result.has("Gradle")


def test_detector_detects_node_and_npm() -> None:
    result = ProjectTechnologyDetector().detect(
        inventory(
            project_file("package.json", kind=FileKind.BUILD),
        )
    )

    assert result.has("Node.js")
    assert result.has("npm")


def test_detector_detects_python_project() -> None:
    result = ProjectTechnologyDetector().detect(
        inventory(
            project_file("pyproject.toml", kind=FileKind.BUILD),
        )
    )

    assert result.has("Python")
    assert result.has("Python Packaging")


def test_detector_detects_docker_and_git() -> None:
    result = ProjectTechnologyDetector().detect(
        inventory(
            project_file("Dockerfile", kind=FileKind.BUILD),
            project_file(".gitignore"),
            project_file(".github/workflows/test.yml"),
        )
    )

    assert result.has("Docker")
    assert result.has("Git")


def test_detector_returns_sorted_categories() -> None:
    result = ProjectTechnologyDetector().detect(
        inventory(
            project_file("pom.xml", kind=FileKind.BUILD),
            project_file(
                "src/App.java",
                language="Java",
                kind=FileKind.SOURCE,
            ),
        )
    )

    categories = [
        technology.category.value
        for technology in result.technologies
    ]

    assert categories == sorted(categories)
    assert result.by_category(TechnologyCategory.BUILD)[0].name == "Maven"
