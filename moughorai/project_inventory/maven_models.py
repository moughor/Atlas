"""Immutable models representing Maven project metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MavenCoordinate:
    """A Maven group, artifact, and optional version coordinate."""

    group_id: str
    artifact_id: str
    version: str | None = None

    @property
    def identifier(self) -> str:
        """Return the stable ``groupId:artifactId`` identifier."""

        return f"{self.group_id}:{self.artifact_id}"


@dataclass(frozen=True)
class MavenParent:
    """Parent project declared by a Maven POM."""

    group_id: str
    artifact_id: str
    version: str
    relative_path: str | None = None

    @property
    def identifier(self) -> str:
        """Return the stable ``groupId:artifactId`` identifier."""

        return f"{self.group_id}:{self.artifact_id}"


@dataclass(frozen=True)
class MavenDependency:
    """Dependency declared by a Maven POM."""

    group_id: str
    artifact_id: str
    version: str | None = None
    scope: str | None = None
    dependency_type: str | None = None
    classifier: str | None = None
    optional: bool = False

    @property
    def identifier(self) -> str:
        """Return the stable ``groupId:artifactId`` identifier."""

        return f"{self.group_id}:{self.artifact_id}"


@dataclass(frozen=True)
class MavenPlugin:
    """Build plugin declared by a Maven POM."""

    group_id: str
    artifact_id: str
    version: str | None = None

    @property
    def identifier(self) -> str:
        """Return the stable ``groupId:artifactId`` identifier."""

        return f"{self.group_id}:{self.artifact_id}"


@dataclass(frozen=True)
class MavenModule:
    """Child module declared in a Maven reactor POM."""

    path: str


@dataclass(frozen=True)
class MavenProject:
    """Parsed Maven project metadata."""

    pom_path: Path
    model_version: str | None
    group_id: str | None
    artifact_id: str | None
    version: str | None
    packaging: str
    name: str | None
    parent: MavenParent | None
    properties: tuple[tuple[str, str], ...]
    dependencies: tuple[MavenDependency, ...]
    managed_dependencies: tuple[MavenDependency, ...]
    plugins: tuple[MavenPlugin, ...]
    modules: tuple[MavenModule, ...]

    @property
    def effective_group_id(self) -> str | None:
        """Return the project group or inherited parent group."""

        if self.group_id is not None:
            return self.group_id
        if self.parent is not None:
            return self.parent.group_id
        return None

    @property
    def effective_version(self) -> str | None:
        """Return the project version or inherited parent version."""

        if self.version is not None:
            return self.version
        if self.parent is not None:
            return self.parent.version
        return None

    @property
    def coordinate(self) -> MavenCoordinate | None:
        """Return the project's effective Maven coordinate when possible."""

        group_id = self.effective_group_id
        if group_id is None or self.artifact_id is None:
            return None

        return MavenCoordinate(
            group_id=group_id,
            artifact_id=self.artifact_id,
            version=self.effective_version,
        )

    def property_value(self, name: str) -> str | None:
        """Return one declared Maven property by name."""

        for property_name, value in self.properties:
            if property_name == name:
                return value
        return None
