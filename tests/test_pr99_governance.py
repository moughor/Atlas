from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from moughorai.atlas_cli import app
from moughorai.governance import (
    GovernanceAction,
    GovernanceAuditLog,
    GovernanceEngine,
    GovernanceError,
    GovernancePolicy,
    GovernancePrincipal,
    GovernanceRole,
)


runner = CliRunner()


@pytest.mark.parametrize(
    ("role", "action", "allowed"),
    [
        (GovernanceRole.VIEWER, GovernanceAction.VIEW, True),
        (GovernanceRole.VIEWER, GovernanceAction.ANALYZE, False),
        (GovernanceRole.ANALYST, GovernanceAction.ANALYZE, True),
        (GovernanceRole.ANALYST, GovernanceAction.CONFIGURE, False),
        (GovernanceRole.ADMIN, GovernanceAction.MANAGE_RULES, True),
        (GovernanceRole.ADMIN, GovernanceAction.DISTRIBUTE, True),
    ],
)
def test_role_permissions(role, action, allowed) -> None:
    decision = GovernanceEngine().authorize(GovernancePrincipal("user", role), action)
    assert decision.allowed is allowed


def test_policy_constraints_are_deterministic() -> None:
    engine = GovernanceEngine(GovernancePolicy(("core",), 2, False))
    principal = GovernancePrincipal("analyst", GovernanceRole.ANALYST)
    assert engine.authorize(principal, "analyze", project="api").reason == "project-is-not-allowed"
    assert engine.authorize(principal, "analyze", project="core", workers=3).reason == "worker-limit-exceeded"
    assert engine.authorize(principal, "analyze", project="core", force=True).reason == "force-analysis-is-disabled"
    assert engine.authorize(principal, "analyze", project="core", workers=2).allowed


def test_policy_parses_pr71_options() -> None:
    policy = GovernancePolicy.from_options({
        "governance.allowed_projects": "api, core,api",
        "governance.maximum_workers": "4",
        "governance.allow_force_analysis": "true",
    })
    assert policy == GovernancePolicy(("api", "core"), 4, True)


def test_invalid_policy_values_are_rejected() -> None:
    with pytest.raises(GovernanceError):
        GovernancePolicy(maximum_workers=-1)
    with pytest.raises(GovernanceError):
        GovernancePolicy.from_options({"governance.maximum_workers": "many"})
    with pytest.raises(GovernanceError):
        GovernancePolicy.from_options({"governance.allow_force_analysis": "yes"})


def test_audit_round_trip_and_chain(tmp_path: Path) -> None:
    log = GovernanceAuditLog(tmp_path / "audit.jsonl")
    engine = GovernanceEngine()
    first = log.append(
        engine.authorize(GovernancePrincipal("alice", GovernanceRole.ANALYST), "analyze"),
        timestamp="2026-01-01T00:00:00+00:00",
    )
    second = log.append(
        engine.authorize(GovernancePrincipal("bob", GovernanceRole.VIEWER), "configure"),
        timestamp="2026-01-02T00:00:00+00:00",
    )
    assert first.sequence == 1
    assert second.previous_hash == first.record_hash
    assert log.verify() == 2
    assert not log.load()[1].decision.allowed


def test_audit_tampering_is_detected(tmp_path: Path) -> None:
    log = GovernanceAuditLog(tmp_path / "audit.jsonl")
    log.append(GovernanceEngine().authorize(GovernancePrincipal("alice", GovernanceRole.ADMIN), "configure"))
    raw = json.loads(log.path.read_text(encoding="utf-8"))
    raw["decision"]["allowed"] = False
    log.path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    with pytest.raises(GovernanceError, match="checksum"):
        log.verify()


def test_empty_audit_is_valid(tmp_path: Path) -> None:
    assert GovernanceAuditLog(tmp_path / "missing.jsonl").verify() == 0


def test_cli_verifies_default_audit_path(tmp_path: Path) -> None:
    result = runner.invoke(app, ["governance", str(tmp_path)])
    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["audit: valid", "records: 0"]


def test_empty_principal_is_rejected() -> None:
    with pytest.raises(GovernanceError):
        GovernancePrincipal(" ", GovernanceRole.ADMIN)
