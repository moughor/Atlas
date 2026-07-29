"""Rule loading and retrieval service."""

from __future__ import annotations

from moughorai.models.rule import RuleContext
from moughorai.rules.selector import RuleSelector


class RuleService:
    """Provide rules relevant to a user request."""

    def __init__(
        self,
        selector: RuleSelector | None = None,
    ) -> None:
        self._selector = selector

    def load(
        self,
        *,
        query: str = "",
    ) -> RuleContext:
        """Return the rules relevant to one request."""

        if self._selector is None:
            return RuleContext()

        if not query.strip():
            return RuleContext()

        return self._selector.retrieve(query)