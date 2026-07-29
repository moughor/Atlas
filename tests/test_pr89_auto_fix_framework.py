from pathlib import Path

import pytest

from moughorai.rule_sdk import (
    AutoFixError,
    AutoFixPlanner,
    FileFixApplier,
    FixPlan,
    FixSafety,
    RuleAuthoringError,
    RuleContext,
    RuleExecutionError,
    RuleFix,
    RuleRunner,
    RuleSeverity,
    SourceEdit,
)


class TodoRule:
    rule_id = "TODO"
    default_severity = RuleSeverity.LOW

    def analyze(self, context, reporter):
        offset = context.source.find("TODO")
        if offset >= 0:
            reporter.report("TODO marker")

    def fix(self, context, finding):
        offset = context.source.index("TODO")
        return RuleFix(
            self.rule_id,
            "Remove TODO",
            (SourceEdit(context.path, offset, offset + 4, "DONE", "TODO"),),
        )


def context(source="TODO") -> RuleContext:
    return RuleContext(Path("app.py"), source, "python", {})


def plan(rule=TodoRule(), source="TODO") -> FixPlan:
    item = context(source)
    findings = RuleRunner().run((rule,), item)
    return AutoFixPlanner().plan((rule,), item, findings)


def test_planner_builds_rule_fix() -> None:
    result = plan()
    assert len(result.fixes) == 1
    assert result.fixes[0].title == "Remove TODO"


def test_apply_safe_fix_in_memory() -> None:
    result = plan().apply({"app.py": "TODO"})
    assert result.as_dict()[Path("app.py")] == "DONE"
    assert result.changed_files == (Path("app.py"),)
    assert result.applied_rules == ("TODO",)


def test_multiple_non_overlapping_edits_apply_from_right_to_left() -> None:
    edits = (
        SourceEdit(Path("a"), 0, 1, "A", "a"),
        SourceEdit(Path("a"), 2, 3, "C", "c"),
    )
    result = FixPlan((RuleFix("R", "upper", edits),)).apply({"a": "abc"})
    assert result.as_dict()[Path("a")] == "AbC"


def test_review_fix_is_skipped_by_default() -> None:
    review = RuleFix("R", "review", (SourceEdit(Path("a"), 0, 1, "x"),), FixSafety.REVIEW)
    default = FixPlan((review,)).apply({"a": "a"})
    included = FixPlan((review,)).apply({"a": "a"}, include_review=True)
    assert default.as_dict()[Path("a")] == "a"
    assert default.skipped_review == 1
    assert included.as_dict()[Path("a")] == "x"


def test_overlapping_edits_are_rejected() -> None:
    fixes = (
        RuleFix("A", "a", (SourceEdit(Path("x"), 0, 2, ""),)),
        RuleFix("B", "b", (SourceEdit(Path("x"), 1, 3, ""),)),
    )
    with pytest.raises(AutoFixError, match="conflicting"):
        FixPlan(fixes).apply({"x": "abc"})


def test_same_position_insertions_are_rejected() -> None:
    fixes = (
        RuleFix("A", "a", (SourceEdit(Path("x"), 1, 1, "a"),)),
        RuleFix("B", "b", (SourceEdit(Path("x"), 1, 1, "b"),)),
    )
    with pytest.raises(AutoFixError, match="conflicting"):
        FixPlan(fixes).apply({"x": "x"})


def test_stale_and_out_of_range_edits_are_rejected() -> None:
    with pytest.raises(AutoFixError, match="stale"):
        FixPlan((RuleFix("R", "x", (SourceEdit(Path("a"), 0, 1, "x", "z"),)),)).apply({"a": "a"})
    with pytest.raises(AutoFixError, match="outside"):
        FixPlan((RuleFix("R", "x", (SourceEdit(Path("a"), 0, 2, "x"),)),)).apply({"a": "a"})


def test_missing_source_is_rejected() -> None:
    with pytest.raises(AutoFixError, match="missing source"):
        plan().apply({})


def test_edit_and_fix_validation() -> None:
    with pytest.raises(AutoFixError, match="offsets"):
        SourceEdit(Path("a"), 2, 1, "")
    with pytest.raises(AutoFixError, match="at least one"):
        RuleFix("R", "x", ())
    with pytest.raises(AutoFixError, match="sorted"):
        RuleFix("R", "x", (SourceEdit(Path("a"), 2, 2, "x"), SourceEdit(Path("a"), 1, 1, "y")))


def test_planner_ignores_rules_without_fix_provider() -> None:
    class NoFix(TodoRule):
        fix = None
    item = context()
    findings = RuleRunner().run((NoFix(),), item)
    assert AutoFixPlanner().plan((NoFix(),), item, findings).fixes == ()


def test_planner_validates_provider_results() -> None:
    class WrongType(TodoRule):
        def fix(self, context, finding): return "bad"
    item = context()
    findings = RuleRunner().run((WrongType(),), item)
    with pytest.raises(RuleAuthoringError, match="RuleFix"):
        AutoFixPlanner().plan((WrongType(),), item, findings)

    class WrongId(TodoRule):
        def fix(self, context, finding):
            return RuleFix("OTHER", "bad", (SourceEdit(context.path, 0, 1, ""),))
    with pytest.raises(RuleAuthoringError, match="id mismatch"):
        AutoFixPlanner().plan((WrongId(),), item, findings)


def test_fix_provider_exception_is_attributed() -> None:
    class Broken(TodoRule):
        def fix(self, context, finding): raise RuntimeError("boom")
    item = context()
    findings = RuleRunner().run((Broken(),), item)
    with pytest.raises(RuleExecutionError, match="TODO fix: RuntimeError: boom"):
        AutoFixPlanner().plan((Broken(),), item, findings)


def test_file_applier_supports_dry_run_and_apply(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("TODO")
    dry = FileFixApplier().apply(plan(), tmp_path, dry_run=True)
    assert dry.as_dict()[Path("app.py")] == "DONE"
    assert target.read_text() == "TODO"
    FileFixApplier().apply(plan(), tmp_path)
    assert target.read_text() == "DONE"


def test_file_applier_rejects_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("x")
    escape = FixPlan((RuleFix("R", "bad", (SourceEdit(Path("..") / "outside.py", 0, 1, "y"),)),))
    with pytest.raises(AutoFixError, match="escapes"):
        FileFixApplier().apply(escape, tmp_path)


def test_plans_and_results_are_deterministic() -> None:
    first = plan()
    second = plan()
    assert first == second
    assert first.apply({"app.py": "TODO"}) == second.apply({"app.py": "TODO"})
