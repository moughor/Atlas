from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.atlas_cli import app
from moughorai.llm import ScriptedLlmProvider
from moughorai.repository_runtime import RepositoryRuntimeSession

from test_pr159_java_code_impact import (
    _entry,
    _semantic_project_mismatch_snapshot,
    pr159_fixture,
)


runner = CliRunner()


@pytest.mark.parametrize(
    ('command', 'expected'),
    (
        ('/search changed', ('changed', 10)),
        ('/search cloneInternal 20', ('cloneInternal', 20)),
        ('/search changed limit=3', ('changed', 3)),
        ('/search name with spaces', ('name with spaces', 10)),
    ),
)
def test_session_search_parser_is_small_and_bounded(command, expected) -> None:
    assert atlas_cli._parse_session_search(command) == expected


@pytest.mark.parametrize(
    ('command', 'message'),
    (
        ('/search', 'usage:'),
        ('/search changed 0', 'between 1 and 20'),
        ('/search changed 21', 'between 1 and 20'),
        ('/search changed limit=nope', 'must be an integer'),
    ),
)
def test_session_search_parser_rejects_malformed_limits(command, message) -> None:
    with pytest.raises(ValueError, match=message):
        atlas_cli._parse_session_search(command)


def test_discovery_state_is_bounded_selectable_and_cleared() -> None:
    state = atlas_cli._SessionSubjectDiscovery()
    result = atlas_cli._SessionSearchResult(
        'method:123', 'app', 'demo.Target#changed()', 'method', 'java', True,
    )

    state.replace((result,))
    assert state.select(1) is result
    with pytest.raises(ValueError, match='between 1 and 1'):
        state.select(2)
    with pytest.raises(ValueError, match='exceeds its bound'):
        state.replace(tuple(result for _ in range(21)))
    state.clear()
    assert state.results == ()
    with pytest.raises(ValueError, match='run /search'):
        state.select(1)


def _invoke_session(monkeypatch, tmp_path, snapshot, commands: str):
    monkeypatch.setattr(
        atlas_cli,
        '_load_ai_snapshot',
        lambda *_args, **_kwargs: snapshot,
    )
    monkeypatch.setattr(
        atlas_cli,
        '_ai_provider_factory',
        lambda: ScriptedLlmProvider([]),
    )
    return runner.invoke(
        app,
        ['ai', 'session', str(tmp_path)],
        input=commands,
    )


def _statistics(output: str) -> dict[str, object]:
    line = next(
        item for item in output.splitlines()
        if item.startswith('{') and 'runtime_build_count' in item
    )
    return json.loads(line)


def test_session_search_is_deterministic_bounded_reused_and_selectable(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    result = _invoke_session(
        monkeypatch,
        tmp_path,
        pr159_fixture['snapshot'],
        '/help\n/search changed 1\n/search changed 1\n/use 1\n'
        '/impact\n/stats\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert '/search <text> [limit] find canonical subjects' in result.output
    assert '/use <n> select a Java method' in result.output
    assert result.output.count(f'  id: {changed.canonical_subject_id}') == 2
    assert result.output.count('  project: app') == 2
    assert result.output.count('  name: demo.Target#changed()') == 2
    assert result.output.count('  kind: method') == 2
    assert result.output.count('  language: java') == 2
    assert result.output.count('showing 1 of ') == 2
    assert f'subject={changed.canonical_subject_id}' in result.output
    assert 'project=app' in result.output
    assert 'resolution: resolved' in result.output
    statistics = _statistics(result.output)
    assert statistics['runtime_build_count'] == 1
    assert statistics['component_build_counts'] == {
        'canonical_subject_resolver': 1,
        'java_code_intelligence': 1,
    }
    assert 'Atlas session closed.' in result.output


def test_search_projects_pr156_identity_across_semantic_project_mismatch(
    pr159_fixture,
    capsys,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    snapshot, _payload, legacy_project = _semantic_project_mismatch_snapshot(
        pr159_fixture,
    )
    session = RepositoryRuntimeSession()

    first = atlas_cli._session_search(session, snapshot, 'changed', 10)
    second = atlas_cli._session_search(session, snapshot, 'changed', 10)
    target = next(
        item for item in first
        if item.canonical_subject_id == changed.canonical_subject_id
    )

    assert first == second
    assert target.project == 'app'
    assert target.project != legacy_project
    assert target.qualified_name == 'demo.Target#changed()'
    assert atlas_cli._session_use(session, snapshot, target) == (
        changed.canonical_subject_id,
        'app',
    )
    assert session.statistics.runtime_build_count == 1
    assert dict(session.statistics.component_build_counts) == {
        'canonical_subject_resolver': 1,
        'java_code_intelligence': 1,
    }
    capsys.readouterr()


def test_empty_invalid_and_excessive_searches_leave_no_stale_selection(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    result = _invoke_session(
        monkeypatch,
        tmp_path,
        pr159_fixture['snapshot'],
        '/search changed 1\n/search noSuchSubjectNameThatCannotMatch 1\n'
        '/use 1\n/search changed limit=nope\n/use 1\n'
        '/search changed 21\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert 'No canonical subjects found.' in result.output
    assert result.output.count('error: run /search before /use') == 2
    assert 'error: search limit must be an integer between 1 and 20' in result.output
    assert 'error: search limit must be between 1 and 20' in result.output


def test_wrong_project_after_search_selection_still_fails_closed(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    result = _invoke_session(
        monkeypatch,
        tmp_path,
        pr159_fixture['snapshot'],
        '/search changed 1\n/use 1\n/project definitely-wrong\n'
        '/impact\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert 'resolution: not_found' in result.output
    assert 'canonical-id:' not in result.output
    assert 'No exact represented Java method or constructor matched' in result.output
