'''Conservative normalization for represented Java callable declarations.'''

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Iterable

from moughorai.java_ast.ast_nodes import CompilationUnit
from moughorai.java_resolution import JavaTypeResolver, ResolutionStatus
from moughorai.java_symbols import CallableSymbol, ConstructorSymbol, TypeSymbol
from moughorai.java_symbols.index import JavaSymbolIndex

from .models import (
    CallableKind,
    NormalizedCallableIdentity,
    ParameterResolution,
    SourceClassification,
)


_TYPE_NAME = re.compile(r'[A-Za-z_$][A-Za-z0-9_$.]*\Z')


@dataclass(frozen=True, slots=True)
class SourceClassificationResult:
    classification: SourceClassification
    relative_path: str | None
    evidence: str
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _NormalizedType:
    value: str
    resolution: ParameterResolution
    limitations: tuple[str, ...] = ()


def classify_source(
    source: Path,
    project_root: Path,
    source_roots: Iterable[object] = (),
) -> SourceClassificationResult:
    '''Classify one Java source from roots, then strict path conventions.'''

    try:
        resolved = source.resolve()
        root = project_root.resolve()
        relative = resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return SourceClassificationResult(
            SourceClassification.UNKNOWN,
            None,
            'unavailable',
            ('Source path is outside the represented project root.',),
        )

    path_text = relative.as_posix()
    matches: list[tuple[int, str]] = []
    for candidate in source_roots:
        candidate_path = getattr(candidate, 'path', None)
        candidate_kind = getattr(candidate, 'kind', None)
        if not isinstance(candidate_path, Path) or candidate_kind is None:
            continue
        try:
            source_relative = resolved.relative_to(candidate_path.resolve())
        except (OSError, RuntimeError, ValueError):
            continue
        kind = str(getattr(candidate_kind, 'value', candidate_kind)).casefold()
        depth = len(relative.parts) - len(source_relative.parts)
        matches.append((depth, kind))

    if matches:
        deepest = max(depth for depth, _ in matches)
        kinds = {kind for depth, kind in matches if depth == deepest}
        mapped = {
            'main': SourceClassification.PRODUCTION,
            'test': SourceClassification.TEST,
            'generated': SourceClassification.GENERATED,
        }
        classifications = {mapped[kind] for kind in kinds if kind in mapped}
        if len(classifications) == 1:
            return SourceClassificationResult(
                classifications.pop(),
                path_text,
                'workspace-source-root',
            )
        if len(classifications) > 1:
            return SourceClassificationResult(
                SourceClassification.UNKNOWN,
                path_text,
                'ambiguous-workspace-source-root',
                ('Source matches conflicting authoritative source-root kinds.',),
            )

    parts = tuple(part.casefold() for part in relative.parts)
    directories = parts[:-1]
    for index in range(max(0, len(directories) - 1)):
        pair = directories[index:index + 2]
        if pair in {
            ('target', 'generated-sources'),
            ('target', 'generated-test-sources'),
            ('build', 'generated'),
            ('build', 'generated-sources'),
            ('build', 'generated-test-sources'),
        }:
            return SourceClassificationResult(
                SourceClassification.GENERATED,
                path_text,
                'conventional-generated-source-root',
            )

    for index, part in enumerate(directories):
        if part != 'src' or index + 1 >= len(directories):
            continue
        source_set = directories[index + 1]
        if source_set == 'generated':
            return SourceClassificationResult(
                SourceClassification.GENERATED,
                path_text,
                'conventional-generated-source-root',
            )
        if source_set == 'test' or re.fullmatch(r'test[1-9][0-9]*', source_set):
            return SourceClassificationResult(
                SourceClassification.TEST,
                path_text,
                'conventional-test-source-root',
            )
        if source_set == 'main' or re.fullmatch(r'main[1-9][0-9]*', source_set):
            return SourceClassificationResult(
                SourceClassification.PRODUCTION,
                path_text,
                'conventional-main-source-root',
            )

    return SourceClassificationResult(
        SourceClassification.UNKNOWN,
        path_text,
        'unclassified-source-root',
        ('No authoritative or conventional source-root classification exists.',),
    )


class CallableIdentityNormalizer:
    '''Build normalized source identities without changing canonical IDs.'''

    def __init__(self, index: JavaSymbolIndex) -> None:
        self._index = index
        self._resolver = JavaTypeResolver(index)

    def normalize(
        self,
        symbol: CallableSymbol,
        unit: CompilationUnit,
    ) -> NormalizedCallableIdentity:
        if symbol.owner is None:
            raise ValueError('callable owner is unavailable')
        owner = self._index.type_by_name(symbol.owner)
        enclosing: list[TypeSymbol] = []
        current = owner
        seen_owners: set[str] = set()
        while current is not None and current.owner is not None:
            if current.qualified_name in seen_owners:
                raise ValueError('callable owner nesting is cyclic')
            seen_owners.add(current.qualified_name)
            current = self._index.type_by_name(current.owner)
            if current is not None:
                enclosing.append(current)
        variables = {
            name: f'typevar:enclosing:{depth}:{index}'
            for depth, declaration in enumerate(reversed(enclosing))
            for index, name in enumerate(declaration.type_parameter_names)
        }
        variables.update({
            name: f'typevar:owner:{index}'
            for index, name in enumerate(
                owner.type_parameter_names if owner is not None else ()
            )
        })
        variables.update({
            name: f'typevar:callable:{index}'
            for index, name in enumerate(symbol.type_parameter_names)
        })
        varargs = symbol.parameter_varargs or tuple(
            False for _ in symbol.parameter_types
        )
        if len(varargs) != len(symbol.parameter_types):
            raise ValueError('callable varargs metadata is inconsistent')

        normalized = tuple(
            self._normalize_type(
                type_name,
                unit,
                variables,
                is_varargs=is_varargs,
            )
            for type_name, is_varargs in zip(
                symbol.parameter_types,
                varargs,
                strict=True,
            )
        )
        kind = (
            CallableKind.CONSTRUCTOR
            if isinstance(symbol, ConstructorSymbol)
            else CallableKind.METHOD
        )
        name = '<init>' if kind is CallableKind.CONSTRUCTOR else symbol.name
        raw_parameters = tuple(
            f'{value}...' if is_varargs else value
            for value, is_varargs in zip(
                symbol.parameter_types,
                varargs,
                strict=True,
            )
        )
        separator = ','
        raw_signature = (
            f'{symbol.owner}#{name}({separator.join(raw_parameters)})'
        )
        parameter_types = tuple(item.value for item in normalized)
        normalized_key = (
            f'java-callable:v1:{symbol.owner}#{name}'
            f'({separator.join(parameter_types)})'
        )
        return NormalizedCallableIdentity(
            symbol.owner,
            kind,
            name,
            parameter_types,
            tuple(item.resolution for item in normalized),
            raw_signature,
            normalized_key,
            tuple(
                limitation
                for item in normalized
                for limitation in item.limitations
            ),
        )

    def _normalize_type(
        self,
        raw: str,
        unit: CompilationUnit,
        variables: dict[str, str],
        *,
        is_varargs: bool = False,
    ) -> _NormalizedType:
        compact = re.sub(r'\s+', '', raw)
        dimensions = 0
        while compact.endswith('[]'):
            compact = compact[:-2]
            dimensions += 1

        if compact.startswith('?extends'):
            nested = self._normalize_type(
                compact[len('?extends'):], unit, variables
            )
            return self._decorate(nested, '?extends:', dimensions, is_varargs)
        if compact.startswith('?super'):
            nested = self._normalize_type(
                compact[len('?super'):], unit, variables
            )
            return self._decorate(nested, '?super:', dimensions, is_varargs)
        if compact == '?':
            return self._decorate(
                _NormalizedType('wildcard:any', ParameterResolution.UNRESOLVED),
                '',
                dimensions,
                is_varargs,
            )

        base, arguments, balanced = _generic_parts(compact)
        base_identity = self._normalize_base(base, unit, variables)
        normalized_arguments = tuple(
            self._normalize_type(item, unit, variables)
            for item in arguments
        )
        limitations = tuple(base_identity.limitations) + tuple(
            limitation
            for item in normalized_arguments
            for limitation in item.limitations
        )
        if not balanced:
            limitations = (*limitations, 'Generic type syntax was not balanced.')
        value = base_identity.value
        if normalized_arguments:
            value += '<' + ','.join(
                item.value for item in normalized_arguments
            ) + '>'
        resolution = _least_resolution((
            base_identity.resolution,
            *(item.resolution for item in normalized_arguments),
        ))
        return self._decorate(
            _NormalizedType(value, resolution, limitations),
            '',
            dimensions,
            is_varargs,
        )

    def _normalize_base(
        self,
        name: str,
        unit: CompilationUnit,
        variables: dict[str, str],
    ) -> _NormalizedType:
        if name in variables:
            return _NormalizedType(
                variables[name],
                ParameterResolution.TYPE_VARIABLE,
            )
        if not _TYPE_NAME.fullmatch(name):
            normalized = _unresolved_identity(name)
            return _NormalizedType(
                normalized,
                ParameterResolution.UNRESOLVED,
                ('Parameter type syntax is unsupported.',),
            )

        resolution = self._resolver.resolve(name, unit)
        if resolution.status is ResolutionStatus.PRIMITIVE:
            return _NormalizedType(
                f'primitive:{resolution.qualified_name}',
                ParameterResolution.PRIMITIVE,
            )
        if resolution.status is ResolutionStatus.RESOLVED:
            return _NormalizedType(
                f'type:{resolution.qualified_name}',
                ParameterResolution.RESOLVED,
            )

        explicit = _explicit_import_identity(name, unit)
        if explicit is not None:
            represented = self._index.type_by_name(explicit)
            return _NormalizedType(
                ('type:' if represented is not None else 'external:') + explicit,
                (
                    ParameterResolution.RESOLVED
                    if represented is not None
                    else ParameterResolution.EXTERNAL
                ),
                (() if represented is not None else (
                    'Parameter type is explicitly qualified but unrepresented.',
                )),
            )
        if '.' in name and name.partition('.')[0][:1].islower():
            return _NormalizedType(
                f'external:{name}',
                ParameterResolution.EXTERNAL,
                ('Parameter type is qualified but unrepresented.',),
            )
        if resolution.status is ResolutionStatus.AMBIGUOUS:
            candidate_digest = hashlib.sha256(
                '\n'.join(sorted(resolution.candidates)).encode('utf-8')
            ).hexdigest()[:16]
            return _NormalizedType(
                f'ambiguous:{name}@{candidate_digest}',
                ParameterResolution.AMBIGUOUS,
                ('Parameter type resolution is ambiguous.',),
            )
        return _NormalizedType(
            _unresolved_identity(name),
            ParameterResolution.UNRESOLVED,
            ('Parameter type could not be resolved without fabrication.',),
        )

    @staticmethod
    def _decorate(
        value: _NormalizedType,
        prefix: str,
        dimensions: int,
        is_varargs: bool,
    ) -> _NormalizedType:
        suffix = '[]' * dimensions
        if is_varargs:
            suffix += '...'
        return _NormalizedType(
            prefix + value.value + suffix,
            value.resolution,
            value.limitations,
        )


def _generic_parts(value: str) -> tuple[str, tuple[str, ...], bool]:
    opening = value.find('<')
    if opening < 0:
        return value, (), True
    depth = 0
    closing = -1
    for index, character in enumerate(value[opening:], start=opening):
        if character == '<':
            depth += 1
        elif character == '>':
            depth -= 1
            if depth == 0:
                closing = index
                break
    if closing != len(value) - 1 or depth != 0:
        return value[:opening] or value, (), False
    arguments = _split_generic_arguments(value[opening + 1:closing])
    return value[:opening], arguments, True


def _split_generic_arguments(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    result: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(value):
        if character == '<':
            depth += 1
        elif character == '>':
            depth -= 1
        elif character == ',' and depth == 0:
            result.append(value[start:index])
            start = index + 1
    result.append(value[start:])
    return tuple(result)


def _explicit_import_identity(
    name: str,
    unit: CompilationUnit,
) -> str | None:
    first, separator, remainder = name.partition('.')
    matches = {
        declaration.name + (separator + remainder if separator else '')
        for declaration in unit.imports
        if (
            not declaration.is_static
            and not declaration.is_wildcard
            and declaration.name.rsplit('.', 1)[-1] == first
        )
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _unresolved_identity(name: str) -> str:
    normalized = name or 'unknown'
    return f'unresolved:{normalized}'


def _least_resolution(
    values: Iterable[ParameterResolution],
) -> ParameterResolution:
    rank = {
        ParameterResolution.PRIMITIVE: 0,
        ParameterResolution.TYPE_VARIABLE: 1,
        ParameterResolution.RESOLVED: 2,
        ParameterResolution.EXTERNAL: 3,
        ParameterResolution.AMBIGUOUS: 4,
        ParameterResolution.UNRESOLVED: 5,
    }
    return max(values, key=rank.__getitem__)
