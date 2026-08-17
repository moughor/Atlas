from __future__ import annotations

import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from moughorai import atlas_cli
from moughorai.atlas_cli import app
from moughorai.llm import (
    LlmProviderError,
    LlmResponse,
    ScriptedLlmProvider,
)

from test_pr159_java_code_impact import _entry, pr159_fixture
from test_pr170_deterministic_engineering_authority import (
    EXPECTED_TESTS,
    FORBIDDEN_TEST,
    five_root_fixture,
)


runner = CliRunner()


class _RecordingAskEngine:
    instances: list[_RecordingAskEngine] = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.requests = []
        self.__class__.instances.append(self)

    def ask(self, _snapshot, request):
        self.requests.append(request)
        return SimpleNamespace(
            answer=f'recorded request {len(self.requests)}',
            conversation_id=len(self.requests),
        )


class _FailingAskEngine:
    calls = 0

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def ask(self, _snapshot, _request):
        self.__class__.calls += 1
        raise ValueError('synthetic request failure')


class _GroundedInjectionProvider:
    name = 'grounded-injection'
    model = 'test'

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request, *, timeout_seconds):
        del timeout_seconds
        self.calls += 1
        prompt = '\n'.join(item.content for item in request.messages)
        evidence = re.search(r'evidence:[0-9a-f]{64}', prompt)
        assert evidence is not None
        return LlmResponse(
            f'{FORBIDDEN_TEST} is the only represented TEST. {evidence.group(0)}',
            self.name,
            self.model,
        )

    def stream(self, *_args, **_kwargs):
        raise AssertionError('streaming was not requested')


def _recorded_session(
    monkeypatch,
    root: Path,
    snapshot,
    commands: str,
    *extra_arguments: str,
):
    _RecordingAskEngine.instances.clear()
    monkeypatch.setattr(
        atlas_cli,
        '_load_ai_snapshot',
        lambda *_args, **_kwargs: snapshot,
    )
    monkeypatch.setattr(
        atlas_cli,
        '_ai_provider_factory',
        lambda: ScriptedLlmProvider(()),
    )
    monkeypatch.setattr(atlas_cli, 'AskEngine', _RecordingAskEngine)
    result = runner.invoke(
        app,
        ['ai', 'session', str(root), *extra_arguments],
        input=commands,
    )
    assert _RecordingAskEngine.instances
    return result, _RecordingAskEngine.instances[-1].requests


def _write_utf8(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))


def _statistics(output: str) -> dict[str, object]:
    line = next(
        item for item in output.splitlines()
        if item.startswith('{') and 'runtime_build_count' in item
    )
    return json.loads(line)


def test_ask_file_submits_complete_multiline_utf8_once_and_stays_active(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    story = 'Update erlSendingIsSigned\r\n- CERTIFICATÉ €\r\n- PRIZE'
    path = tmp_path / 'folder with spaces' / 'Jira story.txt'
    _write_utf8(path, story)

    result, requests = _recorded_session(
        monkeypatch,
        tmp_path,
        pr159_fixture['snapshot'],
        f'/ask-file {path}\n/stats\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert len(requests) == 1
    assert requests[0].question == story
    assert 'request loaded: ' in result.output
    expected_bytes = len(story.encode('utf-8'))
    assert f'({expected_bytes} bytes)' in result.output
    assert result.output.count('recorded request') == 1
    assert _statistics(result.output)['runtime_build_count'] == 0
    assert 'Atlas session closed.' in result.output


def test_story_file_and_interactive_story_submit_equivalent_single_requests(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    story = 'Update Internal service erlSendingIsSigned\n\nAccept when:\n- CERTIFICATE\n- PRIZE'
    path = tmp_path / 'story.txt'
    _write_utf8(path, story)
    commands = (
        f'/story-file {path}\n'
        '/story\n'
        'Update Internal service erlSendingIsSigned\n'
        '\n'
        'Accept when:\n'
        '- CERTIFICATE\n'
        '- PRIZE\n'
        '/end\n'
        '/exit\n'
    )

    result, requests = _recorded_session(
        monkeypatch,
        tmp_path,
        pr159_fixture['snapshot'],
        commands,
    )

    assert result.exit_code == 0, result.output
    assert len(requests) == 2
    assert requests[0].question == story
    assert requests[1].question == story
    assert requests[0].conversation_id is None
    assert requests[1].conversation_id is None
    assert result.output.count('recorded request') == 2
    assert result.output.count('story loaded: ') == 2


def test_story_buffer_preserves_newlines_and_indentation() -> None:
    buffer = atlas_cli._SessionStoryBuffer()
    for line in ('Heading', '', '  indented detail', '- bullet'):
        buffer.append(line)

    assert buffer.character_count == len(
        'Heading\n\n  indented detail\n- bullet'
    )
    assert buffer.finish() == 'Heading\n\n  indented detail\n- bullet'


def test_cancel_and_blank_story_submit_nothing(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    result, requests = _recorded_session(
        monkeypatch,
        tmp_path,
        pr159_fixture['snapshot'],
        '/story\nnot submitted\n/cancel\n/story\n/end\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert requests == []
    assert 'story canceled; no request submitted.' in result.output
    assert 'error: story is blank; nothing was submitted' in result.output


@pytest.mark.parametrize(
    ('command', 'message'),
    (
        ('/ask-file', 'usage: /ask-file <path>'),
        ('/story-file', 'usage: /story-file <path>'),
        ('/ask-file missing-story.txt', 'input file does not exist'),
        ('/story-file .', 'input path is not a regular file'),
    ),
)
def test_file_input_errors_are_useful_and_submit_nothing(
    command,
    message,
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    result, requests = _recorded_session(
        monkeypatch,
        tmp_path,
        pr159_fixture['snapshot'],
        f'{command}\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert requests == []
    assert f'error: {message}' in result.output


@pytest.mark.parametrize(
    'payload',
    (
        b'not-utf8:\xff',
        b'utf8-but-binary:\x00payload',
    ),
)
def test_binary_file_input_is_rejected(payload, tmp_path) -> None:
    path = tmp_path / 'binary.dat'
    path.write_bytes(payload)

    with pytest.raises(ValueError, match='UTF-8 plain text'):
        atlas_cli._read_session_request_file(path)


def test_unreadable_file_input_is_reported(tmp_path, monkeypatch) -> None:
    path = tmp_path / 'unreadable.txt'
    _write_utf8(path, 'story')
    original = Path.read_bytes

    def deny_selected(candidate: Path):
        if candidate == path:
            raise PermissionError('synthetic access denial')
        return original(candidate)

    monkeypatch.setattr(Path, 'read_bytes', deny_selected)
    with pytest.raises(ValueError, match='not readable'):
        atlas_cli._read_session_request_file(path)


def test_oversized_file_and_story_fail_without_silent_truncation(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    maximum = atlas_cli._SESSION_REQUEST_MAXIMUM_CHARACTERS
    path = tmp_path / 'oversized.txt'
    _write_utf8(path, 'x' * (maximum + 1))
    story_line = 'y' * (maximum + 1)

    result, requests = _recorded_session(
        monkeypatch,
        tmp_path,
        pr159_fixture['snapshot'],
        f'/ask-file {path}\n/story\n{story_line}\n/end\n/stats\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert requests == []
    assert f'accepted maximum is {maximum} characters' in result.output
    assert f'accepted maximum of {maximum} characters' in result.output
    assert 'nothing was submitted' in result.output
    assert _statistics(result.output)['runtime_build_count'] == 0


def test_byte_bound_rejects_before_reading(tmp_path, monkeypatch) -> None:
    path = tmp_path / 'too-many-bytes.txt'
    path.write_bytes(b'x' * (atlas_cli._SESSION_REQUEST_MAXIMUM_BYTES + 1))

    def unexpected_read(_candidate):
        raise AssertionError('oversized file was read')

    monkeypatch.setattr(Path, 'read_bytes', unexpected_read)
    with pytest.raises(ValueError, match='accepted maximum'):
        atlas_cli._read_session_request_file(path)


def test_file_text_is_never_shell_or_python_executed(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    marker = tmp_path / 'must-not-exist.txt'
    payload = (
        f'New-Item -Path {marker}; '
        f'__import__(pathlib).Path({marker}).write_text(bad)'
    )
    path = tmp_path / 'command-shaped story.txt'
    _write_utf8(path, payload)

    result, requests = _recorded_session(
        monkeypatch,
        tmp_path,
        pr159_fixture['snapshot'],
        f'/ask-file {path}\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert len(requests) == 1
    assert requests[0].question == payload
    assert not marker.exists()


def test_quoted_and_unquoted_paths_with_spaces_are_literal(tmp_path) -> None:
    expected = tmp_path / 'directory with spaces' / 'story text.txt'
    assert atlas_cli._parse_session_file_path(
        f'/ask-file {expected}', '/ask-file',
    ) == expected
    assert atlas_cli._parse_session_file_path(
        f'/story-file {expected}', '/story-file',
    ) == expected
    assert atlas_cli._parse_session_file_path(
        '/ask-file *.txt', '/ask-file',
    ) == Path('*.txt')


def test_normal_one_line_ask_help_and_exit_remain_unchanged(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    result, requests = _recorded_session(
        monkeypatch,
        tmp_path,
        pr159_fixture['snapshot'],
        '/help\n/ask ordinary one-line question\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert [item.question for item in requests] == [
        'ordinary one-line question'
    ]
    assert '/ask-file <path> ask using a text file as one request' in result.output
    assert '/story enter multiline story mode; finish with /end' in result.output
    assert '/story-file <path> load a story from a text file' in result.output
    assert '/cancel cancel multiline story entry' in result.output
    assert result.output.count('recorded request') == 1
    assert 'Atlas session closed.' in result.output


def test_exit_inside_story_is_text_and_exit_after_end_closes_session(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    result, requests = _recorded_session(
        monkeypatch,
        tmp_path,
        pr159_fixture['snapshot'],
        '/story\n/exit\n/end\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert [item.question for item in requests] == ['/exit']
    assert result.output.count('Atlas session closed.') == 1


def test_request_failure_does_not_terminate_session_or_fall_through(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / 'request.txt'
    _write_utf8(path, 'One bounded request')
    _FailingAskEngine.calls = 0
    monkeypatch.setattr(
        atlas_cli,
        '_load_ai_snapshot',
        lambda *_args, **_kwargs: pr159_fixture['snapshot'],
    )
    monkeypatch.setattr(
        atlas_cli,
        '_ai_provider_factory',
        lambda: ScriptedLlmProvider(()),
    )
    monkeypatch.setattr(atlas_cli, 'AskEngine', _FailingAskEngine)

    result = runner.invoke(
        app,
        ['ai', 'session', str(tmp_path)],
        input=f'/ask-file {path}\n/stats\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert _FailingAskEngine.calls == 1
    assert 'error: synthetic request failure' in result.output
    assert _statistics(result.output)['runtime_build_count'] == 0
    assert 'Atlas session closed.' in result.output


def test_search_use_selection_is_preserved_for_file_request_and_one_runtime(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    path = tmp_path / 'impact story.txt'
    _write_utf8(
        path,
        'If I modify this method, which represented tests should I inspect?',
    )
    provider = ScriptedLlmProvider(tuple(
        LlmProviderError(f'provider unavailable {ordinal}')
        for ordinal in range(6)
    ))
    monkeypatch.setattr(
        atlas_cli,
        '_load_ai_snapshot',
        lambda *_args, **_kwargs: pr159_fixture['snapshot'],
    )
    monkeypatch.setattr(atlas_cli, '_ai_provider_factory', lambda: provider)

    result = runner.invoke(
        app,
        [
            'ai', 'session', str(tmp_path),
            '--capability', 'code_impact',
        ],
        input=(
            f'/search changed 1\n/use 1\n/ask-file {path}\n'
            '/story\n'
            'If I modify this method, which represented tests should I inspect?\n'
            '/end\n/stats\n/exit\n'
        ),
    )

    assert result.exit_code == 0, result.output
    assert f'subject={changed.canonical_subject_id}' in result.output
    assert 'project=app' in result.output
    assert result.output.count('Atlas deterministic Java code-impact answer') == 2
    assert len(provider.calls) == 6
    statistics = _statistics(result.output)
    assert statistics['runtime_build_count'] == 1
    assert statistics['reuse_count'] >= 3
    assert max(statistics['component_build_counts'].values()) == 1
    assert 'Atlas session closed.' in result.output


def test_initial_subject_project_and_capability_are_preserved(
    pr159_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / 'request.txt'
    _write_utf8(path, 'What can this method affect?')

    result, requests = _recorded_session(
        monkeypatch,
        tmp_path,
        pr159_fixture['snapshot'],
        f'/story-file {path}\n/exit\n',
        '--subject', 'method:accepted',
        '--project', 'accepted-project',
        '--capability', 'code_impact',
    )

    assert result.exit_code == 0, result.output
    assert len(requests) == 1
    assert requests[0].subject == 'method:accepted'
    assert requests[0].project == 'accepted-project'
    assert requests[0].capabilities == ('code_impact',)


def test_file_request_preserves_pr170_deterministic_provider_authority(
    five_root_fixture,
    tmp_path,
    monkeypatch,
) -> None:
    fixture = five_root_fixture
    path = tmp_path / 'five-root request.txt'
    _write_utf8(
        path,
        'If I modify this method, which represented tests should I inspect first?',
    )
    provider = _GroundedInjectionProvider()
    monkeypatch.setattr(
        atlas_cli,
        '_load_ai_snapshot',
        lambda *_args, **_kwargs: fixture['snapshot'],
    )
    monkeypatch.setattr(atlas_cli, '_ai_provider_factory', lambda: provider)

    result = runner.invoke(
        app,
        [
            'ai', 'session', str(tmp_path),
            '--subject', fixture['changed'].canonical_subject_id,
            '--project', 'sygma-it-sygma-it-services',
            '--capability', 'code_impact',
        ],
        input=f'/ask-file {path}\n/stats\n/exit\n',
    )

    assert result.exit_code == 0, result.output
    assert provider.calls == 1
    assert FORBIDDEN_TEST not in result.output
    assert all(name in result.output for name in EXPECTED_TESTS)
    assert 'sendSEPEventProcessAndAssert' in result.output
    assert 'not a represented TEST root' in result.output
    assert result.output.count('Atlas deterministic Java code-impact answer') == 1
    statistics = _statistics(result.output)
    assert statistics['runtime_build_count'] == 1
    assert max(statistics['component_build_counts'].values()) == 1
