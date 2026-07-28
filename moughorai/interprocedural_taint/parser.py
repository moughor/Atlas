from __future__ import annotations

import re
from dataclasses import dataclass

from moughorai.java_security import JavaSourceUnit
from moughorai.security_analysis import SourceLocation

from .models import JavaMethod, JavaMethodId, JavaType

_TYPE = re.compile(r"\b(?:class|interface|record|enum)\s+(?P<name>[A-Za-z_$][\w$]*)")
_PACKAGE = re.compile(r"\bpackage\s+([\w.]+)\s*;")
_METHOD = re.compile(
    r"(?P<annotations>(?:@[\w.$]+(?:\([^)]*\))?\s*)*)"
    r"(?:(?:public|protected|private|static|final|synchronized|native|abstract|default)\s+)*"
    r"(?P<return>[\w.$<>?\[\],]+)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*\((?P<params>[^)]*)\)\s*"
    r"(?:throws\s+[^{]+)?\{",
    re.MULTILINE,
)
_FIELD = re.compile(
    r"(?m)^\s*(?:(?:public|protected|private|static|final|volatile|transient)\s+)*"
    r"[\w.$<>?\[\],]+\s+([A-Za-z_$][\w$]*)\s*(?:=[^;]*)?;"
)


@dataclass(slots=True)
class JavaProgramParser:
    def parse_units(self, units: tuple[JavaSourceUnit, ...] | list[JavaSourceUnit]) -> tuple[JavaType, ...]:
        types: list[JavaType] = []
        for unit in sorted(units, key=lambda item: item.path):
            parsed = self.parse_unit(unit)
            if parsed is not None:
                types.append(parsed)
        return tuple(types)

    def parse_unit(self, unit: JavaSourceUnit) -> JavaType | None:
        source = self._strip_comments(unit.source)
        type_match = _TYPE.search(source)
        if not type_match:
            return None
        simple = type_match.group("name")
        package_match = _PACKAGE.search(source)
        package = package_match.group(1) if package_match else ""
        qualified = f"{package}.{simple}" if package else simple
        methods: list[JavaMethod] = []
        method_ranges: list[tuple[int, int]] = []
        for match in _METHOD.finditer(source):
            if match.group("name") in {"if", "for", "while", "switch", "catch", "new"}:
                continue
            opening = match.end() - 1
            closing = self._matching_brace(source, opening)
            if closing is None:
                continue
            params = self._parameter_names(match.group("params"))
            line = source.count("\n", 0, match.start()) + 1
            end_line = source.count("\n", 0, closing) + 1
            annotations = tuple(re.findall(r"@([\w.$]+)", match.group("annotations") or ""))
            methods.append(JavaMethod(
                JavaMethodId(qualified, match.group("name"), len(params)),
                params,
                source[opening + 1:closing],
                SourceLocation(unit.path, line),
                end_line,
                match.group("return"),
                annotations,
            ))
            method_ranges.append((match.start(), closing + 1))
        masked = list(source)
        for start, end in method_ranges:
            masked[start:end] = " " * (end - start)
        field_source = "".join(masked)
        type_open = field_source.find("{", type_match.end())
        field_source = field_source[type_open + 1:] if type_open >= 0 else field_source
        fields = tuple(sorted(set(_FIELD.findall(field_source))))
        return JavaType(qualified, simple, unit.path, tuple(methods), fields)

    def _parameter_names(self, text: str) -> tuple[str, ...]:
        if not text.strip():
            return ()
        names: list[str] = []
        for raw in self._split_top_level(text, ","):
            clean = re.sub(r"@[\w.$]+(?:\([^)]*\))?", "", raw).strip()
            clean = re.sub(r"\bfinal\b", "", clean).strip()
            parts = clean.split()
            if parts:
                names.append(parts[-1].replace("...", "").strip())
        return tuple(names)

    def _matching_brace(self, source: str, opening: int) -> int | None:
        depth = 0
        quote = ""
        escape = False
        for index in range(opening, len(source)):
            char = source[index]
            if quote:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == quote:
                    quote = ""
                continue
            if char in {'"', "'"}:
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
        return None

    def _split_top_level(self, text: str, delimiter: str) -> tuple[str, ...]:
        out: list[str] = []
        start = 0
        depths = [0, 0, 0]
        quote = ""
        escape = False
        for index, char in enumerate(text):
            if quote:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == quote:
                    quote = ""
                continue
            if char in {'"', "'"}:
                quote = char
            elif char == "(": depths[0] += 1
            elif char == ")": depths[0] -= 1
            elif char == "[": depths[1] += 1
            elif char == "]": depths[1] -= 1
            elif char == "{": depths[2] += 1
            elif char == "}": depths[2] -= 1
            elif char == delimiter and depths == [0, 0, 0]:
                out.append(text[start:index].strip()); start = index + 1
        out.append(text[start:].strip())
        return tuple(out)

    def _strip_comments(self, source: str) -> str:
        source = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), source, flags=re.DOTALL)
        return re.sub(r"//[^\n]*", "", source)
