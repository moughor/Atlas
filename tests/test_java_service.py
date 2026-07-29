from pathlib import Path

import pytest

from moughorai.java_analysis.models import JavaSourceSet
from moughorai.java_analysis.service import JavaSourceAnalysisService


def test_service_discovers_and_analyzes_java_files(tmp_path: Path) -> None:
    main = tmp_path / "src/main/java/com/demo/Main.java"
    test = tmp_path / "src/test/java/com/demo/MainTest.java"
    main.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    main.write_text(
        "package com.demo; public class Main {}",
        encoding="utf-8",
    )
    test.write_text(
        "package com.demo; class MainTest {}",
        encoding="utf-8",
    )
    sources = JavaSourceAnalysisService().analyze(tmp_path)
    assert [source.path for source in sources] == [main, test]
    assert [source.source_set for source in sources] == [
        JavaSourceSet.MAIN,
        JavaSourceSet.TEST,
    ]


def test_service_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        JavaSourceAnalysisService().discover(tmp_path / "missing")
