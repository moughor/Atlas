from __future__ import annotations

import re
from dataclasses import dataclass

from moughorai.security_analysis import Assignment, Expression, Invocation, SecurityProgram, SourceLocation, ValueKind

from .models import JavaParseWarning, JavaSecurityParseResult, JavaSourceUnit


_DECLARATION = re.compile(
    r"^(?:final\s+)?(?:[\w.$<>?\[\],]+\s+)+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?P<expr>.+)$",
    re.DOTALL,
)
_ASSIGNMENT = re.compile(r"^(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?P<expr>.+)$", re.DOTALL)
_CALL = re.compile(r"^(?P<name>[A-Za-z_$][\w$]*(?:\s*\.\s*[A-Za-z_$][\w$]*|\s*\([^()]*\))*)\s*\((?P<args>.*)\)$")
_STRING = re.compile(r'^"(?P<value>(?:\\.|[^"\\])*)"$')
_CHAR = re.compile(r"^'(?P<value>(?:\\.|[^'\\])*)'$")
_NUMBER = re.compile(r"^-?(?:\d+(?:\.\d+)?|\.\d+)(?:[fFdDlL])?$")
_ANNOTATION = re.compile(r"^@(?P<name>[\w.$]+)")


@dataclass(slots=True)
class JavaSecurityParser:
    """Small deterministic Java statement adapter for Atlas security analysis.

    It intentionally targets security-relevant expressions instead of attempting
    to replace a complete Java compiler frontend.
    """

    warn_on_unsupported: bool = False

    def parse(self, unit: JavaSourceUnit) -> JavaSecurityParseResult:
        assignments: list[Assignment] = []
        invocations: list[Invocation] = []
        annotations: list[str] = []
        warnings: list[JavaParseWarning] = []

        for line_no, statement in self._statements(unit.source):
            text = statement.strip()
            if not text:
                continue
            annotation = _ANNOTATION.match(text)
            if annotation:
                annotations.append(annotation.group("name"))
                continue
            if self._is_structure(text):
                continue

            clean = text[:-1].strip() if text.endswith(";") else text
            location = SourceLocation(unit.path, line_no)
            match = _DECLARATION.match(clean) or _ASSIGNMENT.match(clean)
            if match:
                expression = self._expression(match.group("expr"), location)
                assignments.append(Assignment(match.group("name"), expression, location))
                continue

            expression = self._expression(clean, location)
            if expression.kind.value == "call":
                invocations.append(
                    Invocation(str(expression.value), expression.parts, location)
                )
            elif self.warn_on_unsupported and self._looks_security_relevant(clean):
                warnings.append(JavaParseWarning(unit.path, line_no, f"Unsupported Java statement: {clean}"))

        return JavaSecurityParseResult(
            SecurityProgram(tuple(assignments), tuple(invocations), tuple(annotations)),
            tuple(warnings),
        )

    def _statements(self, source: str) -> tuple[tuple[int, str], ...]:
        source = self._remove_block_comments(source)
        results: list[tuple[int, str]] = []
        buffer: list[str] = []
        start_line = 1
        depth = 0
        in_string = False
        quote = ""
        escape = False

        for line_no, raw in enumerate(source.splitlines(), 1):
            line = self._remove_line_comment(raw)
            if not buffer and line.strip():
                start_line = line_no
            for char in line + "\n":
                buffer.append(char)
                if escape:
                    escape = False
                    continue
                if char == "\\" and in_string:
                    escape = True
                    continue
                if char in {'"', "'"}:
                    if in_string and char == quote:
                        in_string = False
                    elif not in_string:
                        in_string = True
                        quote = char
                    continue
                if in_string:
                    continue
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth = max(0, depth - 1)
                elif char == ";" and depth == 0:
                    results.append((start_line, "".join(buffer).strip()))
                    buffer.clear()
                elif char in "{}" and depth == 0:
                    candidate = "".join(buffer[:-1]).strip()
                    if candidate:
                        results.append((start_line, candidate))
                    buffer.clear()
            if buffer and not "".join(buffer).strip():
                buffer.clear()
        tail = "".join(buffer).strip()
        if tail:
            results.append((start_line, tail))
        return tuple(results)

    def _expression(self, text: str, location: SourceLocation) -> Expression:
        value = self._strip_outer_parentheses(text.strip())
        parts = self._split_top_level(value, "+")
        if len(parts) > 1:
            return Expression.concat(*(self._expression(part, location) for part in parts), location=location)

        if match := _STRING.match(value):
            return Expression.literal(bytes(match.group("value"), "utf-8").decode("unicode_escape"), location)
        if match := _CHAR.match(value):
            return Expression.literal(match.group("value"), location)
        if value == "true":
            return Expression.literal(True, location)
        if value == "false":
            return Expression.literal(False, location)
        if value == "null":
            return Expression.literal(None, location)
        if _NUMBER.match(value):
            try:
                number = float(value.rstrip("fFdDlL")) if "." in value else int(value.rstrip("fFdDlL"))
                return Expression.literal(number, location)
            except ValueError:
                pass

        call = self._parse_call(value)
        if call is not None:
            name, arguments = call
            return Expression.call(
                self._normalize_call_name(name),
                *(self._expression(argument, location) for argument in arguments),
                location=location,
            )

        if re.fullmatch(r"[A-Za-z_$][\w$]*", value):
            return Expression.variable(value, location)
        return Expression(ValueKind.UNKNOWN, value, (), location)

    def _parse_call(self, value: str) -> tuple[str, tuple[str, ...]] | None:
        if not value.endswith(")"):
            return None
        opening = self._matching_open_paren(value)
        if opening is None:
            return None
        prefix = value[:opening].strip()
        if not prefix:
            return None
        arguments = self._split_top_level(value[opening + 1 : -1], ",")
        return prefix, arguments if not (len(arguments) == 1 and not arguments[0].strip()) else ()

    def _normalize_call_name(self, name: str) -> str:
        compact = re.sub(r"\s+", "", name)
        compact = re.sub(r"\.getRuntime\(\)", "", compact)
        compact = re.sub(r"\.newBuilder\(\)", "", compact)
        compact = re.sub(r"\.builder\(\)", "", compact)
        compact = re.sub(r"\([^()]*\)", "", compact)
        if compact == "scanner.nextLine":
            return "Scanner.nextLine"
        if compact.endswith(".parse") and compact.split(".", 1)[0].lower() in {"builder", "documentbuilder"}:
            return "DocumentBuilder.parse"
        return compact

    def _matching_open_paren(self, value: str) -> int | None:
        depth = 0
        in_string = False
        quote = ""
        escape = False
        for index in range(len(value) - 1, -1, -1):
            char = value[index]
            if escape:
                escape = False
                continue
            if char == "\\" and in_string:
                escape = True
                continue
            if char in {'"', "'"}:
                if in_string and char == quote:
                    in_string = False
                elif not in_string:
                    in_string = True
                    quote = char
                continue
            if in_string:
                continue
            if char == ")":
                depth += 1
            elif char == "(":
                depth -= 1
                if depth == 0:
                    return index
        return None

    def _split_top_level(self, text: str, delimiter: str) -> tuple[str, ...]:
        parts: list[str] = []
        start = 0
        paren = bracket = brace = 0
        in_string = False
        quote = ""
        escape = False
        for index, char in enumerate(text):
            if escape:
                escape = False
                continue
            if char == "\\" and in_string:
                escape = True
                continue
            if char in {'"', "'"}:
                if in_string and char == quote:
                    in_string = False
                elif not in_string:
                    in_string = True
                    quote = char
                continue
            if in_string:
                continue
            if char == "(": paren += 1
            elif char == ")": paren -= 1
            elif char == "[": bracket += 1
            elif char == "]": bracket -= 1
            elif char == "{": brace += 1
            elif char == "}": brace -= 1
            elif char == delimiter and paren == bracket == brace == 0:
                parts.append(text[start:index].strip())
                start = index + 1
        parts.append(text[start:].strip())
        return tuple(parts)

    def _strip_outer_parentheses(self, value: str) -> str:
        while value.startswith("(") and value.endswith(")"):
            opening = self._matching_open_paren(value)
            if opening != 0:
                break
            value = value[1:-1].strip()
        return value

    def _remove_block_comments(self, source: str) -> str:
        return re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), source, flags=re.DOTALL)

    def _remove_line_comment(self, line: str) -> str:
        in_string = False
        quote = ""
        escape = False
        for index in range(len(line) - 1):
            char = line[index]
            if escape:
                escape = False
                continue
            if char == "\\" and in_string:
                escape = True
                continue
            if char in {'"', "'"}:
                if in_string and char == quote: in_string = False
                elif not in_string: in_string, quote = True, char
            elif not in_string and line[index:index+2] == "//":
                return line[:index]
        return line

    def _is_structure(self, text: str) -> bool:
        stripped = text.strip()
        return stripped.startswith(("package ", "import ", "class ", "public class ", "private class ", "protected class ", "interface ", "enum ")) or stripped in {"}", "{"}

    def _looks_security_relevant(self, text: str) -> bool:
        tokens = ("exec", "execute", "readObject", "parse", "openConnection", "getParameter", "password", "secret")
        return any(token in text for token in tokens)
