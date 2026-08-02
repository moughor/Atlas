"""Recursive-descent parser for Java declarations and member signatures."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from moughorai.java_ast.ast_nodes import (
    Annotation,
    AnnotationArgument,
    AnnotationDeclaration,
    ClassDeclaration,
    CompilationUnit,
    ConstructorDeclaration,
    EnumDeclaration,
    FieldDeclaration,
    ImportDeclaration,
    InterfaceDeclaration,
    MethodDeclaration,
    PackageDeclaration,
    ParameterDeclaration,
    RecordDeclaration,
    TypeDeclaration,
)
from moughorai.java_ast.lexer import JavaLexer
from moughorai.java_ast.token import JavaToken
from moughorai.java_ast.token_type import JavaTokenType


class JavaParseError(ValueError):
    def __init__(self, message: str, token: JavaToken) -> None:
        super().__init__(f"{message} at line {token.line}, column {token.column}")
        self.token = token


_MODIFIERS = frozenset({
    "public", "protected", "private", "abstract", "static", "final",
    "sealed", "non-sealed", "strictfp", "synchronized", "native",
    "transient", "volatile", "default",
})
_PARAMETER_MODIFIERS = frozenset({"final"})
_TYPE_KEYWORDS = frozenset({"class", "interface", "enum", "record"})


class JavaParser:
    """Parse Java compilation units while keeping executable bodies opaque."""

    def parse(self, tokens: Iterable[JavaToken]) -> CompilationUnit:
        self._tokens = tuple(tokens)
        if not self._tokens:
            raise ValueError("tokens must contain an EOF token")
        self._position = 0

        package = self._parse_package()
        imports: list[ImportDeclaration] = []
        while self._is_keyword("import"):
            imports.append(self._parse_import())

        types: list[TypeDeclaration] = []
        while not self._at(JavaTokenType.EOF):
            annotations, annotation_nodes = self._parse_annotations()
            modifiers = self._parse_modifiers()
            if self._at(JavaTokenType.SEMICOLON):
                self._advance()
                continue
            types.append(self._parse_type(annotations, modifiers, annotation_nodes))

        return CompilationUnit(package, tuple(imports), tuple(types))

    def parse_source(self, source: str) -> CompilationUnit:
        return self.parse(JavaLexer().tokenize(source))

    def _parse_package(self) -> PackageDeclaration | None:
        if not self._is_keyword("package"):
            return None
        self._advance()
        name = self._parse_qualified_name()
        self._expect(JavaTokenType.SEMICOLON, "Expected ';' after package")
        return PackageDeclaration(name)

    def _parse_import(self) -> ImportDeclaration:
        self._expect_keyword("import")
        is_static = self._is_keyword("static")
        if is_static:
            self._advance()
        parts = [self._expect_identifier_like("Expected import name").lexeme]
        wildcard = False
        while self._at(JavaTokenType.DOT):
            self._advance()
            if self._at(JavaTokenType.STAR):
                self._advance(); wildcard = True; break
            parts.append(self._expect_identifier_like("Expected import name").lexeme)
        self._expect(JavaTokenType.SEMICOLON, "Expected ';' after import")
        return ImportDeclaration(".".join(parts), is_static, wildcard)

    def _parse_type(self, annotations: tuple[str, ...], modifiers: tuple[str, ...], annotation_nodes: tuple[Annotation, ...] = ()) -> TypeDeclaration:
        if self._at(JavaTokenType.AT) and self._peek_keyword("interface", distance=1):
            self._advance(); self._expect_keyword("interface")
            keyword = "annotation"
        elif self._current().lexeme in _TYPE_KEYWORDS:
            keyword = self._advance().lexeme
        else:
            raise JavaParseError("Expected a type declaration", self._current())

        name = self._expect_identifier("Expected type name").lexeme
        if self._at(JavaTokenType.LESS):
            self._collect_balanced(JavaTokenType.LESS, JavaTokenType.GREATER)
        if keyword == "record" and self._at(JavaTokenType.LEFT_PAREN):
            self._collect_balanced(JavaTokenType.LEFT_PAREN, JavaTokenType.RIGHT_PAREN)

        extends: str | None = None
        implements: tuple[str, ...] = ()
        permits: tuple[str, ...] = ()
        if self._is_keyword("extends"):
            self._advance()
            values = self._parse_type_list({"implements", "permits"})
            if keyword == "interface":
                implements = values
            elif values:
                extends = values[0]
        if self._is_keyword("implements"):
            self._advance(); implements = self._parse_type_list({"permits"})
        if self._is_keyword("permits"):
            self._advance(); permits = self._parse_type_list(set())

        fields: list[FieldDeclaration] = []
        constructors: list[ConstructorDeclaration] = []
        methods: list[MethodDeclaration] = []
        nested: list[TypeDeclaration] = []
        if self._at(JavaTokenType.SEMICOLON):
            self._advance()
        else:
            self._expect(JavaTokenType.LEFT_BRACE, "Expected type body")
            if keyword == "enum":
                self._skip_enum_constants()
            while not self._at(JavaTokenType.RIGHT_BRACE):
                if self._at(JavaTokenType.EOF):
                    raise JavaParseError("Unterminated type body", self._current())
                if self._at(JavaTokenType.SEMICOLON):
                    self._advance(); continue
                member_annotations, member_annotation_nodes = self._parse_annotations()
                member_modifiers = self._parse_modifiers()
                if self._is_type_start():
                    nested.append(self._parse_type(member_annotations, member_modifiers, member_annotation_nodes))
                    continue
                member = self._parse_member(name, member_annotations, member_modifiers, member_annotation_nodes)
                if isinstance(member, FieldDeclaration):
                    fields.append(member)
                elif isinstance(member, ConstructorDeclaration):
                    constructors.append(member)
                else:
                    methods.append(member)
            self._advance()

        node_types = {
            "class": ClassDeclaration, "interface": InterfaceDeclaration,
            "enum": EnumDeclaration, "record": RecordDeclaration,
            "annotation": AnnotationDeclaration,
        }
        return node_types[keyword](
            name=name, annotations=annotations, modifiers=modifiers,
            extends=extends, implements=implements, permits=permits,
            fields=tuple(fields), constructors=tuple(constructors),
            methods=tuple(methods), nested_types=tuple(nested),
            annotation_nodes=annotation_nodes,
        )

    def _parse_member(self, owner: str, annotations: tuple[str, ...], modifiers: tuple[str, ...], annotation_nodes: tuple[Annotation, ...] = ()):
        signature = self._collect_member_signature()
        if not signature:
            raise JavaParseError("Expected member declaration", self._current())

        assignment = self._first_top_level(signature, JavaTokenType.ASSIGN)
        paren_index = self._first_top_level(signature, JavaTokenType.LEFT_PAREN)
        if paren_index is not None and (
            assignment is None or paren_index < assignment
        ):
            close_index = self._matching_index(signature, paren_index, JavaTokenType.LEFT_PAREN, JavaTokenType.RIGHT_PAREN)
            name_index = paren_index - 1
            if name_index < 0:
                raise JavaParseError("Expected callable name", signature[0])
            name = signature[name_index].lexeme
            params = self._parse_parameters(signature[paren_index + 1:close_index])
            throws = self._parse_throws(signature[close_index + 1:])
            prefix = list(signature[:name_index])
            type_parameters = None
            if prefix and prefix[0].type == JavaTokenType.LESS:
                end = self._matching_index(prefix, 0, JavaTokenType.LESS, JavaTokenType.GREATER)
                type_parameters = self._join(prefix[:end + 1])
                prefix = prefix[end + 1:]
            if name == owner and not prefix:
                result = ConstructorDeclaration(name, params, annotations, modifiers, throws, annotation_nodes)
            else:
                return_type = self._join(prefix)
                if not return_type:
                    raise JavaParseError("Expected method return type", signature[0])
                result = MethodDeclaration(name, return_type, params, annotations, modifiers, type_parameters, throws, annotation_nodes)
            self._consume_member_terminator()
            return result

        declaration = signature if assignment is None else signature[:assignment]
        initializer = None if assignment is None else self._join(signature[assignment + 1:]) or None
        if len(declaration) < 2:
            raise JavaParseError("Expected field type and name", signature[0])
        name = declaration[-1].lexeme
        type_name = self._join(declaration[:-1])
        self._consume_member_terminator()
        return FieldDeclaration(name, type_name, annotations, modifiers, initializer, annotation_nodes)

    def _collect_member_signature(self) -> list[JavaToken]:
        result: list[JavaToken] = []
        paren = bracket = angle = 0
        while not self._at(JavaTokenType.EOF):
            t = self._current()
            if paren == bracket == angle == 0 and t.type in {JavaTokenType.SEMICOLON, JavaTokenType.LEFT_BRACE}:
                break
            result.append(self._advance())
            if t.type == JavaTokenType.LEFT_PAREN: paren += 1
            elif t.type == JavaTokenType.RIGHT_PAREN: paren -= 1
            elif t.type == JavaTokenType.LEFT_BRACKET: bracket += 1
            elif t.type == JavaTokenType.RIGHT_BRACKET: bracket -= 1
            elif t.type == JavaTokenType.LESS: angle += 1
            elif t.type == JavaTokenType.GREATER and angle: angle -= 1
        return result

    def _consume_member_terminator(self) -> None:
        if self._at(JavaTokenType.SEMICOLON):
            self._advance(); return
        if self._at(JavaTokenType.LEFT_BRACE):
            self._collect_balanced(JavaTokenType.LEFT_BRACE, JavaTokenType.RIGHT_BRACE)
            return
        raise JavaParseError("Expected member body or ';'", self._current())

    def _parse_parameters(self, tokens: Sequence[JavaToken]) -> tuple[ParameterDeclaration, ...]:
        chunks = self._split_top_level(tokens, JavaTokenType.COMMA)
        params: list[ParameterDeclaration] = []
        for chunk in chunks:
            if not chunk:
                continue
            pos = 0; annotations: list[str] = []; annotation_nodes: list[Annotation] = []; modifiers: list[str] = []
            while pos < len(chunk) and chunk[pos].type == JavaTokenType.AT:
                pos += 1
                parts: list[str] = []
                if pos >= len(chunk) or chunk[pos].type not in {JavaTokenType.IDENTIFIER, JavaTokenType.KEYWORD}:
                    raise JavaParseError("Expected parameter annotation name", chunk[0])
                parts.append(chunk[pos].lexeme)
                pos += 1
                while (
                    pos + 1 < len(chunk)
                    and chunk[pos].type == JavaTokenType.DOT
                    and chunk[pos + 1].type in {JavaTokenType.IDENTIFIER, JavaTokenType.KEYWORD}
                ):
                    parts.extend((chunk[pos].lexeme, chunk[pos + 1].lexeme))
                    pos += 2
                annotation_name = "".join(parts)
                annotations.append(annotation_name)
                arguments: tuple[AnnotationArgument, ...] = ()
                if pos < len(chunk) and chunk[pos].type == JavaTokenType.LEFT_PAREN:
                    end = self._matching_index(chunk, pos, JavaTokenType.LEFT_PAREN, JavaTokenType.RIGHT_PAREN)
                    arguments = self._annotation_arguments(chunk[pos + 1:end])
                    pos = end + 1
                annotation_nodes.append(Annotation(annotation_name, arguments))
            while pos < len(chunk) and chunk[pos].lexeme in _PARAMETER_MODIFIERS:
                modifiers.append(chunk[pos].lexeme); pos += 1
            remaining = list(chunk[pos:])
            if len(remaining) < 2:
                raise JavaParseError("Expected parameter type and name", chunk[0])
            name = remaining[-1].lexeme
            is_varargs = any(t.type == JavaTokenType.ELLIPSIS for t in remaining[:-1])
            type_tokens = [t for t in remaining[:-1] if t.type != JavaTokenType.ELLIPSIS]
            params.append(ParameterDeclaration(name, self._join(type_tokens), tuple(annotations), tuple(modifiers), is_varargs, tuple(annotation_nodes)))
        return tuple(params)

    def _parse_throws(self, tokens: Sequence[JavaToken]) -> tuple[str, ...]:
        if not tokens or tokens[0].lexeme != "throws":
            return ()
        return tuple(self._join(chunk) for chunk in self._split_top_level(tokens[1:], JavaTokenType.COMMA) if chunk)

    def _skip_enum_constants(self) -> None:
        depth = 0
        while not self._at(JavaTokenType.EOF):
            t = self._current()
            if depth == 0 and t.type == JavaTokenType.SEMICOLON:
                self._advance(); return
            if depth == 0 and t.type == JavaTokenType.RIGHT_BRACE:
                return
            self._advance()
            if t.type in {JavaTokenType.LEFT_PAREN, JavaTokenType.LEFT_BRACE}: depth += 1
            elif t.type in {JavaTokenType.RIGHT_PAREN, JavaTokenType.RIGHT_BRACE} and depth: depth -= 1

    def _parse_annotations(self) -> tuple[tuple[str, ...], tuple[Annotation, ...]]:
        names: list[str] = []
        nodes: list[Annotation] = []
        while self._at(JavaTokenType.AT) and not self._peek_keyword("interface", distance=1):
            self._advance()
            name = self._parse_qualified_name()
            arguments: tuple[AnnotationArgument, ...] = ()
            if self._at(JavaTokenType.LEFT_PAREN):
                tokens = self._collect_balanced(JavaTokenType.LEFT_PAREN, JavaTokenType.RIGHT_PAREN)
                arguments = self._annotation_arguments(tokens)
            names.append(name)
            nodes.append(Annotation(name, arguments))
        return tuple(names), tuple(nodes)

    def _annotation_arguments(self, tokens: Sequence[JavaToken]) -> tuple[AnnotationArgument, ...]:
        result: list[AnnotationArgument] = []
        for chunk in self._split_top_level(tokens, JavaTokenType.COMMA):
            if not chunk:
                continue
            assignment = self._first_top_level(chunk, JavaTokenType.ASSIGN)
            if assignment is None:
                result.append(AnnotationArgument(None, self._join(chunk)))
            else:
                name = self._join(chunk[:assignment])
                value = self._join(chunk[assignment + 1:])
                result.append(AnnotationArgument(name, value))
        return tuple(result)

    def _parse_modifiers(self) -> tuple[str, ...]:
        result = []
        while self._current().lexeme in _MODIFIERS:
            result.append(self._advance().lexeme)
        return tuple(result)

    def _parse_type_list(self, stops: set[str]) -> tuple[str, ...]:
        tokens: list[JavaToken] = []; angle = bracket = 0
        while not self._at(JavaTokenType.EOF):
            t = self._current()
            if angle == bracket == 0 and (t.lexeme in stops or t.type == JavaTokenType.LEFT_BRACE): break
            tokens.append(self._advance())
            if t.type == JavaTokenType.LESS: angle += 1
            elif t.type == JavaTokenType.GREATER and angle: angle -= 1
            elif t.type == JavaTokenType.LEFT_BRACKET: bracket += 1
            elif t.type == JavaTokenType.RIGHT_BRACKET and bracket: bracket -= 1
        return tuple(self._join(c) for c in self._split_top_level(tokens, JavaTokenType.COMMA) if c)

    def _parse_qualified_name(self) -> str:
        parts = [self._expect_identifier_like("Expected name").lexeme]
        while self._at(JavaTokenType.DOT):
            self._advance(); parts.append(self._expect_identifier_like("Expected name").lexeme)
        return ".".join(parts)

    def _is_type_start(self) -> bool:
        return self._current().lexeme in _TYPE_KEYWORDS or (self._at(JavaTokenType.AT) and self._peek_keyword("interface", distance=1))

    @staticmethod
    def _join(tokens: Sequence[JavaToken]) -> str:
        return "".join(t.lexeme for t in tokens)

    @staticmethod
    def _split_top_level(tokens: Sequence[JavaToken], delimiter: JavaTokenType) -> list[list[JavaToken]]:
        result: list[list[JavaToken]] = [[]]; paren = bracket = angle = brace = 0
        for t in tokens:
            if t.type == delimiter and paren == bracket == angle == brace == 0:
                result.append([]); continue
            result[-1].append(t)
            if t.type == JavaTokenType.LEFT_PAREN: paren += 1
            elif t.type == JavaTokenType.RIGHT_PAREN: paren -= 1
            elif t.type == JavaTokenType.LEFT_BRACKET: bracket += 1
            elif t.type == JavaTokenType.RIGHT_BRACKET: bracket -= 1
            elif t.type == JavaTokenType.LEFT_BRACE: brace += 1
            elif t.type == JavaTokenType.RIGHT_BRACE and brace: brace -= 1
            elif t.type == JavaTokenType.LESS: angle += 1
            elif t.type == JavaTokenType.GREATER and angle: angle -= 1
        return result

    @staticmethod
    def _first_top_level(tokens: Sequence[JavaToken], token_type: JavaTokenType) -> int | None:
        paren = bracket = angle = 0
        for i, t in enumerate(tokens):
            if t.type == token_type and paren == bracket == angle == 0:
                return i
            if t.type == JavaTokenType.LEFT_PAREN: paren += 1
            elif t.type == JavaTokenType.RIGHT_PAREN: paren -= 1
            elif t.type == JavaTokenType.LEFT_BRACKET: bracket += 1
            elif t.type == JavaTokenType.RIGHT_BRACKET: bracket -= 1
            elif t.type == JavaTokenType.LESS: angle += 1
            elif t.type == JavaTokenType.GREATER and angle: angle -= 1
        return None

    @staticmethod
    def _matching_index(tokens: Sequence[JavaToken], start: int, opening: JavaTokenType, closing: JavaTokenType) -> int:
        depth = 0
        for i in range(start, len(tokens)):
            if tokens[i].type == opening: depth += 1
            elif tokens[i].type == closing:
                depth -= 1
                if depth == 0: return i
        raise ValueError("Unterminated balanced token sequence")

    def _collect_balanced(self, opening: JavaTokenType, closing: JavaTokenType) -> list[JavaToken]:
        self._expect(opening, f"Expected '{opening.value}'")
        result = []; depth = 1
        while depth:
            t = self._advance()
            if t.type == JavaTokenType.EOF: raise JavaParseError("Unterminated delimited construct", t)
            if t.type == opening: depth += 1
            elif t.type == closing:
                depth -= 1
                if depth == 0: break
            result.append(t)
        return result

    def _current(self) -> JavaToken: return self._tokens[self._position]
    def _advance(self) -> JavaToken:
        t = self._current()
        if t.type != JavaTokenType.EOF: self._position += 1
        return t
    def _at(self, t: JavaTokenType) -> bool: return self._current().type == t
    def _is_keyword(self, value: str) -> bool: return self._current().type == JavaTokenType.KEYWORD and self._current().lexeme == value
    def _peek_keyword(self, value: str, *, distance: int) -> bool:
        p = self._position + distance
        return p < len(self._tokens) and self._tokens[p].type == JavaTokenType.KEYWORD and self._tokens[p].lexeme == value
    def _expect(self, t: JavaTokenType, message: str) -> JavaToken:
        if not self._at(t): raise JavaParseError(message, self._current())
        return self._advance()
    def _expect_keyword(self, value: str) -> JavaToken:
        if not self._is_keyword(value): raise JavaParseError(f"Expected keyword '{value}'", self._current())
        return self._advance()
    def _expect_identifier(self, message: str) -> JavaToken:
        if self._current().type != JavaTokenType.IDENTIFIER: raise JavaParseError(message, self._current())
        return self._advance()
    def _expect_identifier_like(self, message: str) -> JavaToken:
        if self._current().type not in {JavaTokenType.IDENTIFIER, JavaTokenType.KEYWORD}: raise JavaParseError(message, self._current())
        return self._advance()
