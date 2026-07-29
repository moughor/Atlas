"""Public Atlas rule-authoring API."""

from .models import RuleContext, RuleFinding, RuleLocation, RuleSeverity
from .runtime import (
    Rule,
    RuleAuthoringError,
    RuleExecutionError,
    RuleRegistry,
    RuleReporter,
    RuleRunner,
)
from .testing import ExpectedFinding, RuleTestCase, RuleTestHarness, RuleTestResult
from .metadata import RuleCatalog, RuleMetadata, metadata_for, rule_metadata

__all__ = [
    "Rule",
    "RuleAuthoringError",
    "RuleContext",
    "RuleExecutionError",
    "ExpectedFinding",
    "RuleFinding",
    "RuleLocation",
    "RuleCatalog",
    "RuleMetadata",
    "RuleRegistry",
    "RuleReporter",
    "RuleRunner",
    "RuleSeverity",
    "RuleTestCase",
    "RuleTestHarness",
    "RuleTestResult",
    "metadata_for",
    "rule_metadata",
]
