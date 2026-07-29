"""Statistics collection for classified project files."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from moughorai.project_inventory.models import (
    DirectoryStatistic,
    FileStatistic,
    ProjectFile,
    ProjectInventory,
)


class ProjectStatisticsCollector:
    """Build immutable project inventory statistics."""

    def __init__(self, *, largest_directories_limit: int = 10) -> None:
        if largest_directories_limit < 0:
            raise ValueError("largest_directories_limit must be non-negative")

        self._largest_directories_limit = largest_directories_limit

    def collect(
        self,
        *,
        root: Path,
        files: tuple[ProjectFile, ...],
        total_directories: int,
    ) -> ProjectInventory:
        """Aggregate classified files into one project inventory."""

        total_size = sum(file.size for file in files)
        total_files = len(files)
        average_file_size = (
            total_size / total_files
            if total_files
            else 0.0
        )
        largest_file = max(
            files,
            key=lambda file: file.size,
            default=None,
        )

        return ProjectInventory(
            root=root,
            total_files=total_files,
            total_directories=total_directories,
            total_size=total_size,
            average_file_size=average_file_size,
            largest_file=largest_file,
            files=files,
            languages=self._collect_named_statistics(
                files,
                lambda file: file.language,
            ),
            extensions=self._collect_named_statistics(
                files,
                lambda file: file.extension or "[no extension]",
            ),
            kinds=self._collect_named_statistics(
                files,
                lambda file: file.kind.value,
            ),
            largest_directories=self._collect_directory_statistics(files),
        )

    @staticmethod
    def _collect_named_statistics(
        files: tuple[ProjectFile, ...],
        name_getter,
    ) -> tuple[FileStatistic, ...]:
        counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])

        for file in files:
            name = name_getter(file)

            if name is None:
                continue

            counts[name][0] += 1
            counts[name][1] += file.size

        statistics = (
            FileStatistic(
                name=name,
                files=values[0],
                size=values[1],
            )
            for name, values in counts.items()
        )

        return tuple(
            sorted(
                statistics,
                key=lambda statistic: (
                    -statistic.files,
                    -statistic.size,
                    statistic.name.casefold(),
                ),
            )
        )

    def _collect_directory_statistics(
        self,
        files: tuple[ProjectFile, ...],
    ) -> tuple[DirectoryStatistic, ...]:
        counts: dict[Path, list[int]] = defaultdict(lambda: [0, 0])

        for file in files:
            parent = file.relative_path.parent
            counts[parent][0] += 1
            counts[parent][1] += file.size

        statistics = (
            DirectoryStatistic(
                path=path,
                files=values[0],
                size=values[1],
            )
            for path, values in counts.items()
        )

        ordered = sorted(
            statistics,
            key=lambda statistic: (
                -statistic.size,
                -statistic.files,
                statistic.path.as_posix().casefold(),
            ),
        )

        return tuple(ordered[: self._largest_directories_limit])
