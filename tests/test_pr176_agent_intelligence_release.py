from pathlib import Path
import tomllib

from typer.testing import CliRunner

import moughorai
from moughorai.atlas_cli import app
from moughorai.version import __version__


ROOT = Path(__file__).parents[1]
runner = CliRunner()


def test_release_version_and_cli_identity_are_consistent() -> None:
    project = tomllib.loads(
        (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    )['project']
    assert project['version'] == __version__ == moughorai.__version__ == '2.1.0'
    result = runner.invoke(app, ['--version'])
    assert result.exit_code == 0
    assert result.stdout == 'Atlas 2.1.0\n'


def test_agent_context_is_discoverable_and_session_is_experimental() -> None:
    root_help = runner.invoke(app, ['--help'])
    agent_help = runner.invoke(app, ['agent', '--help'])
    context_help = runner.invoke(app, ['agent', 'context', '--help'])
    session_help = runner.invoke(app, ['ai', 'session', '--help'])
    assert all(result.exit_code == 0 for result in (
        root_help, agent_help, context_help, session_help,
    ))
    assert 'agent' in root_help.stdout
    assert 'Primary supported export workflow' in agent_help.stdout
    assert 'context' in agent_help.stdout
    normalized_context_help = ' '.join(context_help.stdout.split())
    assert 'four bounded deterministic context artifacts' in normalized_context_help
    assert '--depth' in normalized_context_help
    assert 'story|expanded' in normalized_context_help
    assert 'experimental engineering-agent runtime' in session_help.stdout


def test_release_documents_define_supported_and_experimental_boundaries() -> None:
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    architecture = (
        ROOT / 'docs' / 'architecture' / 'ATLAS_2_1_AGENT_INTELLIGENCE.md'
    ).read_text(encoding='utf-8')
    release_notes = (
        ROOT / 'docs' / 'RELEASE_NOTES_2_1.md'
    ).read_text(encoding='utf-8')
    operations = (
        ROOT / 'docs' / 'ATLAS_2_1_OPERATIONS_GUIDE.md'
    ).read_text(encoding='utf-8')
    combined = '\n'.join((readme, architecture, release_notes, operations))
    assert 'Atlas 2.1 — Agent Intelligence' in combined
    assert 'Kiro/Codex write; Atlas maps, grounds, and verifies.' in combined
    assert 'context.md' in architecture
    assert 'context.json' in architecture
    assert 'graph.json' in architecture
    assert 'graph.mmd' in architecture
    assert 'PR174 executable verification' in combined
    assert 'experimental engineering-agent runtime' in combined
    assert 'version 2.1.0' in release_notes
    assert '50,000 normalized characters' in combined
    assert '256 KiB' in combined
    assert '## Discovered roots' in architecture
    assert '--subject' not in operations.split('### Advanced/manual targeting')[0].split(
        '## Primary Atlas and Kiro/Codex workflow', 1
    )[1]
    assert '--project' not in operations.split('### Advanced/manual targeting')[0].split(
        '## Primary Atlas and Kiro/Codex workflow', 1
    )[1]
