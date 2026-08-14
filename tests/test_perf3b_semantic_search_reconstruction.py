from __future__ import annotations

import pytest

from moughorai.semantic_search import SemanticSearchRequest, SemanticSearchService
import moughorai.semantic_search.index as search_index
from moughorai.subject_resolution import CanonicalSubjectResolver, SubjectCandidate
import moughorai.subject_resolution.models as subject_models

from test_pr135_semantic_search import API, _snapshot


def test_semantic_index_retains_one_validated_candidate_projection_per_node(
    monkeypatch,
) -> None:
    snapshot = _snapshot()
    resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
    assert resolver.graph is not None
    original = SubjectCandidate.__post_init__
    constructions = 0

    def counted(candidate: SubjectCandidate) -> None:
        nonlocal constructions
        constructions += 1
        original(candidate)

    monkeypatch.setattr(SubjectCandidate, "__post_init__", counted)

    service = SemanticSearchService._from_runtime(snapshot, resolver=resolver)

    assert service._index is not None
    assert constructions == len(resolver.graph.nodes)
    assert all(entry.subject.path is None for entry in service._index.entries)


def test_source_free_index_projection_preserves_default_resolver_contract() -> None:
    snapshot = _snapshot()
    resolver = CanonicalSubjectResolver.from_snapshot(snapshot)

    ordinary = resolver.candidate_for_graph_id(API)
    source_free = resolver._source_free_candidate_for_graph_id(API)

    assert ordinary is not None
    assert source_free is not None
    assert ordinary.path is not None
    assert source_free.path is None
    expected = ordinary.to_dict()
    expected["path"] = None
    assert source_free.to_dict() == expected
    assert source_free.graph_id == ordinary.graph_id


def test_semantic_index_reuses_the_validated_resolver_graph_digest() -> None:
    snapshot = _snapshot()
    resolver = CanonicalSubjectResolver.from_snapshot(snapshot)

    service = SemanticSearchService._from_runtime(snapshot, resolver=resolver)

    assert service._index is not None
    assert service._index.graph is resolver.graph
    assert service._index.graph_digest == resolver.graph_digest


def test_build_local_validation_failure_is_not_cached_across_index_builds(
    monkeypatch,
) -> None:
    snapshot = _snapshot()
    resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
    original = search_index._safe_project_scope
    attempts = 0

    def fail_once(value, trusted):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ValueError("synthetic project validation failure")
        return original(value, trusted)

    monkeypatch.setattr(search_index, "_safe_project_scope", fail_once)

    with pytest.raises(ValueError, match="synthetic project validation failure"):
        SemanticSearchService._from_runtime(snapshot, resolver=resolver)
    recovered = SemanticSearchService._from_runtime(snapshot, resolver=resolver)

    assert recovered.search_semantic(SemanticSearchRequest(API)).hits
    assert attempts > 1


def test_candidate_safety_reuse_is_scoped_to_one_projection_build(
    monkeypatch,
) -> None:
    snapshot = _snapshot()
    resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
    candidate = resolver._source_free_candidate_for_graph_id(API)
    assert candidate is not None
    original = subject_models.contains_absolute_path_text
    validations = 0

    def counted(value: str) -> bool:
        nonlocal validations
        validations += 1
        return original(value)

    monkeypatch.setattr(subject_models, "contains_absolute_path_text", counted)

    with subject_models._subject_candidate_validation_scope():
        SubjectCandidate.from_dict(candidate.to_dict())
        first = validations
        SubjectCandidate.from_dict(candidate.to_dict())
        assert validations == first
    with subject_models._subject_candidate_validation_scope():
        SubjectCandidate.from_dict(candidate.to_dict())

    assert first > 0
    assert validations == first * 2


def test_candidate_safety_rejections_are_never_cached(monkeypatch) -> None:
    snapshot = _snapshot()
    resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
    candidate = resolver._source_free_candidate_for_graph_id(API)
    assert candidate is not None
    original = subject_models.contains_absolute_path_text
    rejected_validations = 0

    def counted(value: str) -> bool:
        nonlocal rejected_validations
        if value == "file:///private/Secret.java":
            rejected_validations += 1
        return original(value)

    monkeypatch.setattr(subject_models, "contains_absolute_path_text", counted)

    with subject_models._subject_candidate_validation_scope():
        for _ in range(2):
            with pytest.raises(ValueError, match="absolute paths"):
                SubjectCandidate(
                    candidate.canonical_id,
                    candidate.kind,
                    candidate.name,
                    "file:///private/Secret.java",
                    candidate.project,
                    candidate.language,
                    None,
                    candidate.project_scopes,
                    candidate.match_basis,
                    candidate.graph_id,
                )

    assert rejected_validations == 2


@pytest.mark.parametrize(
    "unsafe",
    (
        "C:/enterprise/private/Secret.java",
        "file:///enterprise/private/Secret.java",
        "../private/Secret.java",
        "/enterprise/private/Secret.java",
        "//server/private/Secret.java",
    ),
)
def test_source_free_projection_does_not_weaken_path_rejection(unsafe: str) -> None:
    snapshot = _snapshot()
    resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
    candidate = resolver._source_free_candidate_for_graph_id(API)

    assert candidate is not None
    with pytest.raises(ValueError):
        SubjectCandidate(
            candidate.canonical_id,
            candidate.kind,
            candidate.name,
            candidate.qualified_name,
            candidate.project,
            candidate.language,
            unsafe,
            candidate.project_scopes,
            candidate.match_basis,
            candidate.graph_id,
        )


def test_source_free_projection_preserves_windows_separator_normalization() -> None:
    snapshot = _snapshot()
    resolver = CanonicalSubjectResolver.from_snapshot(snapshot)
    candidate = resolver._source_free_candidate_for_graph_id(API)

    assert candidate is not None
    projected = SubjectCandidate(
        candidate.canonical_id,
        candidate.kind,
        candidate.name,
        candidate.qualified_name,
        candidate.project,
        candidate.language,
        "src\\main\\java\\Secret.java",
        candidate.project_scopes,
        candidate.match_basis,
        candidate.graph_id,
    )

    assert projected.path == "src/main/java/Secret.java"
