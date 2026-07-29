"""Deterministic continuous-integration templates for Atlas."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import re
import tempfile


class CiTemplateError(ValueError):
    """Raised when a CI template cannot be rendered or written safely."""


class CiProvider(str, Enum):
    GITHUB = "github"
    GITLAB = "gitlab"
    AZURE = "azure"


@dataclass(frozen=True, slots=True)
class CiTemplate:
    provider: CiProvider
    path: Path
    content: str


_PYTHON_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,2}$")


class CiTemplateService:
    """Render and install supported CI configurations."""

    DEFAULT_PATHS = {
        CiProvider.GITHUB: Path(".github/workflows/atlas.yml"),
        CiProvider.GITLAB: Path(".gitlab-ci.yml"),
        CiProvider.AZURE: Path("azure-pipelines.yml"),
    }

    def render(self, provider: CiProvider | str, *, python_version: str = "3.12") -> CiTemplate:
        try:
            selected = CiProvider(provider)
        except ValueError as exc:
            raise CiTemplateError(f"unsupported CI provider: {provider}") from exc
        if not _PYTHON_VERSION.fullmatch(python_version):
            raise CiTemplateError(f"invalid Python version: {python_version}")
        renderers = {
            CiProvider.GITHUB: self._github,
            CiProvider.GITLAB: self._gitlab,
            CiProvider.AZURE: self._azure,
        }
        return CiTemplate(selected, self.DEFAULT_PATHS[selected], renderers[selected](python_version))

    def write(
        self,
        root: Path,
        provider: CiProvider | str,
        *,
        output: Path | None = None,
        python_version: str = "3.12",
        force: bool = False,
    ) -> Path:
        template = self.render(provider, python_version=python_version)
        base = root.expanduser().resolve()
        target = (output if output is not None else template.path).expanduser()
        if not target.is_absolute():
            target = base / target
        target = target.resolve()
        if target.exists() and not force:
            raise CiTemplateError(f"refusing to overwrite existing CI template: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="\n",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                stream.write(template.content)
                stream.flush()
                os.fsync(stream.fileno())
                temporary = Path(stream.name)
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target

    @staticmethod
    def _github(version: str) -> str:
        return f"""name: Atlas

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read
  security-events: write

jobs:
  atlas:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "{version}"
          cache: pip
      - run: python -m pip install .
      - run: atlas check . --format sarif > atlas.sarif
      - uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: atlas.sarif
"""

    @staticmethod
    def _gitlab(version: str) -> str:
        return f"""stages:
  - test

atlas:
  stage: test
  image: python:{version}
  script:
    - python -m pip install .
    - atlas check . --format sarif > atlas.sarif
  artifacts:
    when: always
    paths:
      - atlas.sarif
"""

    @staticmethod
    def _azure(version: str) -> str:
        return f"""trigger:
  - main

pr:
  - main

pool:
  vmImage: ubuntu-latest

steps:
  - task: UsePythonVersion@0
    inputs:
      versionSpec: "{version}"
  - script: python -m pip install .
    displayName: Install Atlas
  - script: atlas check . --format sarif > atlas.sarif
    displayName: Run Atlas
  - task: PublishBuildArtifacts@1
    condition: always()
    inputs:
      PathtoPublish: atlas.sarif
      ArtifactName: atlas-sarif
"""
