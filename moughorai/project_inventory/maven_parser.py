"""Safe deterministic parser for Maven ``pom.xml`` files."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ElementTree

from moughorai.project_inventory.maven_models import (
    MavenDependency,
    MavenModule,
    MavenParent,
    MavenPlugin,
    MavenProject,
)


class MavenParseError(ValueError):
    """Raised when a Maven POM cannot be parsed safely."""


class MavenParser:
    """Parse Maven project metadata using only the Python standard library."""

    DEFAULT_PACKAGING = "jar"
    DEFAULT_PLUGIN_GROUP = "org.apache.maven.plugins"

    def parse(self, pom_path: Path) -> MavenProject:
        """Parse one Maven POM from disk."""

        path = Path(pom_path)

        if not path.is_file():
            raise MavenParseError(f"Maven POM does not exist: {path}")

        try:
            root = ElementTree.parse(path).getroot()
        except (ElementTree.ParseError, OSError) as error:
            raise MavenParseError(
                f"Unable to parse Maven POM: {path}"
            ) from error

        return MavenProject(
            pom_path=path.resolve(),
            model_version=self._child_text(root, "modelVersion"),
            group_id=self._child_text(root, "groupId"),
            artifact_id=self._child_text(root, "artifactId"),
            version=self._child_text(root, "version"),
            packaging=(
                self._child_text(root, "packaging")
                or self.DEFAULT_PACKAGING
            ),
            name=self._child_text(root, "name"),
            parent=self._parse_parent(root),
            properties=self._parse_properties(root),
            dependencies=self._parse_dependencies(
                self._child(root, "dependencies")
            ),
            managed_dependencies=self._parse_dependencies(
                self._child(
                    self._child(root, "dependencyManagement"),
                    "dependencies",
                )
            ),
            plugins=self._parse_plugins(
                self._child(self._child(root, "build"), "plugins")
            ),
            modules=self._parse_modules(self._child(root, "modules")),
        )

    def parse_many(
        self,
        pom_paths: tuple[Path, ...] | list[Path],
    ) -> tuple[MavenProject, ...]:
        """Parse multiple POMs in deterministic path order."""

        return tuple(
            self.parse(path)
            for path in sorted(
                pom_paths,
                key=lambda item: Path(item).as_posix().casefold(),
            )
        )

    def _parse_parent(
        self,
        project: ElementTree.Element,
    ) -> MavenParent | None:
        parent = self._child(project, "parent")
        if parent is None:
            return None

        group_id = self._child_text(parent, "groupId")
        artifact_id = self._child_text(parent, "artifactId")
        version = self._child_text(parent, "version")

        if group_id is None or artifact_id is None or version is None:
            return None

        return MavenParent(
            group_id=group_id,
            artifact_id=artifact_id,
            version=version,
            relative_path=self._child_text(parent, "relativePath"),
        )

    def _parse_properties(
        self,
        project: ElementTree.Element,
    ) -> tuple[tuple[str, str], ...]:
        properties = self._child(project, "properties")
        if properties is None:
            return ()

        values: list[tuple[str, str]] = []

        for element in properties:
            name = self._local_name(element.tag)
            value = self._text(element)
            if value is not None:
                values.append((name, value))

        return tuple(sorted(values, key=lambda item: item[0].casefold()))

    def _parse_dependencies(
        self,
        dependencies: ElementTree.Element | None,
    ) -> tuple[MavenDependency, ...]:
        if dependencies is None:
            return ()

        parsed: list[MavenDependency] = []

        for dependency in self._children(dependencies, "dependency"):
            group_id = self._child_text(dependency, "groupId")
            artifact_id = self._child_text(dependency, "artifactId")

            if group_id is None or artifact_id is None:
                continue

            optional = (
                self._child_text(dependency, "optional") or ""
            ).casefold() == "true"

            parsed.append(
                MavenDependency(
                    group_id=group_id,
                    artifact_id=artifact_id,
                    version=self._child_text(dependency, "version"),
                    scope=self._child_text(dependency, "scope"),
                    dependency_type=self._child_text(dependency, "type"),
                    classifier=self._child_text(
                        dependency,
                        "classifier",
                    ),
                    optional=optional,
                )
            )

        return tuple(parsed)

    def _parse_plugins(
        self,
        plugins: ElementTree.Element | None,
    ) -> tuple[MavenPlugin, ...]:
        if plugins is None:
            return ()

        parsed: list[MavenPlugin] = []

        for plugin in self._children(plugins, "plugin"):
            artifact_id = self._child_text(plugin, "artifactId")
            if artifact_id is None:
                continue

            parsed.append(
                MavenPlugin(
                    group_id=(
                        self._child_text(plugin, "groupId")
                        or self.DEFAULT_PLUGIN_GROUP
                    ),
                    artifact_id=artifact_id,
                    version=self._child_text(plugin, "version"),
                )
            )

        return tuple(parsed)

    def _parse_modules(
        self,
        modules: ElementTree.Element | None,
    ) -> tuple[MavenModule, ...]:
        if modules is None:
            return ()

        parsed = []

        for module in self._children(modules, "module"):
            path = self._text(module)
            if path is not None:
                parsed.append(MavenModule(path=path))

        return tuple(parsed)

    @classmethod
    def _child(
        cls,
        element: ElementTree.Element | None,
        name: str,
    ) -> ElementTree.Element | None:
        if element is None:
            return None

        for child in element:
            if cls._local_name(child.tag) == name:
                return child

        return None

    @classmethod
    def _children(
        cls,
        element: ElementTree.Element,
        name: str,
    ) -> tuple[ElementTree.Element, ...]:
        return tuple(
            child
            for child in element
            if cls._local_name(child.tag) == name
        )

    @classmethod
    def _child_text(
        cls,
        element: ElementTree.Element | None,
        name: str,
    ) -> str | None:
        return cls._text(cls._child(element, name))

    @staticmethod
    def _text(element: ElementTree.Element | None) -> str | None:
        if element is None or element.text is None:
            return None

        value = element.text.strip()
        return value or None

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", maxsplit=1)[-1]
