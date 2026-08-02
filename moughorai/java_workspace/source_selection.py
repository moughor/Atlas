"""Evidence-ordered Java source selection for repository analysis."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import re
from urllib.parse import unquote
import xml.etree.ElementTree as ET

from moughorai.gradle_syntax import literal_arguments, strip_comments


_FIXTURE_DATA_DIRECTORIES = frozenset({"testdata", "test-data"})
_MAX_DESCRIPTOR_BYTES = 16 * 1024 * 1024
_MAX_XML_ELEMENTS = 100_000
_GRADLE_SOURCE_DIRECTORY = re.compile(
    r"\b(?P<kind>java|resources)\s*\.\s*srcDirs?\s*"
    r"\((?P<arguments>[^()\r\n]*)\)"
)
_GENERATED_SOURCE_PREFIXES = frozenset({
    ("build", "generated"),
    ("build", "generated-sources"),
    ("build", "generated-test-sources"),
    ("target", "generated-sources"),
    ("target", "generated-test-sources"),
})


def select_compiled_java_sources(
    root: Path,
    paths: tuple[Path, ...],
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Separate compiled candidates from structured resources and fixture data.

    Complete project inventory remains the caller's responsibility. This selector
    removes Java semantic inputs under proven resource roots, plus inputs whose
    first fixture-data boundary is not covered by structured source-root evidence
    or an earlier recognized root.
    """
    project_root = root.resolve()
    classified: list[
        tuple[Path, tuple[str, ...] | None, int | None, bool, bool]
    ] = []
    resolved_directories: dict[Path, Path | None] = {}
    seen_sources: set[Path] = set()
    needs_declared_roots = False
    has_structured_metadata = _has_structured_root_metadata(project_root)
    for original_path in paths:
        project_path = _project_path(
            project_root,
            original_path,
            resolved_directories,
        )
        if project_path is None:
            classified.append((original_path, None, None, False, False))
            continue
        path, relative = project_path
        if path in seen_sources:
            continue
        seen_sources.add(path)
        parts = relative.parts[:-1]
        fixture_index = _fixture_boundary(parts)
        has_earlier_root = (
            fixture_index is not None
            and _has_earlier_root(parts, fixture_index)
        )
        if fixture_index is not None and not has_earlier_root:
            needs_declared_roots = True
        classified.append((
            path,
            parts,
            fixture_index,
            has_earlier_root,
            _has_conventional_resource_root(parts),
        ))

    compiled_prefixes: frozenset[tuple[str, ...]] = frozenset()
    resource_prefixes: frozenset[tuple[str, ...]] = frozenset()
    if needs_declared_roots or has_structured_metadata:
        compiled_roots, resource_roots, content_roots = _declared_java_roots(
            project_root
        )
        compiled_prefixes = frozenset(
            source_root.relative_to(project_root).parts
            for source_root in compiled_roots
        )
        resource_prefixes = frozenset(
            resource_root.relative_to(project_root).parts
            for resource_root in resource_roots
        )
        content_prefixes = frozenset(
            content_root.relative_to(project_root).parts
            for content_root in content_roots
        )
    else:
        content_prefixes = frozenset()
    selected: list[Path] = []
    excluded_data: list[Path] = []
    for (
        path,
        parts,
        fixture_index,
        has_earlier_root,
        conventional_resource,
    ) in classified:
        if parts is None:
            excluded_data.append(path)
            continue
        compiled_depth = _declared_root_depth(parts, compiled_prefixes)
        resource_depth = _declared_root_depth(parts, resource_prefixes)
        if compiled_depth is not None or resource_depth is not None:
            if compiled_depth is not None and (
                resource_depth is None or compiled_depth >= resource_depth
            ):
                selected.append(path)
            else:
                excluded_data.append(path)
            continue
        if _has_declared_root(parts, content_prefixes):
            excluded_data.append(path)
            continue
        if conventional_resource:
            excluded_data.append(path)
            continue
        if fixture_index is None:
            selected.append(path)
            continue
        if has_earlier_root:
            selected.append(path)
            continue
        excluded_data.append(path)
    return tuple(selected), tuple(excluded_data)


def declared_java_source_roots(root: Path) -> tuple[Path, ...]:
    """Return bounded, static source-root evidence attached to *root*."""
    return _declared_java_roots(root.resolve())[0]


def declared_java_resource_roots(root: Path) -> tuple[Path, ...]:
    """Return bounded, static resource-root evidence attached to *root*."""
    return _declared_java_roots(root.resolve())[1]


def _declared_java_roots(
    project_root: Path,
) -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[Path, ...]]:
    gradle_sources, gradle_resources = _literal_gradle_roots(project_root)
    (
        intellij_sources,
        intellij_resources,
        intellij_contents,
    ) = _registered_intellij_roots(project_root)
    return (
        _sorted_roots(project_root, {*gradle_sources, *intellij_sources}),
        _sorted_roots(project_root, {*gradle_resources, *intellij_resources}),
        _sorted_roots(project_root, set(intellij_contents)),
    )


def _sorted_roots(root: Path, roots: set[Path]) -> tuple[Path, ...]:
    return tuple(sorted(
        roots,
        key=lambda path: (
            path.relative_to(root).as_posix().casefold(),
            path.relative_to(root).as_posix(),
        ),
    ))


def _fixture_boundary(parts: tuple[str, ...]) -> int | None:
    for index, part in enumerate(parts):
        if part.casefold() in _FIXTURE_DATA_DIRECTORIES:
            return index
    return None


def _project_path(
    root: Path,
    path: Path,
    resolved_directories: dict[Path, Path | None],
) -> tuple[Path, Path] | None:
    candidate = path if path.is_absolute() else root / path
    resolved_parent = resolved_directories.get(candidate.parent)
    if candidate.parent not in resolved_directories:
        try:
            resolved_parent = candidate.parent.resolve()
            resolved_parent.relative_to(root)
            resolved_directories[candidate.parent] = resolved_parent
        except (OSError, RuntimeError, ValueError):
            resolved_directories[candidate.parent] = None
            return None
    if resolved_parent is None:
        return None
    try:
        resolved = (
            candidate.resolve()
            if candidate.is_symlink()
            else resolved_parent / candidate.name
        )
        relative = resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved, relative


def _has_declared_root(
    parts: tuple[str, ...],
    declared_prefixes: frozenset[tuple[str, ...]],
) -> bool:
    return _declared_root_depth(parts, declared_prefixes) is not None


def _declared_root_depth(
    parts: tuple[str, ...],
    declared_prefixes: frozenset[tuple[str, ...]],
) -> int | None:
    for depth in range(len(parts), -1, -1):
        if parts[:depth] in declared_prefixes:
            return depth
    return None


def _has_earlier_root(parts: tuple[str, ...], fixture_index: int) -> bool:
    prefix = tuple(part.casefold() for part in parts[:fixture_index])
    if prefix[:2] in _GENERATED_SOURCE_PREFIXES:
        return True
    return any(
        prefix[index] == "src"
        and _is_compiled_source_leaf(prefix[index + 2])
        for index in range(max(0, len(prefix) - 2))
    )


def _is_compiled_source_leaf(value: str) -> bool:
    return value in {"java", "kotlin", "groovy", "scala"} or (
        value.startswith("java") and value[4:].isdigit()
    )


def _has_conventional_resource_root(parts: tuple[str, ...]) -> bool:
    normalized = tuple(part.casefold() for part in parts)
    inside_compiled_root = False
    for index in range(max(0, len(normalized) - 2)):
        if normalized[index] != "src":
            continue
        leaf = normalized[index + 2]
        if leaf == "resources":
            return not inside_compiled_root
        if _is_compiled_source_leaf(leaf):
            inside_compiled_root = True
    return False


def _has_structured_root_metadata(root: Path) -> bool:
    candidates = (
        root / "build.gradle",
        root / "build.gradle.kts",
        root / ".idea" / "modules.xml",
    )
    return any(
        _contained_file(root, path) is not None
        for path in candidates
    ) or any(
        _contained_file(root, path) is not None for path in root.glob("*.iml")
    )


def _literal_gradle_roots(
    root: Path,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    source_roots: set[Path] = set()
    resource_roots: set[Path] = set()
    for filename in ("build.gradle", "build.gradle.kts"):
        descriptor = _contained_file(root, root / filename)
        if descriptor is None:
            continue
        source = _read_bounded_text(descriptor)
        if source is None:
            continue
        source = strip_comments(source)
        for match in _matches_outside_strings(source):
            arguments = literal_arguments(match.group("arguments"))
            if not arguments:
                continue
            target = (
                source_roots
                if match.group("kind") == "java"
                else resource_roots
            )
            for argument in arguments:
                candidate = _contained_directory(root, root / argument)
                if candidate is not None:
                    target.add(candidate)
    return tuple(source_roots), tuple(resource_roots)


def _registered_intellij_roots(
    root: Path,
) -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[Path, ...]]:
    descriptors = {
        path.resolve()
        for path in root.glob("*.iml")
        if path.is_file() and _contained_file(root, path) is not None
    }
    modules_descriptor = _contained_file(root, root / ".idea" / "modules.xml")
    modules = (
        _parse_xml(modules_descriptor)
        if modules_descriptor is not None
        else None
    )
    if modules is not None:
        for element in modules.iter("module"):
            reference = element.get("filepath") or element.get("fileurl")
            descriptor = _resolve_reference(
                reference,
                project_root=root,
                module_directory=root,
            )
            if descriptor is not None and descriptor.suffix.casefold() == ".iml":
                contained = _contained_file(root, descriptor)
                if contained is not None:
                    descriptors.add(contained)

    source_roots: set[Path] = set()
    resource_roots: set[Path] = set()
    content_roots: set[Path] = set()
    for descriptor in sorted(
        descriptors,
        key=lambda path: (
            path.relative_to(root).as_posix().casefold(),
            path.relative_to(root).as_posix(),
        ),
    ):
        module = _parse_xml(descriptor)
        if module is None:
            continue
        for content in module.iter("content"):
            content_root = _resolve_reference(
                content.get("url"),
                project_root=root,
                module_directory=descriptor.parent,
            )
            if content_root is None:
                continue
            contained_content = _contained_directory(root, content_root)
            if contained_content is None:
                continue
            attached_root = False
            for element in content.iter("sourceFolder"):
                source_root = _resolve_reference(
                    element.get("url"),
                    project_root=root,
                    module_directory=descriptor.parent,
                )
                if source_root is None:
                    continue
                contained = _contained_directory(root, source_root)
                if contained is None:
                    continue
                target = (
                    resource_roots
                    if "resource" in element.get("type", "").casefold()
                    else source_roots
                )
                target.add(contained)
                attached_root = True
            if attached_root:
                content_roots.add(contained_content)
    return tuple(source_roots), tuple(resource_roots), tuple(content_roots)


def _matches_outside_strings(source: str) -> Iterator[re.Match[str]]:
    cursor = 0
    quote: str | None = None
    slashy = False
    dollar_slashy = False
    for match in _GRADLE_SOURCE_DIRECTORY.finditer(source):
        while cursor < match.start():
            character = source[cursor]
            if dollar_slashy:
                if source[cursor : cursor + 2] == "/$":
                    dollar_slashy = False
                    cursor += 2
                else:
                    cursor += 1
                continue
            if slashy:
                if character == "\\":
                    cursor += 2
                elif character == "/":
                    slashy = False
                    cursor += 1
                else:
                    cursor += 1
                continue
            if quote is not None and character == "\\" and len(quote) == 1:
                cursor += 2
                continue
            if quote is not None and source[cursor : cursor + len(quote)] == quote:
                quote = None
                cursor += 3 if source[cursor : cursor + 3] in {"'''", '"""'} else 1
                continue
            if quote is None and source[cursor : cursor + 2] == "$/":
                dollar_slashy = True
                cursor += 2
                continue
            if quote is None and source[cursor : cursor + 3] in {"'''", '"""'}:
                quote = source[cursor : cursor + 3]
                cursor += 3
                continue
            if quote is None and character in {"'", '"'}:
                quote = character
            elif quote is None and character == "/":
                slashy = True
            cursor += 1
        if quote is None and not slashy and not dollar_slashy:
            yield match


def _read_bounded_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > _MAX_DESCRIPTOR_BYTES:
            return None
        payload = path.read_bytes()
        if len(payload) > _MAX_DESCRIPTOR_BYTES:
            return None
        return payload.decode("utf-8-sig")
    except (OSError, UnicodeError):
        return None


def _parse_xml(path: Path) -> ET.Element | None:
    try:
        if path.stat().st_size > _MAX_DESCRIPTOR_BYTES:
            return None
        payload = path.read_bytes()
        if len(payload) > _MAX_DESCRIPTOR_BYTES or re.search(
            br"<!\s*(?:DOCTYPE|ENTITY)\b",
            payload,
            re.IGNORECASE,
        ):
            return None
        root = ET.fromstring(payload)
        for count, _element in enumerate(root.iter(), start=1):
            if count > _MAX_XML_ELEMENTS:
                return None
        return root
    except (ET.ParseError, OSError, UnicodeError):
        return None


def _resolve_reference(
    value: str | None,
    *,
    project_root: Path,
    module_directory: Path,
) -> Path | None:
    if not value:
        return None
    decoded = unquote(value)
    if decoded.startswith("file://"):
        decoded = decoded[7:]
    decoded = decoded.replace("$PROJECT_DIR$", str(project_root))
    decoded = decoded.replace("$MODULE_DIR$", str(module_directory))
    if "$" in decoded or "://" in decoded:
        return None
    if re.match(r"^/[A-Za-z]:/", decoded):
        decoded = decoded[1:]
    candidate = Path(decoded)
    if not candidate.is_absolute():
        candidate = module_directory / candidate
    try:
        resolved = candidate.resolve()
        resolved.relative_to(project_root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def _contained_file(root: Path, path: Path) -> Path | None:
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def _contained_directory(root: Path, path: Path) -> Path | None:
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved if resolved.is_dir() else None
