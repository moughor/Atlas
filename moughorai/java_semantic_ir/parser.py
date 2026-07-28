from __future__ import annotations

import re

from .models import (
    JavaAssignment,
    JavaCall,
    JavaControlStatement,
    JavaLocalVariable,
    JavaMethodBody,
    JavaObjectCreation,
    JavaReturn,
)

_IDENTIFIER = r"[A-Za-z_$][A-Za-z0-9_$]*"
_TYPE = rf"{_IDENTIFIER}(?:\.{_IDENTIFIER})*(?:\s*<[^;=(){{}}]+>)?(?:\[\])*"

_LOCAL_RE = re.compile(
    rf"^(?P<type>{_TYPE})\s+"
    rf"(?P<name>{_IDENTIFIER})"
    rf"(?:\s*=\s*(?P<init>.+))?$"
)
_ASSIGNMENT_RE = re.compile(
    rf"^(?P<target>{_IDENTIFIER}(?:\.{_IDENTIFIER})*)\s*"
    rf"(?<![=!<>])=(?!=)\s*(?P<expr>.+)$"
)
_NEW_RE = re.compile(rf"\bnew\s+(?P<type>{_TYPE})\s*\((?P<args>[^()]*)\)")
_CALL_RE = re.compile(
    rf"(?P<expr>"
    rf"(?:(?P<qualifier>{_IDENTIFIER}(?:\.{_IDENTIFIER})*)\s*\.)?"
    rf"(?P<method>{_IDENTIFIER})\s*\((?P<args>[^()]*)\)"
    rf")"
)
_RETURN_RE = re.compile(r"^return(?:\s+(?P<expr>.+))?$")
_CONTROL_RE = re.compile(
    r"\b(?P<kind>if|for|while|switch|catch|synchronized)\s*"
    r"\((?P<condition>[^()]*)\)"
    r"|\b(?P<simple>else|do|try|finally)\b"
)

_CALL_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "synchronized",
    "return", "throw", "new", "super", "this",
}
_NON_TYPE_PREFIXES = {
    "return", "throw", "if", "for", "while", "switch", "catch",
    "else", "do", "try", "finally", "synchronized",
}


class JavaMethodBodyParser:
    def parse(self, source: str) -> JavaMethodBody:
        if not isinstance(source, str):
            raise TypeError("source must be a string")

        cleaned = self._mask_comments_and_literals(source)
        statements = self._split_statements(cleaned)

        locals_: list[JavaLocalVariable] = []
        assignments: list[JavaAssignment] = []
        returns: list[JavaReturn] = []

        for statement in statements:
            normalized = statement.strip().strip("{}").strip()
            if not normalized:
                continue

            return_match = _RETURN_RE.match(normalized)
            if return_match:
                returns.append(
                    JavaReturn(self._clean_optional(return_match.group("expr")))
                )
                continue

            local_match = _LOCAL_RE.match(normalized)
            if (
                local_match
                and local_match.group("type").split(".", 1)[0]
                not in _NON_TYPE_PREFIXES
            ):
                locals_.append(
                    JavaLocalVariable(
                        type_name=self._normalize(local_match.group("type")),
                        name=local_match.group("name"),
                        initializer=self._clean_optional(local_match.group("init")),
                    )
                )
                continue

            assignment_match = _ASSIGNMENT_RE.match(normalized)
            if assignment_match:
                assignments.append(
                    JavaAssignment(
                        target=assignment_match.group("target"),
                        expression=assignment_match.group("expr").strip(),
                    )
                )

        creations = tuple(
            JavaObjectCreation(
                type_name=self._normalize(match.group("type")),
                arguments=self._split_arguments(match.group("args")),
                expression=match.group(0).strip(),
            )
            for match in _NEW_RE.finditer(cleaned)
        )

        calls = []
        for match in _CALL_RE.finditer(cleaned):
            method = match.group("method")
            prefix = cleaned[max(0, match.start() - 5):match.start()]
            if method in _CALL_KEYWORDS or prefix.rstrip().endswith("new"):
                continue
            calls.append(
                JavaCall(
                    qualifier=match.group("qualifier"),
                    method_name=method,
                    arguments=self._split_arguments(match.group("args")),
                    expression=match.group("expr").strip(),
                )
            )

        controls = tuple(
            JavaControlStatement(
                kind=match.group("kind") or match.group("simple"),
                condition=self._clean_optional(match.group("condition")),
            )
            for match in _CONTROL_RE.finditer(cleaned)
        )

        return JavaMethodBody(
            source=source,
            local_variables=tuple(locals_),
            assignments=tuple(assignments),
            calls=tuple(calls),
            object_creations=creations,
            returns=tuple(returns),
            control_statements=controls,
        )

    @staticmethod
    def _split_statements(source: str) -> tuple[str, ...]:
        statements: list[str] = []
        current: list[str] = []
        depth = 0
        for char in source:
            if char in "([{":
                depth += 1
            elif char in ")]}":
                depth = max(0, depth - 1)
            if char == ";" and depth <= 1:
                statements.append("".join(current))
                current = []
            else:
                current.append(char)
        tail = "".join(current).strip()
        if tail:
            statements.append(tail)
        return tuple(statements)

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _clean_optional(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @staticmethod
    def _split_arguments(value: str) -> tuple[str, ...]:
        value = value.strip()
        if not value:
            return ()
        parts, current, depth = [], [], 0
        for char in value:
            if char in "(<[{":
                depth += 1
            elif char in ")>]}":
                depth = max(0, depth - 1)
            if char == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(char)
        tail = "".join(current).strip()
        if tail:
            parts.append(tail)
        return tuple(parts)

    @staticmethod
    def _mask_comments_and_literals(source: str) -> str:
        result = list(source)
        i, length = 0, len(result)
        while i < length:
            if i + 1 < length and result[i] == "/" and result[i + 1] == "/":
                start = i
                i += 2
                while i < length and result[i] != "\n":
                    i += 1
                for pos in range(start, i):
                    result[pos] = " "
                continue
            if i + 1 < length and result[i] == "/" and result[i + 1] == "*":
                start = i
                i += 2
                while i + 1 < length and not (
                    result[i] == "*" and result[i + 1] == "/"
                ):
                    i += 1
                i = min(length, i + 2)
                for pos in range(start, i):
                    if result[pos] != "\n":
                        result[pos] = " "
                continue
            if result[i] in {'"', "'"}:
                quote, start = result[i], i
                i += 1
                escaped = False
                while i < length:
                    char = result[i]
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == quote:
                        i += 1
                        break
                    i += 1
                for pos in range(start, i):
                    if result[pos] != "\n":
                        result[pos] = " "
                continue
            i += 1
        return "".join(result)
