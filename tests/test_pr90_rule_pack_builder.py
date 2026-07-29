import hashlib
import json
from pathlib import PurePosixPath
import zipfile

import pytest

from moughorai.rule_sdk import (
    RULE_PACK_SCHEMA_VERSION,
    RuleMetadata,
    RulePackBuilder,
    RulePackError,
    RulePackReader,
    RulePackSpec,
    RuleSeverity,
    rule_metadata,
)


@rule_metadata(RuleMetadata(
    "TODO", "TODO rule", "Detects TODO markers.", RuleSeverity.LOW,
    category="style", languages=("python",), tags=("maintainability",),
))
class TodoRule:
    rule_id = "TODO"
    default_severity = RuleSeverity.LOW
    def analyze(self, context, reporter): pass


def spec(**values):
    return RulePackSpec(
        values.pop("name", "atlas-demo"),
        values.pop("version", "1.2.3"),
        entry_points=values.pop("entry_points", (("TODO", "rules.todo:TodoRule"),)),
        **values,
    )


def files():
    return {
        "rules/__init__.py": "",
        "rules/todo.py": "class TodoRule:\n    pass\n",
    }


def test_builds_verified_rule_pack(tmp_path) -> None:
    result = RulePackBuilder().build(spec(), (TodoRule(),), files(), tmp_path / "demo.zip")
    assert result.path.is_file()
    assert result.sha256 == hashlib.sha256(result.path.read_bytes()).hexdigest()
    manifest = RulePackReader().verify(result.path)
    assert manifest["schema_version"] == RULE_PACK_SCHEMA_VERSION
    assert manifest["rules"][0]["entry_point"] == "rules.todo:TodoRule"


def test_build_is_byte_reproducible(tmp_path) -> None:
    first = RulePackBuilder().build(spec(), (TodoRule(),), files(), tmp_path / "a.zip")
    second = RulePackBuilder().build(spec(), (TodoRule(),), dict(reversed(list(files().items()))), tmp_path / "b.zip")
    assert first.path.read_bytes() == second.path.read_bytes()
    assert first.sha256 == second.sha256


def test_archive_entries_and_timestamps_are_deterministic(tmp_path) -> None:
    result = RulePackBuilder().build(spec(), (TodoRule(),), files(), tmp_path / "demo.zip")
    with zipfile.ZipFile(result.path) as archive:
        assert archive.namelist() == ["manifest.json", "rules/__init__.py", "rules/todo.py"]
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())


def test_manifest_contains_metadata_and_hashes(tmp_path) -> None:
    result = RulePackBuilder().build(spec(dependencies=("core>=1",)), (TodoRule(),), files(), tmp_path / "demo.zip")
    manifest = result.manifest
    assert manifest["dependencies"] == ["core>=1"]
    assert manifest["rules"][0]["tags"] == ["maintainability"]
    assert [record["path"] for record in manifest["files"]] == ["rules/__init__.py", "rules/todo.py"]


def test_entry_points_must_match_rules(tmp_path) -> None:
    with pytest.raises(RulePackError, match="do not match"):
        RulePackBuilder().build(spec(entry_points=()), (TodoRule(),), files(), tmp_path / "demo.zip")


def test_entry_point_module_must_be_included(tmp_path) -> None:
    with pytest.raises(RulePackError, match="not included"):
        RulePackBuilder().build(spec(), (TodoRule(),), {"other.py": ""}, tmp_path / "demo.zip")


@pytest.mark.parametrize("path", ["/absolute.py", "../escape.py", "a/../b.py", ""])
def test_unsafe_source_paths_are_rejected(tmp_path, path) -> None:
    with pytest.raises(RulePackError, match="unsafe"):
        RulePackBuilder().build(spec(), (TodoRule(),), {path: ""}, tmp_path / "demo.zip")


def test_reserved_manifest_path_is_rejected(tmp_path) -> None:
    with pytest.raises(RulePackError, match="reserved"):
        RulePackBuilder().build(spec(), (TodoRule(),), {"manifest.json": "{}"}, tmp_path / "demo.zip")


@pytest.mark.parametrize("version", ["1", "v1.0.0", "01.0.0"])
def test_semantic_versions_are_required(version) -> None:
    with pytest.raises(RulePackError, match="semantic"):
        spec(version=version)


def test_spec_validates_name_entry_points_and_dependencies() -> None:
    with pytest.raises(RulePackError, match="name"):
        spec(name="bad name")
    with pytest.raises(RulePackError, match="entry point"):
        spec(entry_points=(("TODO", "not valid"),))
    with pytest.raises(RulePackError, match="dependencies"):
        spec(dependencies=("z", "a"))


def test_reader_detects_checksum_tampering(tmp_path) -> None:
    target = RulePackBuilder().build(spec(), (TodoRule(),), files(), tmp_path / "demo.zip").path
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(target, "a") as archive:
            archive.writestr("rules/todo.py", "tampered")
    with pytest.raises(RulePackError, match="duplicate archive entries"):
        RulePackReader().verify(target)


def test_reader_rejects_bad_archive(tmp_path) -> None:
    target = tmp_path / "bad.zip"
    target.write_text("bad")
    with pytest.raises(RulePackError, match="archive"):
        RulePackReader().verify(target)


def test_reader_rejects_undeclared_file(tmp_path) -> None:
    target = RulePackBuilder().build(spec(), (TodoRule(),), files(), tmp_path / "demo.zip").path
    with zipfile.ZipFile(target, "a") as archive:
        archive.writestr("extra.txt", "x")
    with pytest.raises(RulePackError, match="undeclared"):
        RulePackReader().verify(target)


def test_manifest_json_is_canonical(tmp_path) -> None:
    target = RulePackBuilder().build(spec(), (TodoRule(),), files(), tmp_path / "demo.zip").path
    with zipfile.ZipFile(target) as archive:
        raw = archive.read("manifest.json").decode()
    assert raw.endswith("\n")
    assert raw.strip() == json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def test_pure_posix_paths_are_supported(tmp_path) -> None:
    source_files = {PurePosixPath(key): value for key, value in files().items()}
    assert RulePackBuilder().build(spec(), (TodoRule(),), source_files, tmp_path / "demo.zip").path.exists()
