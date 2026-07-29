from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, TypeVar
from urllib.parse import urlparse

from .models import RuleSeverity
from .runtime import Rule, RuleAuthoringError


@dataclass(frozen=True, slots=True)
class RuleMetadata:
    rule_id: str
    title: str
    description: str
    default_severity: RuleSeverity
    category: str = "general"
    tags: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    documentation_url: str | None = None
    references: tuple[str, ...] = ()
    enabled_by_default: bool = True
    deprecated: bool = False
    replaced_by: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("rule_id", self.rule_id),
            ("title", self.title),
            ("description", self.description),
            ("category", self.category),
        ):
            if not value.strip():
                raise RuleAuthoringError(f"rule metadata {name} must not be empty")
        object.__setattr__(self, "default_severity", RuleSeverity(self.default_severity))
        for name in ("tags", "languages", "references"):
            values = getattr(self, name)
            if values != tuple(sorted(set(values))):
                raise RuleAuthoringError(f"rule metadata {name} must be unique and sorted")
            if any(not value.strip() for value in values):
                raise RuleAuthoringError(f"rule metadata {name} must not contain empty values")
        for name in ("documentation_url",):
            value = getattr(self, name)
            if value is not None and urlparse(value).scheme not in {"http", "https"}:
                raise RuleAuthoringError(f"rule metadata {name} must be an HTTP(S) URL")
        for reference in self.references:
            if urlparse(reference).scheme not in {"http", "https"}:
                raise RuleAuthoringError("rule metadata references must be HTTP(S) URLs")
        if self.replaced_by == self.rule_id:
            raise RuleAuthoringError("rule metadata cannot replace itself")
        if self.replaced_by is not None and not self.deprecated:
            raise RuleAuthoringError("replaced_by requires deprecated metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "description": self.description,
            "default_severity": self.default_severity.value,
            "category": self.category,
            "tags": list(self.tags),
            "languages": list(self.languages),
            "documentation_url": self.documentation_url,
            "references": list(self.references),
            "enabled_by_default": self.enabled_by_default,
            "deprecated": self.deprecated,
            "replaced_by": self.replaced_by,
        }


T = TypeVar("T")


def rule_metadata(metadata: RuleMetadata):
    def decorate(rule_type: T) -> T:
        if hasattr(rule_type, "rule_id") and str(getattr(rule_type, "rule_id")) != metadata.rule_id:
            raise RuleAuthoringError("rule metadata id does not match rule_id")
        setattr(rule_type, "metadata", metadata)
        return rule_type
    return decorate


def metadata_for(rule: Rule) -> RuleMetadata:
    value = getattr(rule, "metadata", None)
    if value is not None:
        if not isinstance(value, RuleMetadata):
            raise RuleAuthoringError(f"{rule.rule_id}: metadata must be RuleMetadata")
        if value.rule_id != rule.rule_id:
            raise RuleAuthoringError(f"{rule.rule_id}: metadata id mismatch")
        if value.default_severity is not RuleSeverity(rule.default_severity):
            raise RuleAuthoringError(f"{rule.rule_id}: metadata severity mismatch")
        return value
    rule_id = str(rule.rule_id)
    return RuleMetadata(
        rule_id,
        rule_id,
        f"Atlas rule {rule_id}.",
        RuleSeverity(rule.default_severity),
    )


class RuleCatalog:
    def __init__(self, rules: Iterable[Rule]) -> None:
        entries = [metadata_for(rule) for rule in rules]
        ids = [entry.rule_id for entry in entries]
        if len(ids) != len(set(ids)):
            raise RuleAuthoringError("rule catalog contains duplicate rule ids")
        self._entries = tuple(sorted(entries, key=lambda item: item.rule_id))

    def entries(self) -> tuple[RuleMetadata, ...]:
        return self._entries

    def get(self, rule_id: str) -> RuleMetadata:
        for entry in self._entries:
            if entry.rule_id == rule_id:
                return entry
        raise KeyError(f"unknown rule metadata: {rule_id}")

    def select(
        self,
        *,
        category: str | None = None,
        tag: str | None = None,
        language: str | None = None,
        include_deprecated: bool = False,
    ) -> tuple[RuleMetadata, ...]:
        return tuple(
            entry for entry in self._entries
            if (include_deprecated or not entry.deprecated)
            and (category is None or entry.category == category)
            and (tag is None or tag in entry.tags)
            and (language is None or not entry.languages or language in entry.languages)
        )

    def to_dict(self) -> dict[str, Any]:
        return {"rules": [entry.to_dict() for entry in self._entries]}
