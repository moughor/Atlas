from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, order=True, slots=True)
class DeclaredDependency:
    ecosystem: str
    name: str
    version: str | None
    scope: str
    source: Path
    optional: bool = False

    def deterministic_sort_key(self) -> tuple[str, str, bool, str, str, str, bool]:
        """Order dependencies without changing an unspecified version's meaning."""

        return (
            self.ecosystem,
            self.name,
            self.version is None,
            self.version or "",
            self.scope,
            self.source.as_posix(),
            self.optional,
        )

    def to_dict(self, *, root: Path | None = None) -> dict[str, object]:
        source = self.source
        if root is not None:
            try:
                source = source.resolve().relative_to(root.resolve())
            except ValueError:
                pass
        return {
            "ecosystem": self.ecosystem,
            "name": self.name,
            "version": self.version,
            "scope": self.scope,
            "optional": self.optional,
            "source": source.as_posix(),
        }
