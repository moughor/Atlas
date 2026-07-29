from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import (
    IRAssignment,
    IRCall,
    IRFunction,
    IRModule,
    IRParameter,
    IRType,
    Language,
    SourceSpan,
)

_EXTENSIONS = {".java": Language.JAVA, ".kt": Language.KOTLIN, ".kts": Language.KOTLIN, ".scala": Language.SCALA, ".groovy": Language.GROOVY}
_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "new", "throw", "when", "match", "super", "this", "assert", "synchronized"}


def language_for_path(path: str) -> Language:
    suffix = Path(path).suffix.lower()
    if suffix not in _EXTENSIONS:
        raise ValueError(f"unsupported source language: {path}")
    return _EXTENSIONS[suffix]


def _line_of(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _split_args(text: str) -> tuple[str, ...]:
    if not text.strip():
        return ()
    out: list[str] = []
    depth = 0
    quote = ""
    start = 0
    for i, ch in enumerate(text):
        if quote:
            if ch == quote and (i == 0 or text[i - 1] != "\\"):
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            out.append(text[start:i].strip())
            start = i + 1
    out.append(text[start:].strip())
    return tuple(x for x in out if x)


def _annotations(prefix: str) -> tuple[str, ...]:
    return tuple(sorted(set(re.findall(r"@([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)", prefix))))


def _matching_brace(source: str, opening: int) -> int:
    depth = 0
    quote = ""
    i = opening
    while i < len(source):
        ch = source[i]
        if quote:
            if ch == quote and source[i - 1] != "\\":
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif source.startswith("//", i):
            nl = source.find("\n", i)
            i = len(source) if nl < 0 else nl
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            i = len(source) if end < 0 else end + 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(source) - 1


def _calls(body: str, path: str, base_line: int) -> tuple[IRCall, ...]:
    result: list[IRCall] = []
    pattern = re.compile(r"(?:(?P<recv>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\.)?(?P<name>[A-Za-z_]\w*)\s*\((?P<args>[^(){};]*)\)")
    for match in pattern.finditer(body):
        name = match.group("name")
        if name in _KEYWORDS:
            continue
        args = _split_args(match.group("args"))
        line = base_line + body.count("\n", 0, match.start())
        result.append(IRCall(name, match.group("recv") or "", args, SourceSpan(path, line, 1)))
    return tuple(sorted(result, key=lambda c: (c.span.line if c.span else 0, c.name, c.receiver, c.arguments)))


def _assignments(body: str, path: str, base_line: int) -> tuple[IRAssignment, ...]:
    result = []
    for match in re.finditer(r"(?m)(?:\b(?:val|var|def|final|String|int|long|boolean|Object)\s+)?([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*=\s*([^;\n]+)", body):
        if match.group(2).lstrip().startswith("="):
            continue
        line = base_line + body.count("\n", 0, match.start())
        result.append(IRAssignment(match.group(1), match.group(2).strip(), SourceSpan(path, line, 1)))
    return tuple(result)


def _returns(body: str) -> tuple[str, ...]:
    values = [m.group(1).strip() for m in re.finditer(r"\breturn\s+([^;\n}]+)", body)]
    return tuple(values)


def _params(text: str, language: Language, path: str, line: int) -> tuple[IRParameter, ...]:
    result = []
    for raw in _split_args(text):
        annotations = _annotations(raw)
        clean = re.sub(r"@[A-Za-z_]\w*(?:\([^)]*\))?\s*", "", raw).strip()
        clean = re.sub(r"\b(?:final|val|var|def|implicit|crossinline|noinline)\b\s*", "", clean).strip()
        name = ""
        typ = ""
        if language in (Language.KOTLIN, Language.SCALA) and ":" in clean:
            name, typ = (part.strip() for part in clean.split(":", 1))
            typ = typ.split("=")[0].strip()
        else:
            bits = clean.split()
            if len(bits) >= 2:
                name, typ = bits[-1].split("=")[0], " ".join(bits[:-1])
            elif bits:
                name = bits[0].split("=")[0]
        name = name.strip("* ")
        if name:
            result.append(IRParameter(name, typ, annotations, SourceSpan(path, line, 1)))
    return tuple(result)


@dataclass(frozen=True)
class _FunctionMatch:
    name: str
    params: str
    return_type: str
    start: int
    body_start: int
    body_end: int
    prefix: str
    modifiers: tuple[str, ...]


def _function_matches(source: str, language: Language) -> list[_FunctionMatch]:
    matches: list[_FunctionMatch] = []
    if language is Language.JAVA:
        pattern = re.compile(r"(?P<prefix>(?:@[\w.]+(?:\([^)]*\))?\s*)*)(?P<mods>(?:(?:public|private|protected|static|final|abstract|synchronized|native|default)\s+)*)?(?P<ret>[\w.$<>?,\[\]]+)\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^)]*)\)\s*\{", re.M)
    elif language is Language.KOTLIN:
        pattern = re.compile(r"(?P<prefix>(?:@[\w.]+(?:\([^)]*\))?\s*)*)(?P<mods>(?:(?:public|private|protected|internal|open|override|suspend|inline|tailrec|operator|infix)\s+)*)fun\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^)]*)\)\s*(?::\s*(?P<ret>[\w.?<>]+))?\s*(?:=\s*([^\n;]+)|\{)", re.M)
    else:
        pattern = re.compile(r"(?P<prefix>(?:@[\w.]+(?:\([^)]*\))?\s*)*)(?P<mods>(?:(?:public|private|protected|static|final|override|implicit|abstract|synchronized|def)\s+)*)?(?:def\s+)?(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^)]*)\)\s*(?::\s*(?P<ret>[\w.?<>\[\]]+))?\s*(?:=\s*)?\{", re.M)
    for match in pattern.finditer(source):
        name = match.group("name")
        if name in _KEYWORDS or name in {"class", "interface", "object", "trait", "enum"}:
            continue
        opening = source.find("{", match.start(), match.end())
        if opening < 0:
            # Kotlin expression body
            end = source.find("\n", match.end())
            end = len(source) if end < 0 else end
            matches.append(_FunctionMatch(name, match.group("params"), match.groupdict().get("ret") or "", match.start(), match.end(), end, match.group("prefix") or "", tuple((match.groupdict().get("mods") or "").split())))
        else:
            matches.append(_FunctionMatch(name, match.group("params"), match.groupdict().get("ret") or "", match.start(), opening + 1, _matching_brace(source, opening), match.group("prefix") or "", tuple((match.groupdict().get("mods") or "").split())))
    return matches


def parse_source(path: str, source: str, language: Language | None = None) -> IRModule:
    language = language or language_for_path(path)
    package_match = re.search(r"(?m)^\s*package\s+([\w.]+)", source)
    package = package_match.group(1) if package_match else ""
    imports = tuple(sorted(set(re.findall(r"(?m)^\s*import\s+([\w.*{}]+)", source))))
    type_pattern = re.compile(r"(?P<prefix>(?:@[\w.]+(?:\([^)]*\))?\s*)*)(?P<kind>class|interface|enum|record|object|trait)\s+(?P<name>[A-Za-z_]\w*)(?P<tail>[^\{\n]*)\{", re.M)
    raw_types = []
    for match in type_pattern.finditer(source):
        end = _matching_brace(source, source.find("{", match.start(), match.end()))
        raw_types.append((match, end))
    functions = _function_matches(source, language)
    ir_types: list[IRType] = []
    used: set[int] = set()
    for type_match, type_end in raw_types:
        simple = type_match.group("name")
        qname = f"{package}.{simple}" if package else simple
        member_functions = []
        for idx, fm in enumerate(functions):
            if type_match.start() < fm.start < type_end:
                used.add(idx)
                line = _line_of(source, fm.start)
                body = source[fm.body_start:fm.body_end]
                member_functions.append(IRFunction(qname, fm.name, _params(fm.params, language, path, line), fm.return_type, body, SourceSpan(path, line, 1, _line_of(source, fm.body_end)), _annotations(fm.prefix), _calls(body, path, _line_of(source, fm.body_start)), _assignments(body, path, _line_of(source, fm.body_start)), _returns(body), fm.modifiers))
        tail = type_match.group("tail") or ""
        supers = tuple(x.strip() for x in re.split(r"\b(?:extends|implements|with)\b|[:,]", tail) if x.strip() and not x.strip().startswith("(") )
        ir_types.append(IRType(qname, simple, type_match.group("kind"), SourceSpan(path, _line_of(source, type_match.start()), 1, _line_of(source, type_end)), tuple(sorted(member_functions, key=lambda f: f.qualified_name)), _annotations(type_match.group("prefix") or ""), supers))
    top = []
    owner = package or Path(path).stem
    for idx, fm in enumerate(functions):
        if idx in used:
            continue
        line = _line_of(source, fm.start)
        body = source[fm.body_start:fm.body_end]
        top.append(IRFunction(owner, fm.name, _params(fm.params, language, path, line), fm.return_type, body, SourceSpan(path, line, 1, _line_of(source, fm.body_end)), _annotations(fm.prefix), _calls(body, path, _line_of(source, fm.body_start)), _assignments(body, path, _line_of(source, fm.body_start)), _returns(body), fm.modifiers))
    diagnostics = () if raw_types or top else (f"no declarations found in {path}",)
    return IRModule(path, language, package, imports, tuple(sorted(ir_types, key=lambda t: t.qualified_name)), tuple(sorted(top, key=lambda f: f.qualified_name)), diagnostics)
