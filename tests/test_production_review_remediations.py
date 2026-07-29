from __future__ import annotations

import json
from pathlib import Path

import pytest

from moughorai.global_symbols import GlobalSymbol, GlobalSymbolDatabase, GlobalSymbolKind, SymbolId
from moughorai.incremental_analysis.models import IncrementalAnalysisPlan
from moughorai.incremental_analysis.state import IncrementalStateStore
from moughorai.java_semantics import JavaAnalysisResult, JavaSemanticFrontEnd, SemanticDocument
from moughorai.passes import ExpressionTypeInferencePass
from moughorai.project_index import ProjectFileIndexer
from moughorai.semantic import PassContext, SemanticDocument as CoreSemanticDocument
from moughorai.semantic.types import TypeTable


def _symbol(name: str, source: Path | None = None) -> GlobalSymbol:
    return GlobalSymbol(
        SymbolId(name),
        GlobalSymbolKind.TYPE,
        name,
        f"example.{name}",
        source=source,
    )


def test_incremental_state_round_trip(tmp_path: Path) -> None:
    state = IncrementalAnalysisPlan(
        changed_files=(Path("src/A.java"),),
        removed_files=(Path("src/Old.java"),),
        directly_changed_symbols=(SymbolId("A"),),
        impacted_symbols=(SymbolId("B"),),
        files_to_analyze=(Path("src/A.java"), Path("src/B.java")),
    )
    path = tmp_path / "state.json"

    store = IncrementalStateStore()
    store.save(state, path)

    assert store.load(path) == state
    assert not tuple(tmp_path.glob("state.json.*.tmp"))


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 2},
        {"schema_version": 1},
        {
            "schema_version": 1,
            "changed_files": "src/A.java",
            "removed_files": [],
            "directly_changed_symbols": [],
            "impacted_symbols": [],
            "files_to_analyze": [],
        },
        {
            "schema_version": 1,
            "changed_files": [],
            "removed_files": [],
            "directly_changed_symbols": [],
            "impacted_symbols": [],
            "files_to_analyze": [],
            "unexpected": True,
        },
    ],
)
def test_incremental_state_rejects_incompatible_data(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        IncrementalStateStore().load(path)


def test_global_symbol_snapshot_builds_detached_indexes(tmp_path: Path) -> None:
    source = tmp_path / "A.java"
    first = _symbol("A", source)
    second = _symbol("B", source)
    database = GlobalSymbolDatabase((first, second))

    snapshot = database.snapshot()
    database.remove_source(source)

    assert snapshot.get(first.id) is first
    assert snapshot.by_qualified_name(first.qualified_name) is first
    assert snapshot.find_simple("A") == (first,)
    assert snapshot.by_kind(GlobalSymbolKind.TYPE) == (first, second)
    assert snapshot.by_source(source) == (first, second)


def test_java_analysis_result_rename_preserves_legacy_identity() -> None:
    result = JavaSemanticFrontEnd().analyze_method_body("{}")

    assert isinstance(result, JavaAnalysisResult)
    assert SemanticDocument is JavaAnalysisResult


def test_project_indexer_does_not_follow_file_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target.java"
    target.write_text("class Target {}", encoding="utf-8")
    link = tmp_path / "linked.java"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")

    indexed = ProjectFileIndexer().build(tmp_path)

    assert tuple(item.relative_path for item in indexed.files) == (Path("target.java"),)


def test_expression_pass_uses_bulk_type_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    source = "{ " + " ".join(f"{index} + {index + 1};" for index in range(250)) + " }"
    syntax_tree = JavaSemanticFrontEnd().analyze_method_body(source).root
    document = CoreSemanticDocument(
        language="java",
        source=source,
        syntax_tree=syntax_tree,
    )

    def reject_copy_on_write(*args: object, **kwargs: object) -> object:
        raise AssertionError("expression pass used TypeTable.with_type")

    monkeypatch.setattr(TypeTable, "with_type", reject_copy_on_write)

    result = ExpressionTypeInferencePass().run(document, PassContext())

    assert len(result.types) >= 500
