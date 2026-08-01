from __future__ import annotations

from pathlib import Path
import re

from moughorai.project_inventory.maven_parser import MavenParseError, MavenParser
from moughorai.project_locator import DEFAULT_PROJECT_MARKERS

from .loader import WorkspaceLoader
from .files import DEFAULT_IGNORED_DIRECTORIES
from .models import GRADLE_SETTINGS_MEMBERSHIP_OPTION, Project, Workspace


class WorkspaceDiscovery:
    DEFAULT_IGNORED = DEFAULT_IGNORED_DIRECTORIES

    def __init__(self, *, markers: tuple[str, ...] = DEFAULT_PROJECT_MARKERS, ignored: frozenset[str] = DEFAULT_IGNORED) -> None:
        self.markers = markers
        self.ignored = ignored
        self.loader = WorkspaceLoader()
        self.maven_parser = MavenParser()

    def discover(self, root: Path | str, *, max_depth: int = 4) -> Workspace:
        workspace_root = Path(root).expanduser().resolve()
        if not workspace_root.is_dir():
            raise FileNotFoundError(f"workspace root not found: {workspace_root}")
        config = self.loader.find_config(workspace_root)
        if config is not None:
            return self.loader.load(config)
        projects: list[Project] = []
        for directory in self._directories(workspace_root, max_depth=max_depth):
            if self._is_project(directory):
                relative = directory.relative_to(workspace_root)
                name = workspace_root.name if relative == Path(".") else "-".join(relative.parts)
                projects.append(Project(name=name, path=directory))
        projects = self._gradle_projects(workspace_root, projects)
        projects.extend(self._maven_projects(workspace_root, projects))
        projects = self._exclude_nested_projects(projects)
        return Workspace(root=workspace_root, projects=tuple(sorted(projects, key=lambda item: item.name)))

    def _maven_projects(self, root: Path, existing: list[Project]) -> list[Project]:
        """Discover explicit Maven reactor modules beyond the generic depth limit."""

        workspace_root = root.resolve()
        known_paths = {project.path.resolve() for project in existing}
        pending = sorted(
            (path for path in known_paths if (path / "pom.xml").is_file()),
            key=lambda path: path.as_posix().casefold(),
        )
        parsed_paths: set[Path] = set()
        discovered: list[Project] = []

        while pending:
            project_path = pending.pop(0)
            if project_path in parsed_paths:
                continue
            parsed_paths.add(project_path)
            try:
                model = self.maven_parser.parse(project_path / "pom.xml")
            except MavenParseError:
                continue

            for module in sorted(model.modules, key=lambda item: item.path.casefold()):
                declared = project_path / module.path
                pom = declared if declared.name == "pom.xml" else declared / "pom.xml"
                if not pom.is_file():
                    continue
                module_path = pom.parent.resolve()
                try:
                    relative = module_path.relative_to(workspace_root)
                except ValueError:
                    continue
                if module_path not in known_paths:
                    known_paths.add(module_path)
                    discovered.append(Project("-".join(relative.parts), module_path))
                if module_path not in parsed_paths:
                    pending.append(module_path)
            pending.sort(key=lambda path: path.as_posix().casefold())

        return discovered

    @staticmethod
    def _gradle_projects(root: Path, existing: list[Project]) -> list[Project]:
        """Merge projects proven by literal Gradle settings declarations."""
        workspace_root = root.resolve()
        settings_files = tuple(
            root / filename
            for filename in ("settings.gradle", "settings.gradle.kts")
            if (root / filename).is_file()
        )
        if len(settings_files) != 1:
            return list(existing)
        settings = settings_files[0]
        try:
            source = settings.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            return list(existing)

        declarations: dict[Path, tuple[str, str, set[str]]] = {}
        ambiguous_paths: set[Path] = set()
        for token in _literal_gradle_includes(source):
            parts = _gradle_project_parts(token)
            if not parts:
                continue
            declared_logical_path = ":" + ":".join(parts)
            evidence = f"{settings.name}#include({declared_logical_path})"
            for count in range(1, len(parts) + 1):
                prefix = parts[:count]
                logical_path = ":" + ":".join(prefix)
                try:
                    path = root.joinpath(*prefix).resolve()
                    path.relative_to(workspace_root)
                except (OSError, RuntimeError, ValueError):
                    break
                if path == workspace_root or not path.is_dir():
                    break
                if _has_path_in(path, ambiguous_paths):
                    break
                current = declarations.get(path)
                if current is None:
                    declarations[path] = (
                        "-".join(prefix),
                        logical_path,
                        {evidence},
                    )
                elif current[1] == logical_path:
                    current[2].add(evidence)
                else:
                    declarations.pop(path)
                    ambiguous_paths.add(path)
                    break

        result = list(existing)
        indexes = {
            project.path.resolve(): index
            for index, project in enumerate(result)
        }
        declaration_paths = tuple(
            path
            for path in declarations
            if not _has_path_in(path, ambiguous_paths)
        )
        paths_by_name: dict[str, set[Path]] = {}
        for project in result:
            paths_by_name.setdefault(project.name, set()).add(project.path.resolve())
        for path in declaration_paths:
            index = indexes.get(path)
            name = result[index].name if index is not None else declarations[path][0]
            paths_by_name.setdefault(name, set()).add(path)
        ambiguous_names = {
            name for name, paths in paths_by_name.items() if len(paths) > 1
        }
        ambiguous_name_roots: set[Path] = set()
        for path in declaration_paths:
            index = indexes.get(path)
            name = result[index].name if index is not None else declarations[path][0]
            if name in ambiguous_names:
                ambiguous_name_roots.add(path)
        if ambiguous_name_roots:
            result = [
                project
                for project in result
                if not _has_path_in(project.path.resolve(), ambiguous_name_roots)
            ]
            indexes = {
                project.path.resolve(): index
                for index, project in enumerate(result)
            }
        for path in sorted(
            declaration_paths,
            key=lambda item: (item.as_posix().casefold(), item.as_posix()),
        ):
            if _has_path_in(path, ambiguous_name_roots):
                continue
            name, _logical_path, evidence = declarations[path]
            option_value = "|".join(sorted(evidence))
            index = indexes.get(path)
            if index is None:
                indexes[path] = len(result)
                result.append(Project(
                    name,
                    path,
                    options=((GRADLE_SETTINGS_MEMBERSHIP_OPTION, option_value),),
                ))
                continue
            project = result[index]
            options = project.option_map
            prior = options.get(GRADLE_SETTINGS_MEMBERSHIP_OPTION)
            if prior:
                option_value = "|".join(sorted({*prior.split("|"), *evidence}))
            options[GRADLE_SETTINGS_MEMBERSHIP_OPTION] = option_value
            result[index] = Project(
                project.name,
                project.path,
                project.dependencies,
                project.include,
                project.exclude,
                tuple(sorted(options.items())),
            )
        return result

    @staticmethod
    def _exclude_nested_projects(projects: list[Project]) -> list[Project]:
        """Assign nested source trees to their most specific discovered project."""
        result: list[Project] = []
        resolved = tuple((project, project.path.resolve()) for project in projects)
        for project, project_path in resolved:
            nested: list[str] = []
            for candidate, candidate_path in resolved:
                if candidate is project:
                    continue
                try:
                    relative = candidate_path.relative_to(project_path)
                except ValueError:
                    continue
                nested.append(f"{relative.as_posix()}/**/*")
            result.append(
                Project(
                    project.name,
                    project.path,
                    project.dependencies,
                    project.include,
                    tuple(sorted(set(project.exclude).union(nested))),
                    project.options,
                )
            )
        return result

    def _directories(self, root: Path, *, max_depth: int):
        pending = [(root, 0)]
        while pending:
            directory, depth = pending.pop(0)
            yield directory
            if depth >= max_depth:
                continue
            try:
                children = sorted(
                    (
                        item
                        for item in directory.iterdir()
                        if item.is_dir()
                        and not item.name.startswith(".")
                        and item.name not in self.ignored
                    ),
                    key=lambda item: item.name,
                )
            except OSError:
                children = ()
            pending.extend((child, depth + 1) for child in children)

    def _is_project(self, directory: Path) -> bool:
        return any((directory / marker).exists() for marker in self.markers)


def _literal_gradle_includes(source: str) -> tuple[str, ...]:
    """Return literal ``include`` arguments without evaluating Gradle code."""
    lines = _strip_gradle_comments(source).splitlines()
    top_level = _gradle_top_level_lines(lines)
    result: set[str] = set()
    index = 0
    while index < len(lines):
        if not top_level[index]:
            index += 1
            continue
        match = re.match(r"^\s*include(.*)$", lines[index])
        if match is None:
            index += 1
            continue
        tail = match.group(1)
        if not tail or (not tail[0].isspace() and not tail.startswith("(")):
            index += 1
            continue
        remainder = tail.strip()
        if remainder.startswith("("):
            argument_lines = [remainder[1:]]
            closing = argument_lines[-1].find(")")
            while closing < 0 and index + 1 < len(lines):
                index += 1
                argument_lines.append(lines[index])
                closing = argument_lines[-1].find(")")
            if closing < 0 or argument_lines[-1][closing + 1 :].strip() not in {"", ";"}:
                index += 1
                continue
            argument_lines[-1] = argument_lines[-1][:closing]
            arguments = "\n".join(argument_lines)
        else:
            arguments = remainder[:-1].rstrip() if remainder.endswith(";") else remainder
        result.update(_literal_gradle_arguments(arguments))
        index += 1
    return tuple(sorted(result, key=lambda item: (item.casefold(), item)))


def _gradle_top_level_lines(lines: list[str]) -> tuple[bool, ...]:
    """Identify statically top-level lines using a bounded linear scan."""
    result: list[bool] = []
    delimiters: list[str] = []
    quote: str | None = None
    valid = True
    pairs = {"(": ")", "[": "]", "{": "}"}
    controls = re.compile(
        r"^\s*(?:if|else\b|for|while|switch|try|catch|finally|do|return|throw)\b"
    )
    continuation = re.compile(
        r"(?:&&|\|\||<=>|==?|!=|<=?|>=?|<<|>>>?|"
        r"[?:+\-*%&|^=.,\\]|\b(?:as|in|instanceof))\s*$"
    )
    for line in lines:
        at_top_level = valid and not delimiters and quote is None
        result.append(at_top_level)
        position = 0
        while valid and position < len(line):
            character = line[position]
            if quote is not None:
                if character == "\\" and position + 1 < len(line):
                    position += 2
                    continue
                if character == quote:
                    quote = None
                position += 1
                continue
            if character in {"'", '"'}:
                quote = character
            elif character == "/":
                # Comments were already masked. Any remaining slash may begin a
                # Groovy slashy literal or expression that this parser cannot prove.
                valid = False
            elif character in pairs:
                delimiters.append(character)
            elif character in pairs.values():
                if not delimiters or pairs[delimiters[-1]] != character:
                    valid = False
                else:
                    delimiters.pop()
            position += 1
        if quote is not None:
            valid = False
        if at_top_level and controls.match(line):
            valid = False
        if at_top_level and not delimiters and continuation.search(line):
            # A following line can be part of this expression. Once that
            # relationship is ambiguous, no later declaration is promoted to
            # unconditional settings evidence.
            valid = False
    return tuple(result)


def _has_path_in(path: Path, ancestors: set[Path]) -> bool:
    """Return whether ``path`` is at or below an ambiguous resolved path."""
    return path in ancestors or any(parent in ancestors for parent in path.parents)


def _literal_gradle_arguments(value: str) -> tuple[str, ...]:
    """Parse only comma-separated single- or double-quoted string literals."""
    result: list[str] = []
    position = 0
    length = len(value)
    while True:
        while position < length and value[position].isspace():
            position += 1
        if position == length:
            return tuple(result)
        quote = value[position]
        if quote not in {"'", '"'}:
            return ()
        closing = value.find(quote, position + 1)
        if closing < 0:
            return ()
        token = value[position + 1 : closing]
        if "\\" in token or "$" in token or any(
            ord(character) < 32 or ord(character) == 127
            for character in token
        ):
            return ()
        result.append(token)
        position = closing + 1
        while position < length and value[position].isspace():
            position += 1
        if position == length:
            return tuple(result)
        if value[position] != ",":
            return ()
        position += 1
        if not value[position:].strip():
            return ()


def _gradle_project_parts(token: str) -> tuple[str, ...]:
    if not token or token != token.strip():
        return ()
    normalized = token
    if normalized.startswith(":"):
        normalized = normalized[1:]
    parts = tuple(normalized.split(":"))
    if not parts or any(
        not part
        or part in {".", ".."}
        or any(
            character in "/\\$|"
            or ord(character) < 32
            or ord(character) == 127
            for character in part
        )
        for part in parts
    ):
        return ()
    return parts


def _strip_gradle_comments(source: str) -> str:
    """Mask comments with spaces while preserving strings and newlines."""
    result: list[str] = []
    position = 0
    quote: str | None = None
    while position < len(source):
        character = source[position]
        following = source[position + 1] if position + 1 < len(source) else ""
        if quote is not None:
            result.append(character)
            if character == "\\" and following:
                result.append(following)
                position += 2
                continue
            if character == quote:
                quote = None
            position += 1
            continue
        if character in {"'", '"'}:
            quote = character
            result.append(character)
            position += 1
            continue
        if character == "/" and following == "/":
            result.extend((" ", " "))
            position += 2
            while position < len(source) and source[position] not in "\r\n":
                result.append(" ")
                position += 1
            continue
        if character == "/" and following == "*":
            result.extend((" ", " "))
            position += 2
            while position < len(source):
                if source[position : position + 2] == "*/":
                    result.extend((" ", " "))
                    position += 2
                    break
                if source[position] in "\r\n":
                    result.append(source[position])
                else:
                    result.append(" ")
                position += 1
            continue
        result.append(character)
        position += 1
    return "".join(result)
