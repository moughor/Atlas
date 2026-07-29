"""Parse Java package, import and top-level type metadata."""

from __future__ import annotations

import re
from pathlib import Path

from moughorai.java_analysis.models import (
    JavaAnnotation,
    JavaImport,
    JavaSourceFile,
    JavaSourceSet,
    JavaTypeDeclaration,
    JavaTypeKind,
)


class JavaSourceParseError(ValueError):
    """Raised when Java source metadata cannot be read safely."""


_PACKAGE_RE = re.compile(
    r"\bpackage\s+([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*;"
)
_IMPORT_RE = re.compile(
    r"\bimport\s+(static\s+)?"
    r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$*][\w$*]*)*)\s*;"
)
_TYPE_RE = re.compile(
    r"(?P<annotations>(?:@[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*"
    r"(?:\s*\([^;{}]*\))?\s*)*)"
    r"(?P<modifiers>(?:(?:public|protected|private|abstract|final|"
    r"static|sealed|non-sealed|strictfp)\s+)*)"
    r"(?P<kind>@interface|class|interface|enum|record)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
_ANNOTATION_RE = re.compile(
    r"@([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)"
)
_MODIFIER_RE = re.compile(
    r"\b(public|protected|private|abstract|final|static|sealed|"
    r"non-sealed|strictfp)\b"
)


class JavaSourceParser:
    """Parse structural metadata without requiring a full Java AST."""

    def parse(self, path: Path) -> JavaSourceFile:
        source_path = Path(path)
        if not source_path.exists():
            raise JavaSourceParseError(
                f"Java source file does not exist: {source_path}"
            )
        if not source_path.is_file():
            raise JavaSourceParseError(
                f"Java source path is not a file: {source_path}"
            )
        try:
            text = source_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise JavaSourceParseError(
                f"Unable to read Java source: {source_path}"
            ) from exc

        sanitized = self._sanitize(text)
        package_match = _PACKAGE_RE.search(sanitized)

        return JavaSourceFile(
            path=source_path,
            package_name=(
                package_match.group(1) if package_match else None
            ),
            imports=self._parse_imports(sanitized),
            types=self._parse_top_level_types(sanitized),
            source_set=self.classify_source_set(source_path),
        )

    def parse_many(
        self,
        paths: tuple[Path, ...] | list[Path],
    ) -> tuple[JavaSourceFile, ...]:
        return tuple(
            self.parse(path)
            for path in sorted(
                map(Path, paths),
                key=lambda item: item.as_posix().casefold(),
            )
        )

    @staticmethod
    def classify_source_set(path: Path) -> JavaSourceSet:
        joined = "/".join(
            part.casefold() for part in Path(path).parts
        )
        framed = f"/{joined}/"
        if "generated-sources" in joined or "generated-test-sources" in joined:
            return JavaSourceSet.GENERATED
        if "/src/test/java/" in framed:
            return JavaSourceSet.TEST
        if "/src/main/java/" in framed:
            return JavaSourceSet.MAIN
        return JavaSourceSet.UNKNOWN

    @staticmethod
    def _parse_imports(text: str) -> tuple[JavaImport, ...]:
        values = {
            JavaImport(
                qualified_name=match.group(2),
                is_static=bool(match.group(1)),
                is_wildcard=match.group(2).endswith(".*"),
            )
            for match in _IMPORT_RE.finditer(text)
        }
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    item.qualified_name.casefold(),
                    item.is_static,
                ),
            )
        )

    def _parse_top_level_types(
        self,
        text: str,
    ) -> tuple[JavaTypeDeclaration, ...]:
        depths = self._brace_depths(text)
        declarations: list[JavaTypeDeclaration] = []
        kinds = {
            "class": JavaTypeKind.CLASS,
            "interface": JavaTypeKind.INTERFACE,
            "enum": JavaTypeKind.ENUM,
            "record": JavaTypeKind.RECORD,
            "@interface": JavaTypeKind.ANNOTATION,
        }

        for match in _TYPE_RE.finditer(text):
            if depths[match.start()] != 0:
                continue
            declarations.append(
                JavaTypeDeclaration(
                    name=match.group("name"),
                    kind=kinds[match.group("kind")],
                    annotations=tuple(
                        JavaAnnotation(name)
                        for name in _ANNOTATION_RE.findall(
                            match.group("annotations") or ""
                        )
                    ),
                    modifiers=tuple(
                        _MODIFIER_RE.findall(
                            match.group("modifiers") or ""
                        )
                    ),
                )
            )
        return tuple(declarations)

    @staticmethod
    def _brace_depths(text: str) -> list[int]:
        depths = [0] * (len(text) + 1)
        depth = 0
        for index, character in enumerate(text):
            depths[index] = depth
            if character == "{":
                depth += 1
            elif character == "}":
                depth = max(0, depth - 1)
        depths[len(text)] = depth
        return depths

    @staticmethod
    def _sanitize(text: str) -> str:
        """Blank comments and literals while preserving offsets."""

        output = list(text)
        index = 0
        length = len(text)

        while index < length:
            if text.startswith("//", index):
                end = text.find("\n", index + 2)
                end = length if end == -1 else end
                for position in range(index, end):
                    output[position] = " "
                index = end
                continue

            if text.startswith("/*", index):
                end = text.find("*/", index + 2)
                stop = length if end == -1 else end + 2
                for position in range(index, stop):
                    if output[position] not in "\r\n":
                        output[position] = " "
                index = stop
                continue

            if text.startswith('"""', index):
                end = text.find('"""', index + 3)
                stop = length if end == -1 else end + 3
                for position in range(index, stop):
                    if output[position] not in "\r\n":
                        output[position] = " "
                index = stop
                continue

            if text[index] in {'"', "'"}:
                quote = text[index]
                output[index] = " "
                index += 1
                escaped = False
                while index < length:
                    character = text[index]
                    if character not in "\r\n":
                        output[index] = " "
                    if escaped:
                        escaped = False
                    elif character == "\\":
                        escaped = True
                    elif character == quote:
                        index += 1
                        break
                    index += 1
                continue

            index += 1

        return "".join(output)
