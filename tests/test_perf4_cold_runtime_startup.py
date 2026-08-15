from __future__ import annotations

from moughorai import atlas_cli
from moughorai.repository_runtime import RepositoryRuntimeSession
from moughorai.semantic_search import SemanticSearchRequest

from test_pr159_java_code_impact import _entry, pr159_fixture


def _semantic_results(session, snapshot, query: str, limit: int):
    runtime = session.runtime_for(snapshot)
    response = runtime.semantic_search.search_semantic(
        SemanticSearchRequest(query, limit=limit)
    )
    return tuple(
        atlas_cli._authoritative_session_search_result(runtime, hit)
        for hit in response.hits
    )


def test_exact_identity_search_eliminates_full_semantic_projection(
    pr159_fixture,
    capsys,
) -> None:
    changed = _entry(pr159_fixture, 'Target', 'changed')
    snapshot = pr159_fixture['snapshot']
    reference_session = RepositoryRuntimeSession()
    expected = _semantic_results(reference_session, snapshot, 'changed', 10)
    assert dict(reference_session.statistics.component_build_counts) == {
        'canonical_subject_resolver': 1,
        'java_code_intelligence': 1,
        'semantic_search': 1,
    }

    optimized_session = RepositoryRuntimeSession()
    actual = atlas_cli._session_search(
        optimized_session, snapshot, 'changed', 10,
    )

    assert actual == expected
    assert actual[0].canonical_subject_id == changed.canonical_subject_id
    assert dict(optimized_session.statistics.component_build_counts) == {
        'canonical_subject_resolver': 1,
        'java_code_intelligence': 1,
    }
    capsys.readouterr()


def test_non_exact_search_falls_back_to_one_reused_semantic_projection(
    pr159_fixture,
    capsys,
) -> None:
    snapshot = pr159_fixture['snapshot']
    session = RepositoryRuntimeSession()

    first = atlas_cli._session_search(session, snapshot, 'method changed', 10)
    second = atlas_cli._session_search(session, snapshot, 'method changed', 10)

    assert first == second
    assert dict(session.statistics.component_build_counts) == {
        'canonical_subject_resolver': 1,
        'java_code_intelligence': 1,
        'semantic_search': 1,
    }
    capsys.readouterr()


def test_unresolved_exact_identity_fails_over_without_stale_results(
    pr159_fixture,
    capsys,
) -> None:
    snapshot = pr159_fixture['snapshot']
    session = RepositoryRuntimeSession()

    results = atlas_cli._session_search(
        session, snapshot, 'noSuchSubjectNameThatCannotMatch', 10,
    )

    assert results == ()
    assert dict(session.statistics.component_build_counts) == {
        'canonical_subject_resolver': 1,
        'semantic_search': 1,
    }
    capsys.readouterr()
