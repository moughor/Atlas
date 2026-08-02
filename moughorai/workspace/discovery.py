from __future__ import annotations

from dataclasses import dataclass
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

        def record_declaration(
            path: Path,
            name: str,
            logical_path: str,
            evidence: str,
        ) -> bool:
            try:
                path = path.resolve()
                path.relative_to(workspace_root)
            except (OSError, RuntimeError, ValueError):
                return False
            if path == workspace_root or not path.is_dir():
                return False
            if _has_path_in(path, ambiguous_paths):
                return False
            current = declarations.get(path)
            if current is None:
                declarations[path] = (name, logical_path, {evidence})
                return True
            if current[1] == logical_path:
                current[2].add(evidence)
                return True
            declarations.pop(path)
            ambiguous_paths.add(path)
            return False

        for token in _literal_gradle_includes(source):
            parts = _gradle_project_parts(token)
            if not parts:
                continue
            declared_logical_path = ":" + ":".join(parts)
            evidence = f"{settings.name}#include({declared_logical_path})"
            for count in range(1, len(parts) + 1):
                prefix = parts[:count]
                logical_path = ":" + ":".join(prefix)
                if not record_declaration(
                    root.joinpath(*prefix),
                    "-".join(prefix),
                    logical_path,
                    evidence,
                ):
                    break

        for membership in _recursive_gradle_memberships(source, root, settings.name):
            record_declaration(
                membership.path,
                "-".join(membership.parts),
                ":" + ":".join(membership.parts),
                membership.evidence,
            )

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


@dataclass(frozen=True)
class _RecursiveGradleHelper:
    name: str
    skipped_names: tuple[str, ...]
    skipped_paths: tuple[str, ...]
    remapped_path_prefix: str | None


@dataclass(frozen=True)
class _RecursiveGradleMembership:
    path: Path
    parts: tuple[str, ...]
    evidence: str


def _recursive_gradle_memberships(
    source: str,
    root: Path,
    settings_name: str,
) -> tuple[_RecursiveGradleMembership, ...]:
    """Prove memberships from a narrowly verified recursive Gradle helper."""
    helpers = {
        helper.name: helper
        for helper in _recursive_gradle_helpers(source)
    }
    if not helpers:
        return ()

    workspace_root = root.resolve()
    seen: set[Path] = set()

    stripped = _strip_gradle_comments(source)
    lines = stripped.splitlines()
    top_level = _gradle_top_level_lines(lines)
    invocations: list[
        tuple[_RecursiveGradleHelper, tuple[str, ...], Path, tuple[str, ...]]
    ] = []
    for line_index, (line, is_top_level) in enumerate(zip(lines, top_level)):
        if not is_top_level:
            continue
        for helper in helpers.values():
            invocation = _literal_recursive_gradle_invocation(line, helper, root)
            if invocation is not None:
                prior_source = "\n".join(lines[:line_index])
                if _has_unmodeled_gradle_membership_mutation(prior_source):
                    continue
                invocations.append((
                    helper,
                    invocation[0],
                    invocation[1],
                    _literal_gradle_includes(prior_source),
                ))
                break

    result: list[_RecursiveGradleMembership] = []

    def visit(
        helper: _RecursiveGradleHelper,
        prefix: tuple[str, ...],
        directory: Path,
    ) -> None:
        pending = [(prefix, directory)]
        while pending:
            current_prefix, current = pending.pop()
            if current.is_symlink():
                continue
            try:
                resolved = current.resolve()
                resolved.relative_to(workspace_root)
            except (OSError, RuntimeError, ValueError):
                continue
            if resolved in seen or not resolved.is_dir():
                continue
            if current.name in helper.skipped_names:
                continue
            if not (resolved / "build.gradle").is_file():
                continue
            if (resolved / "settings.gradle").exists():
                continue

            parts = (*current_prefix, current.name)
            logical_path = _canonical_gradle_logical_path(parts)
            if logical_path is None:
                continue
            if logical_path in helper.skipped_paths:
                continue
            prior_logical_path = (
                ":" + ":".join(current_prefix)
                if current_prefix
                else ""
            )
            mapping_applies = (
                helper.remapped_path_prefix is not None
                and (
                    not prior_logical_path
                    or prior_logical_path.startswith(helper.remapped_path_prefix)
                )
            )
            try:
                default_path = workspace_root.joinpath(*parts).resolve()
            except (OSError, RuntimeError):
                continue
            if resolved != default_path and not mapping_applies:
                continue

            seen.add(resolved)
            result.append(
                _RecursiveGradleMembership(
                    resolved,
                    parts,
                    f"{settings_name}#recursive({helper.name},{logical_path})",
                )
            )
            try:
                children = sorted(
                    (item for item in resolved.iterdir() if item.is_dir()),
                    key=lambda item: (item.name.casefold(), item.name),
                    reverse=True,
                )
            except OSError:
                continue
            pending.extend((parts, child) for child in children)

    for helper, prefix, invocation_root, prior_includes in invocations:
        for token in prior_includes:
            parts = _gradle_project_parts(token)
            for count in range(1, len(parts) + 1):
                try:
                    path = root.joinpath(*parts[:count]).resolve()
                    path.relative_to(workspace_root)
                except (OSError, RuntimeError, ValueError):
                    break
                seen.add(path)
        visit(helper, prefix, invocation_root)
    return tuple(result)


def _canonical_gradle_logical_path(parts: tuple[str, ...]) -> str | None:
    """Return a logical path only when its round-trip preserves every segment."""
    logical_path = ":" + ":".join(parts)
    if _gradle_project_parts(logical_path) != parts:
        return None
    return logical_path


def _has_unmodeled_gradle_membership_mutation(source: str) -> bool:
    """Reject prior settings mutations that can change ``findProject`` results."""
    stripped = _strip_gradle_comments(source)
    lines = stripped.splitlines()
    top_level = _gradle_top_level_lines(lines)
    for line, is_top_level in zip(lines, top_level):
        if not is_top_level:
            continue
        if re.match(r"^\s*includeFlat\b", line):
            return True
        if re.match(r"^\s*include\b", line):
            tokens = _literal_gradle_includes(line)
            if not tokens or any(not _gradle_project_parts(token) for token in tokens):
                return True
        if re.search(r"\bprojectDir\s*=|\.setProjectDir\s*\(", line):
            return True
    return False


def _recursive_gradle_helpers(source: str) -> tuple[_RecursiveGradleHelper, ...]:
    """Return only helper definitions whose recursive semantics are provable."""
    stripped = _strip_gradle_comments(source)
    kept_lines = stripped.splitlines(keepends=True)
    lines = [line.rstrip("\r\n") for line in kept_lines]
    top_level = _gradle_top_level_lines(lines)
    header = re.compile(
        r"^\s*void\s+(?P<name>[A-Za-z_]\w*)\s*\(\s*"
        r"String\s+(?P<path>[A-Za-z_]\w*)\s*,\s*"
        r"File\s+(?P<directory>[A-Za-z_]\w*)\s*\)\s*\{\s*$"
    )
    definitions: dict[str, _RecursiveGradleHelper | None] = {}
    offset = 0
    for line, kept_line, is_top_level in zip(lines, kept_lines, top_level):
        match = header.fullmatch(line) if is_top_level else None
        if match is not None:
            opening = offset + line.rfind("{")
            body = _gradle_braced_body(stripped, opening)
            helper = None
            if body is not None:
                helper = _parse_recursive_gradle_helper(
                    match.group("name"),
                    match.group("path"),
                    match.group("directory"),
                    body,
                )
            name = match.group("name")
            definitions[name] = (
                helper if name not in definitions else None
            )
        offset += len(kept_line)
    return tuple(
        helper
        for name, helper in sorted(definitions.items())
        if helper is not None
    )


def _gradle_braced_body(source: str, opening: int) -> str | None:
    if opening < 0 or opening >= len(source) or source[opening] != "{":
        return None
    depth = 0
    quote: str | None = None
    position = opening
    while position < len(source):
        character = source[position]
        if quote is not None:
            if character == "\\" and position + 1 < len(source):
                position += 2
                continue
            if character == quote:
                quote = None
            position += 1
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[opening + 1 : position]
            if depth < 0:
                return None
        elif character == "/":
            # Comments were already masked. Slashy strings and division make
            # structural verification ambiguous, so the helper is rejected.
            return None
        position += 1
    return None


def _parse_recursive_gradle_helper(
    name: str,
    path_parameter: str,
    directory_parameter: str,
    body: str,
) -> _RecursiveGradleHelper | None:
    lines = tuple(line.strip() for line in body.splitlines() if line.strip())
    required_guards = {
        "directory": re.compile(
            rf"{re.escape(directory_parameter)}\.isDirectory\(\)\s*==\s*false"
        ),
        "build": re.compile(
            rf"new\s+File\(\s*{re.escape(directory_parameter)}\s*,\s*"
            r"(['\"])build\.gradle\1\s*\)\.exists\(\)\s*==\s*false"
        ),
        "settings": re.compile(
            rf"new\s+File\(\s*{re.escape(directory_parameter)}\s*,\s*"
            r"(['\"])settings\.gradle\1\s*\)\.exists\(\)"
        ),
        "known": re.compile(
            rf"findProject\(\s*{re.escape(directory_parameter)}\s*\)\s*!=\s*null"
        ),
    }
    found_guards: set[str] = set()
    skipped_names: set[str] = set()
    index = 0
    project_variable: str | None = None
    interpolation = re.escape(
        '"${' + path_parameter + '}:${' + directory_parameter + '.name}"'
    )
    assignment = re.compile(
        rf"(?:final\s+)?String\s+(?P<project>[A-Za-z_]\w*)\s*=\s*"
        rf"{interpolation}\s*;?"
    )
    while index < len(lines):
        match = assignment.fullmatch(lines[index])
        if match is not None:
            project_variable = match.group("project")
            index += 1
            break
        guard = _gradle_return_guard(lines, index)
        if guard is None:
            return None
        condition, index = guard
        matched = False
        for key, pattern in required_guards.items():
            if pattern.fullmatch(condition):
                if key in found_guards:
                    return None
                found_guards.add(key)
                matched = True
                break
        if matched:
            continue
        skipped_name = re.fullmatch(
            rf"{re.escape(directory_parameter)}\.name\s*==\s*"
            r"(?P<quote>['\"])(?P<value>[^'\"\\$\r\n]+)(?P=quote)",
            condition,
        )
        if skipped_name is None:
            return None
        skipped_names.add(skipped_name.group("value"))

    if project_variable is None or found_guards != set(required_guards):
        return None

    skipped_paths: set[str] = set()
    while index < len(lines):
        include = re.fullmatch(
            rf"include\s*(?:\(\s*)?{re.escape(project_variable)}\s*\)?\s*;?",
            lines[index],
        )
        if include is not None:
            index += 1
            break
        guard = _gradle_return_guard(lines, index)
        if guard is None:
            return None
        condition, index = guard
        skipped_path = re.fullmatch(
            rf"{re.escape(project_variable)}\.equals\(\s*"
            r"(?P<quote>['\"])(?P<value>[^'\"\\$\r\n]+)(?P=quote)\s*\)",
            condition,
        )
        if skipped_path is None:
            return None
        value = skipped_path.group("value")
        if not value.startswith(":") or not _gradle_project_parts(value):
            return None
        skipped_paths.add(":" + ":".join(_gradle_project_parts(value)))
    else:
        return None

    remapped_path_prefix: str | None = None
    if index < len(lines) and re.match(r"^if\b", lines[index]):
        mapping = _gradle_single_statement_if(lines, index)
        if mapping is None:
            return None
        condition, statement, index = mapping
        condition_match = re.fullmatch(
            rf"{re.escape(path_parameter)}\.isEmpty\(\)\s*\|\|\s*"
            rf"{re.escape(path_parameter)}\.startsWith\(\s*"
            r"(?P<quote>['\"])(?P<value>[^'\"\\$\r\n]+)(?P=quote)\s*\)",
            condition,
        )
        if condition_match is None:
            return None
        remapped_value = condition_match.group("value")
        remapped_parts = _gradle_project_parts(remapped_value)
        if not remapped_value.startswith(":") or not remapped_parts:
            return None
        remapped_path_prefix = ":" + ":".join(remapped_parts)
        if re.fullmatch(
            rf"project\(\s*{re.escape(project_variable)}\s*\)\.projectDir\s*=\s*"
            rf"{re.escape(directory_parameter)}\s*;?",
            statement,
        ) is None:
            return None

    if index >= len(lines):
        return None
    loop = re.fullmatch(
        rf"for\s*\(\s*File\s+(?P<child>[A-Za-z_]\w*)\s*:\s*"
        rf"{re.escape(directory_parameter)}\.listFiles\(\)\s*\)\s*\{{",
        lines[index],
    )
    if loop is None or index + 2 >= len(lines):
        return None
    child = loop.group("child")
    if re.fullmatch(
        rf"{re.escape(name)}\(\s*{re.escape(project_variable)}\s*,\s*"
        rf"{re.escape(child)}\s*\)\s*;?",
        lines[index + 1],
    ) is None:
        return None
    if re.fullmatch(r"}\s*;?", lines[index + 2]) is None:
        return None
    if index + 3 != len(lines):
        return None
    return _RecursiveGradleHelper(
        name,
        tuple(sorted(skipped_names)),
        tuple(sorted(skipped_paths)),
        remapped_path_prefix,
    )


def _gradle_return_guard(
    lines: tuple[str, ...],
    index: int,
) -> tuple[str, int] | None:
    single = re.fullmatch(r"if\s*\((?P<condition>.*)\)\s*return\s*;?", lines[index])
    if single is not None:
        return single.group("condition").strip(), index + 1
    block = re.fullmatch(r"if\s*\((?P<condition>.*)\)\s*\{", lines[index])
    if block is None or index + 2 >= len(lines):
        return None
    if re.fullmatch(r"return\s*;?", lines[index + 1]) is None:
        return None
    if re.fullmatch(r"}\s*;?", lines[index + 2]) is None:
        return None
    return block.group("condition").strip(), index + 3


def _gradle_single_statement_if(
    lines: tuple[str, ...],
    index: int,
) -> tuple[str, str, int] | None:
    block = re.fullmatch(r"if\s*\((?P<condition>.*)\)\s*\{", lines[index])
    if block is None or index + 2 >= len(lines):
        return None
    if re.fullmatch(r"}\s*;?", lines[index + 2]) is None:
        return None
    return block.group("condition").strip(), lines[index + 1], index + 3


def _literal_recursive_gradle_invocation(
    line: str,
    helper: _RecursiveGradleHelper,
    root: Path,
) -> tuple[tuple[str, ...], Path] | None:
    match = re.fullmatch(
        rf"\s*{re.escape(helper.name)}\s*\(\s*"
        r"(?P<prefix_quote>['\"])(?P<prefix>[^'\"\\$\r\n]*)(?P=prefix_quote)\s*,\s*"
        r"new\s+File\(\s*rootProject\.projectDir\s*,\s*"
        r"(?P<root_quote>['\"])(?P<root>[^'\"\\$\r\n]+)(?P=root_quote)\s*\)\s*"
        r"\)\s*;?\s*",
        line,
    )
    if match is None:
        return None
    prefix_value = match.group("prefix")
    prefix = _gradle_project_parts(prefix_value) if prefix_value else ()
    if prefix_value and not prefix:
        return None
    relative = match.group("root")
    parts = tuple(relative.split("/"))
    if (
        not parts
        or relative.startswith("/")
        or any(
            not part
            or part in {".", ".."}
            or ":" in part
            or "|" in part
            or any(ord(character) < 32 or ord(character) == 127 for character in part)
            for part in parts
        )
    ):
        return None
    return prefix, root.joinpath(*parts)


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
