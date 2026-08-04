from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from moughorai.ai_context.analyzer_registry import JavaLanguageAnalyzer
from moughorai.ai_context.persistence import (
    _decode_symbol,
    _encode_symbol,
    decode_analysis_result,
    encode_analysis_result,
)
from moughorai.ai_context.service import WorkspaceContextBuilder
from moughorai.global_symbols import (
    GlobalSymbol,
    GlobalSymbolDatabase,
    GlobalSymbolKind,
    GlobalSymbolStore,
    SymbolId,
)
from moughorai.java_symbols import DuplicateTypeError
from moughorai.knowledge_graph import KnowledgeGraph
from moughorai.workspace import (
    ANALYSIS_RESULT_PRODUCER_FINGERPRINT,
    Project,
    Workspace,
    WorkspaceService,
    WorkspaceStateStore,
)


def _write_java(path: Path, declaration: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"package demo; {declaration}\n", encoding="utf-8")
    return path


def _gradle_project(root: Path) -> Project:
    (root / "build.gradle").write_text("plugins {}\n", encoding="utf-8")
    return Project("demo", root)


def _analyze(project: Project, *paths: Path):
    return JavaLanguageAnalyzer().analyze(project, tuple(paths), {})


@pytest.mark.parametrize("source_set", ("main", "test"))
def test_mainnn_and_testnn_overlays_drop_exact_counterparts_and_keep_additions(
    tmp_path: Path,
    source_set: str,
) -> None:
    project = _gradle_project(tmp_path)
    baseline = _write_java(
        tmp_path / f"src/{source_set}/java/demo/Shared.java",
        "class Shared { int baseline; }",
    )
    overlay = _write_java(
        tmp_path / f"src/{source_set}22/java/demo/Shared.java",
        "class Shared { int overlay; }",
    )
    additive = _write_java(
        tmp_path / f"src/{source_set}22/java/demo/OnlyOn22.java",
        "class OnlyOn22 {}",
    )

    document = _analyze(project, overlay, additive, baseline)
    symbols = document.get_artifact("global_symbols", ())

    shared = [item for item in symbols if item.qualified_name == "demo.Shared"]
    assert len(shared) == 1
    assert shared[0].source == baseline
    assert any(item.qualified_name == "demo.OnlyOn22" for item in symbols)
    variants = [
        item
        for item in document.diagnostics
        if item.code == "ATLAS-JAVA-SOURCE-VARIANT"
    ]
    assert len(variants) == 1
    assert variants[0].location == Path(
        f"src/{source_set}22/java/demo/Shared.java"
    )


def test_ambiguous_version_roots_are_not_treated_as_independent_source_sets(
    tmp_path: Path,
) -> None:
    project = _gradle_project(tmp_path)
    first = _write_java(
        tmp_path / "src/main21/java/demo/Shared.java",
        "class Shared { int first; }",
    )
    second = _write_java(
        tmp_path / "src/main22/java/demo/Shared.java",
        "class Shared { int second; }",
    )

    with pytest.raises(DuplicateTypeError, match="demo.Shared"):
        _analyze(project, first, second)


def test_distinct_gradle_source_sets_are_isolated_without_relation_guessing(
    tmp_path: Path,
) -> None:
    project = _gradle_project(tmp_path)
    test_source = _write_java(
        tmp_path / "src/test/java/demo/Shared.java",
        "@Deprecated public class Shared { int testOnly; void run() {} "
        "public static void main(String[] args) {} }",
    )
    rest_source = _write_java(
        tmp_path / "src/javaRestTest/java/demo/Shared.java",
        "@Deprecated public class Shared { int restOnly; void run() {} "
        "public static void main(String[] args) {} }",
    )

    document = _analyze(project, test_source, rest_source)
    matches = [
        item
        for item in document.get_artifact("global_symbols", ())
        if item.kind is GlobalSymbolKind.TYPE
        and item.qualified_name == "demo.Shared"
    ]

    assert len(matches) == 2
    assert len({item.id for item in matches}) == 2
    assert {item.scope_id for item in matches} == {
        "gradle-source-set:javaRestTest",
        "gradle-source-set:test",
    }
    assert {
        dict(item.metadata)["source_scope_evidence"] for item in matches
    } == {"conventional-gradle-source-set"}
    assert {
        dict(item.metadata)["architecture_relations"] for item in matches
    } == {"unavailable"}
    assert {dict(item.metadata)["visibility"] for item in matches} == {"public"}
    assert {dict(item.metadata)["annotations"] for item in matches} == {
        "Deprecated"
    }
    assert document.get_artifact("java_architecture_graph") is None
    diagnostics = [
        item
        for item in document.diagnostics
        if item.code == "ATLAS-JAVA-SOURCE-SETS-PARTIAL"
    ]
    assert len(diagnostics) == 1
    assert diagnostics[0].location is None
    assert "architecture relations are unavailable" in diagnostics[0].message
    assert str(tmp_path) not in diagnostics[0].message
    assert "class Shared" not in diagnostics[0].message

    by_id = {
        item.id: item for item in document.get_artifact("global_symbols", ())
    }
    methods = [
        item
        for item in by_id.values()
        if item.kind is GlobalSymbolKind.METHOD
        and item.qualified_name == "demo.Shared#run()"
    ]
    assert len(methods) == 2
    assert all(by_id[item.owner_id].scope_id == item.scope_id for item in methods)
    entry_points = [
        item
        for item in by_id.values()
        if item.kind is GlobalSymbolKind.METHOD
        and dict(item.metadata).get("entry_point") == "java-main"
    ]
    assert len(entry_points) == 2
    assert all(
        by_id[item.owner_id].scope_id == item.scope_id for item in entry_points
    )

    encoded = encode_analysis_result(document)
    restored = decode_analysis_result(encoded)
    assert encode_analysis_result(restored) == encoded
    assert "package demo; class Shared" not in json.dumps(
        encoded,
        sort_keys=True,
    )


def test_source_set_isolation_is_deterministic_for_reordered_inputs(
    tmp_path: Path,
) -> None:
    project = _gradle_project(tmp_path)
    paths = (
        _write_java(
            tmp_path / "src/test/java/demo/Shared.java",
            "class Shared { int testOnly; }",
        ),
        _write_java(
            tmp_path / "src/javaRestTest/java/demo/Shared.java",
            "class Shared { int restOnly; }",
        ),
        _write_java(
            tmp_path / "src/javaRestTest/java/demo/RestOnly.java",
            "class RestOnly {}",
        ),
    )

    first = _analyze(project, *paths)
    second = _analyze(project, *reversed(paths))

    def serialized(document) -> tuple[tuple[object, ...], ...]:
        return tuple(
            (
                str(item.id),
                item.kind.value,
                item.qualified_name,
                item.scope_id,
                item.source.relative_to(tmp_path).as_posix() if item.source else None,
                item.metadata,
            )
            for item in document.get_artifact("global_symbols", ())
        )

    assert serialized(first) == serialized(second)
    assert first.diagnostics == second.diagnostics


def test_duplicate_type_within_one_source_set_still_fails(tmp_path: Path) -> None:
    project = _gradle_project(tmp_path)
    first = _write_java(
        tmp_path / "src/test/java/one/Shared.java",
        "class Shared {}",
    )
    second = _write_java(
        tmp_path / "src/test/java/two/Shared.java",
        "class Shared {}",
    )

    with pytest.raises(DuplicateTypeError, match="demo.Shared"):
        _analyze(project, first, second)


def test_scoped_identity_database_and_store_are_backward_compatible(
    tmp_path: Path,
) -> None:
    legacy = GlobalSymbol.create(
        GlobalSymbolKind.TYPE,
        "Shared",
        "demo.Shared",
        project_id="demo",
    )
    expected_legacy_id = SymbolId.from_parts(
        GlobalSymbolKind.TYPE,
        "demo.Shared",
        "demo",
    )
    first = GlobalSymbol.create(
        GlobalSymbolKind.TYPE,
        "Shared",
        "demo.Shared",
        project_id="demo",
        scope_id="gradle-source-set:test",
    )
    second = GlobalSymbol.create(
        GlobalSymbolKind.TYPE,
        "Shared",
        "demo.Shared",
        project_id="demo",
        scope_id="gradle-source-set:javaRestTest",
    )

    assert legacy.id == expected_legacy_id
    assert str(legacy.id) == "type:be95a5946e8fe4887cff5581"
    assert "scope_id" not in _encode_symbol(legacy)
    assert _decode_symbol(_encode_symbol(legacy)) == legacy
    assert _decode_symbol(_encode_symbol(first)) == first

    database = GlobalSymbolDatabase((first, second))
    assert database.find_qualified("demo.Shared") == (second, first)
    assert database.by_qualified_name("demo.Shared", "demo") == second
    database.validate()

    path = tmp_path / "symbols.json"
    GlobalSymbolStore().save(database, path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert {item["scope_id"] for item in saved["symbols"]} == {
        "gradle-source-set:javaRestTest",
        "gradle-source-set:test",
    }
    assert GlobalSymbolStore().load(path).symbols == database.symbols

    legacy_path = tmp_path / "legacy-symbols.json"
    legacy_path.write_text(
        json.dumps({
            "schema_version": 1,
            "symbols": [{
                "id": str(legacy.id),
                "kind": legacy.kind.value,
                "name": legacy.name,
                "qualified_name": legacy.qualified_name,
                "owner_id": None,
                "source": None,
                "metadata": {},
                "project_id": legacy.project_id,
            }],
        }),
        encoding="utf-8",
    )
    loaded_legacy = GlobalSymbolStore().load(legacy_path)
    assert loaded_legacy.symbols == (legacy,)
    GlobalSymbolStore().save(loaded_legacy, legacy_path)
    reencoded = json.loads(legacy_path.read_text(encoding="utf-8"))
    assert "scope_id" not in reencoded["symbols"][0]


def test_workspace_context_is_deterministic_and_omits_ambiguous_relations(
    tmp_path: Path,
) -> None:
    project = Project("demo", tmp_path)
    workspace = Workspace(tmp_path, (project,))
    first = GlobalSymbol.create(
        GlobalSymbolKind.TYPE,
        "Shared",
        "demo.Shared",
        project_id="demo",
        scope_id="gradle-source-set:test",
    )
    second = GlobalSymbol.create(
        GlobalSymbolKind.TYPE,
        "Shared",
        "demo.Shared",
        project_id="demo",
        scope_id="gradle-source-set:javaRestTest",
    )
    consumer = GlobalSymbol.create(
        GlobalSymbolKind.TYPE,
        "Consumer",
        "demo.Consumer",
        metadata={"inherits": "demo.Shared"},
        project_id="demo",
    )

    builder = WorkspaceContextBuilder()
    first_context = builder.build(
        workspace,
        symbols=(first, second, consumer),
    )
    second_context = builder.build(
        workspace,
        symbols=(consumer, second, first),
    )

    assert first_context.to_json() == second_context.to_json()
    payload = first_context.to_dict()
    assert KnowledgeGraph.from_dict(
        payload["semantic_graph"]
    ).to_dict() == payload["semantic_graph"]
    nodes = {
        item["id"]: item for item in payload["semantic_graph"]["nodes"]
    }
    assert nodes[str(first.id)]["metadata"]["scope_id"] == first.scope_id
    assert nodes[str(second.id)]["metadata"]["scope_id"] == second.scope_id
    assert not any(
        item["source"] == str(consumer.id)
        and item["kind"] == "inheritance"
        for item in payload["semantic_graph"]["edges"]
    )


def test_previous_analysis_producer_is_invalidated(tmp_path: Path) -> None:
    (tmp_path / "atlas.yaml").write_text(
        "projects:\n  - name: demo\n    path: .\n",
        encoding="utf-8",
    )
    service = WorkspaceService(tmp_path)
    store = WorkspaceStateStore(service)
    current = store.capture({"demo": {"status": "old"}}, ("demo",))
    stale = replace(
        current,
        producer_fingerprint=ANALYSIS_RESULT_PRODUCER_FINGERPRINT.replace(
            "workspace-analysis-result-v6",
            "workspace-analysis-result-v5",
        ),
    )

    results, report = store.restore(stale)

    assert ANALYSIS_RESULT_PRODUCER_FINGERPRINT.endswith(
        "workspace-analysis-result-v6"
    )
    assert results == {}
    assert report.invalidated == ("demo",)


@pytest.mark.parametrize("scope_id", ("", "   ", " source-set:test "))
def test_scope_identity_rejects_empty_or_untrimmed_values(
    tmp_path: Path,
    scope_id: str,
) -> None:
    with pytest.raises(ValueError, match="scope_id"):
        SymbolId.from_parts(
            GlobalSymbolKind.TYPE,
            "demo.Shared",
            "demo",
            scope_id,
        )
    with pytest.raises(ValueError, match="scope_id"):
        GlobalSymbol.create(
            GlobalSymbolKind.TYPE,
            "Shared",
            "demo.Shared",
            project_id="demo",
            scope_id=scope_id,
        )

    encoded = _encode_symbol(GlobalSymbol.create(
        GlobalSymbolKind.TYPE,
        "Shared",
        "demo.Shared",
        project_id="demo",
    ))
    encoded["scope_id"] = scope_id
    with pytest.raises(ValueError, match="scope_id"):
        _decode_symbol(encoded)

    store_path = tmp_path / "invalid-scope.json"
    store_path.write_text(
        json.dumps({
            "schema_version": 1,
            "symbols": [{
                "id": "type:persisted",
                "kind": "type",
                "name": "Shared",
                "qualified_name": "demo.Shared",
                "owner_id": None,
                "source": None,
                "metadata": {},
                "project_id": "demo",
                "scope_id": scope_id,
            }],
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="scope_id"):
        GlobalSymbolStore().load(store_path)
