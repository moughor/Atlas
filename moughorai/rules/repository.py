"""Rule repository."""

from __future__ import annotations

from pathlib import Path

from moughorai.models.rule import RuleContext
from moughorai.rules.loader import RuleLoader


class RuleRepository:
    """Cache rules loaded from disk."""

    def __init__(
        self,
        loader: RuleLoader,
        directory: Path | str,
        *,
        category: str = "general",
    ) -> None:
        self._loader = loader
        self._directory = directory
        self._category = category
        self._rules: RuleContext | None = None

    def load(self) -> RuleContext:
        """Return cached rules."""

        if self._rules is None:
            self._rules = self._loader.load(
                self._directory,
                category=self._category,
            )

        return self._rules

    def reload(self) -> RuleContext:
        """Reload rules from disk."""

        self._rules = self._loader.load(
            self._directory,
            category=self._category,
        )

        return self._rules