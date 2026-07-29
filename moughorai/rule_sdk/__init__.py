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
from .fixes import (
    AutoFixError,
    AutoFixPlanner,
    AutoFixResult,
    FileFixApplier,
    FixPlan,
    FixProvider,
    FixSafety,
    RuleFix,
    SourceEdit,
)
from .pack import (
    RULE_PACK_SCHEMA_VERSION,
    RulePackBuildResult,
    RulePackBuilder,
    RulePackError,
    RulePackReader,
    RulePackSpec,
)

__all__ = [
    "AutoFixError",
    "AutoFixPlanner",
    "AutoFixResult",
    "FileFixApplier",
    "FixPlan",
    "FixProvider",
    "FixSafety",
    "Rule",
    "RuleAuthoringError",
    "RuleContext",
    "RuleExecutionError",
    "ExpectedFinding",
    "RuleFinding",
    "RuleLocation",
    "RuleFix",
    "RuleCatalog",
    "RuleMetadata",
    "RULE_PACK_SCHEMA_VERSION",
    "RulePackBuildResult",
    "RulePackBuilder",
    "RulePackError",
    "RulePackReader",
    "RulePackSpec",
    "RuleRegistry",
    "RuleReporter",
    "RuleRunner",
    "RuleSeverity",
    "RuleTestCase",
    "RuleTestHarness",
    "RuleTestResult",
    "SourceEdit",
    "metadata_for",
    "rule_metadata",
]
