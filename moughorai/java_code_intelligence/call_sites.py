'''Source-safe represented Java call-site extraction and evidence models.'''

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Iterable, Mapping, Sequence

from moughorai.java_ast.ast_nodes import (
    CallSiteSyntax,
    CallSyntaxKind,
    CompilationUnit,
    ConstructorDeclaration,
    MethodDeclaration,
    TypeDeclaration,
)
from moughorai.java_ast.lexer import JavaLexer

from .models import JavaCallableIndex, SourcePosition, SourceRange


_HINT = re.compile(r'(?:literal|identifier|new|type|primitive|unknown)(?::[^\s]+)?\Z')


def _is_java_structured_name(value: str) -> bool:
    '''Match identifier(.identifier)* using the canonical Java lexer rules.'''

    segments = value.split('.')
    return bool(segments) and all(
        segment
        and JavaLexer._is_identifier_start(segment[0])
        and all(
            JavaLexer._is_identifier_part(character)
            for character in segment[1:]
        )
        for segment in segments
    )


def _java_structured_text(value: object, label: str) -> str:
    normalized = _text(value, label, 1_024)
    if normalized != value or not _is_java_structured_name(normalized):
        raise ValueError(f'{label} must be a structured name')
    return normalized


class InvocationKind(str, Enum):
    METHOD_INVOCATION = 'method_invocation'
    CONSTRUCTOR_INVOCATION = 'constructor_invocation'
    METHOD_REFERENCE = 'method_reference'


class ReceiverKind(str, Enum):
    UNQUALIFIED = 'unqualified'
    TYPE = 'type'
    INSTANCE = 'instance'
    THIS = 'this'
    SUPER = 'super'
    STATIC_IMPORT = 'static_import'
    WILDCARD_STATIC_IMPORT = 'wildcard_static_import'
    CONSTRUCTOR = 'constructor'
    UNKNOWN = 'unknown'


class CallResolutionState(str, Enum):
    RESOLVED = 'resolved'
    POLYMORPHIC = 'polymorphic'
    AMBIGUOUS = 'ambiguous'
    UNRESOLVED = 'unresolved'
    EXTERNAL = 'external'
    UNSUPPORTED = 'unsupported'


def _text(value: object, label: str, maximum: int = 1_024) -> str:
    if not isinstance(value, str):
        raise TypeError(f'{label} must be a string')
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f'{label} is empty or oversized')
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f'{label} contains control characters')
    return normalized


def _relative_path(value: object) -> str:
    text = _text(value, 'call-site path', 2_048)
    if '\\' in text:
        raise ValueError('call-site path must use POSIX separators')
    path = PurePosixPath(text)
    if path.is_absolute() or any(
        part in {'', '.', '..'} or ':' in part for part in path.parts
    ):
        raise ValueError('call-site path must be workspace-relative')
    return path.as_posix()


@dataclass(frozen=True, order=True, slots=True)
class CallSiteRequest:
    caller_subject_id: str
    caller_normalized_key: str
    project_id: str
    source_path: str
    source_range: SourceRange
    invocation_kind: InvocationKind
    receiver_kind: ReceiverKind
    member_name: str
    receiver: str | None
    owner_type_hints: tuple[str, ...]
    argument_hints: tuple[str, ...]
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, 'caller_subject_id', _text(
            self.caller_subject_id, 'caller canonical ID', 256,
        ))
        object.__setattr__(self, 'caller_normalized_key', _text(
            self.caller_normalized_key, 'caller normalized key', 4_096,
        ))
        object.__setattr__(self, 'project_id', _text(
            self.project_id, 'call-site project', 256,
        ))
        object.__setattr__(self, 'source_path', _relative_path(self.source_path))
        if not isinstance(self.source_range, SourceRange):
            raise TypeError('call-site source range is invalid')
        if not isinstance(self.invocation_kind, InvocationKind):
            raise TypeError('invocation kind is invalid')
        if not isinstance(self.receiver_kind, ReceiverKind):
            raise TypeError('receiver kind is invalid')
        member = _text(self.member_name, 'invoked member', 256)
        receiver = self.receiver
        if receiver is not None:
            receiver = _java_structured_text(receiver, 'call receiver')
        owners = tuple(sorted(set(
            _java_structured_text(item, 'owner type hint')
            for item in self.owner_type_hints
        )))
        arguments = tuple(
            _text(item, 'argument hint', 1_024)
            for item in self.argument_hints
        )
        if any(_HINT.fullmatch(item) is None for item in arguments):
            raise ValueError('argument hint is not structured')
        limitations = tuple(sorted(set(
            _text(item, 'call-site limitation', 512)
            for item in self.limitations
        )))
        object.__setattr__(self, 'member_name', member)
        object.__setattr__(self, 'receiver', receiver)
        object.__setattr__(self, 'owner_type_hints', owners)
        object.__setattr__(self, 'argument_hints', arguments)
        object.__setattr__(self, 'limitations', limitations)

    @property
    def argument_count(self) -> int | None:
        if self.invocation_kind is InvocationKind.METHOD_REFERENCE:
            return None
        return len(self.argument_hints)


@dataclass(frozen=True, order=True, slots=True)
class CallSiteEvidence:
    request: CallSiteRequest
    state: CallResolutionState
    evidence_id: str
    target_subject_id: str | None = None
    declared_target_id: str | None = None
    candidate_target_ids: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.request, CallSiteRequest):
            raise TypeError('call-site request is invalid')
        if not isinstance(self.state, CallResolutionState):
            raise TypeError('call resolution state is invalid')
        evidence_id = _text(self.evidence_id, 'call evidence ID', 96)
        if not evidence_id.startswith('evidence:') or len(evidence_id) != 73:
            raise ValueError('call evidence ID is malformed')
        target = self.target_subject_id
        declared = self.declared_target_id
        if target is not None:
            target = _text(target, 'resolved target ID', 256)
        if declared is not None:
            declared = _text(declared, 'declared target ID', 256)
        candidates = tuple(sorted(set(
            _text(item, 'candidate target ID', 256)
            for item in self.candidate_target_ids
        )))
        if self.state is CallResolutionState.RESOLVED:
            if target is None or declared is not None or candidates:
                raise ValueError('resolved call target coverage is inconsistent')
        elif target is not None:
            raise ValueError('uncertain call cannot contain a resolved target')
        if self.state is CallResolutionState.POLYMORPHIC and (
            declared is None and not candidates
        ):
            raise ValueError('polymorphic call has no represented targets')
        if self.state in {
            CallResolutionState.UNRESOLVED,
            CallResolutionState.EXTERNAL,
            CallResolutionState.UNSUPPORTED,
        } and (declared is not None or candidates):
            raise ValueError('unresolved call cannot contain target candidates')
        limitations = tuple(sorted(set(
            _text(item, 'resolution limitation', 512)
            for item in self.limitations
        )))
        object.__setattr__(self, 'evidence_id', evidence_id)
        object.__setattr__(self, 'target_subject_id', target)
        object.__setattr__(self, 'declared_target_id', declared)
        object.__setattr__(self, 'candidate_target_ids', candidates)
        object.__setattr__(self, 'limitations', limitations)

    @classmethod
    def create(
        cls,
        request: CallSiteRequest,
        state: CallResolutionState,
        *,
        target_subject_id: str | None = None,
        declared_target_id: str | None = None,
        candidate_target_ids: Iterable[str] = (),
        limitations: Iterable[str] = (),
    ) -> CallSiteEvidence:
        candidates = tuple(sorted(set(candidate_target_ids)))
        limits = tuple(sorted(set((*request.limitations, *limitations))))
        payload = {
            'request': call_request_to_dict(request),
            'state': state.value,
            'target_subject_id': target_subject_id,
            'declared_target_id': declared_target_id,
            'candidate_target_ids': list(candidates),
            'limitations': list(limits),
        }
        digest = hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, separators=(',', ':'), sort_keys=True,
        ).encode('utf-8')).hexdigest()
        return cls(
            request, state, f'evidence:{digest}', target_subject_id,
            declared_target_id, candidates, limits,
        )

    def as_request(self) -> CallSiteRequest:
        return self.request


def call_request_to_dict(value: CallSiteRequest) -> dict[str, object]:
    return {
        'caller_subject_id': value.caller_subject_id,
        'caller_normalized_key': value.caller_normalized_key,
        'project_id': value.project_id,
        'source_path': value.source_path,
        'source_range': value.source_range.to_dict(),
        'invocation_kind': value.invocation_kind.value,
        'receiver_kind': value.receiver_kind.value,
        'member_name': value.member_name,
        'receiver': value.receiver,
        'owner_type_hints': list(value.owner_type_hints),
        'argument_count': value.argument_count,
        'argument_hints': list(value.argument_hints),
        'limitations': list(value.limitations),
    }


def call_evidence_to_dict(value: CallSiteEvidence) -> dict[str, object]:
    return {
        **call_request_to_dict(value.request),
        'state': value.state.value,
        'target_subject_id': value.target_subject_id,
        'declared_target_id': value.declared_target_id,
        'candidate_target_ids': list(value.candidate_target_ids),
        'evidence_id': value.evidence_id,
        'resolution_limitations': list(value.limitations),
    }


@dataclass(frozen=True, slots=True)
class CallSiteExtraction:
    requests: tuple[CallSiteRequest, ...]
    callable_bodies_examined: int
    callable_bodies_unavailable: int
    extraction_failures: int


class CallSiteExtractor:
    '''Map AST call syntax to authoritative PR156 caller identities.'''

    def extract(
        self,
        units: Sequence[CompilationUnit],
        sources: Sequence[Path],
        callable_index: JavaCallableIndex,
        *,
        project_root: Path,
        parents: Mapping[str, Iterable[str]] | None = None,
    ) -> CallSiteExtraction:
        if len(units) != len(sources):
            raise ValueError('call-site units and sources must align')
        entry_by_location = {
            (
                item.source.path,
                item.source.declaration.start.line,
                item.source.declaration.start.column,
            ): item
            for item in callable_index.entries
        }
        represented_owners = {
            item.identity.owner_type for item in callable_index.entries
        }
        parent_map = {
            owner: tuple(sorted(set(values)))
            for owner, values in (parents or {}).items()
        }
        requests: list[CallSiteRequest] = []
        examined = unavailable = failures = 0

        for unit, source in zip(units, sources, strict=True):
            try:
                relative = source.resolve().relative_to(
                    project_root.resolve()
                ).as_posix()
            except (OSError, RuntimeError, ValueError):
                failures += 1
                continue
            for declaration, owner, fields in _callable_declarations(unit):
                span = declaration.declaration_span
                if span is None:
                    failures += 1
                    continue
                entry = entry_by_location.get((
                    relative, span.start.line, span.start.column,
                ))
                if entry is None:
                    failures += 1
                    continue
                if declaration.body_span is None:
                    unavailable += 1
                    continue
                examined += 1
                variables = {
                    parameter.name: parameter.type_name
                    for parameter in declaration.parameters
                }
                variables.update(fields)
                for syntax in declaration.call_sites:
                    requests.append(self._request(
                        syntax, unit, entry.canonical_subject_id,
                        entry.identity.normalized_key, entry.project_id,
                        relative, owner, variables, represented_owners,
                        parent_map,
                    ))
        return CallSiteExtraction(
            tuple(sorted(set(requests), key=_request_sort_key)),
            examined,
            unavailable,
            failures,
        )

    def _request(
        self,
        syntax: CallSiteSyntax,
        unit: CompilationUnit,
        caller_id: str,
        caller_key: str,
        project_id: str,
        path: str,
        owner: str,
        variables: Mapping[str, str],
        represented_owners: set[str],
        parents: Mapping[str, tuple[str, ...]],
    ) -> CallSiteRequest:
        kind = InvocationKind(syntax.kind.value)
        receiver_kind, owner_hints, limitations = self._owners(
            syntax, unit, owner, variables, represented_owners, parents,
        )
        receiver = syntax.receiver
        if receiver is not None and not _is_java_structured_name(receiver):
            receiver = None
            receiver_kind = ReceiverKind.UNKNOWN
            owner_hints = ()
            limitations = (
                *limitations,
                'Receiver syntax is outside the represented structured-name model.',
            )
        argument_hints = tuple(
            self._qualify_argument(
                hint, variables, unit, represented_owners,
            )
            for hint in syntax.argument_hints
        )
        if syntax.unsupported_reason is not None:
            limitations = (*limitations, syntax.unsupported_reason)
            receiver_kind = ReceiverKind.UNKNOWN
        return CallSiteRequest(
            caller_id,
            caller_key,
            project_id,
            path,
            SourceRange(
                SourcePosition(
                    syntax.span.start.line, syntax.span.start.column,
                ),
                SourcePosition(syntax.span.end.line, syntax.span.end.column),
            ),
            kind,
            receiver_kind,
            syntax.member_name,
            receiver,
            owner_hints,
            argument_hints,
            limitations,
        )

    def _owners(
        self,
        syntax: CallSiteSyntax,
        unit: CompilationUnit,
        owner: str,
        variables: Mapping[str, str],
        represented: set[str],
        parents: Mapping[str, tuple[str, ...]],
    ) -> tuple[ReceiverKind, tuple[str, ...], tuple[str, ...]]:
        if syntax.kind is CallSyntaxKind.CONSTRUCTOR_INVOCATION:
            if syntax.requested_owner == 'this':
                return ReceiverKind.CONSTRUCTOR, (owner,), ()
            if syntax.requested_owner == 'super':
                return ReceiverKind.SUPER, parents.get(owner, ()), ()
            requested = self._qualify_type(
                syntax.requested_owner, unit, represented,
            )
            return ReceiverKind.CONSTRUCTOR, ((requested,) if requested else ()), ()

        receiver = syntax.receiver
        if receiver == 'this':
            return ReceiverKind.THIS, (owner,), ()
        if receiver == 'super':
            return ReceiverKind.SUPER, parents.get(owner, ()), ()
        if receiver is not None and receiver.startswith('this.'):
            field_name = receiver.removeprefix('this.')
            if '.' not in field_name and field_name in variables:
                target = self._qualify_type(
                    variables[field_name], unit, represented,
                )
                return ReceiverKind.INSTANCE, ((target,) if target else ()), ()
        if receiver is not None and receiver in variables:
            target = self._qualify_type(variables[receiver], unit, represented)
            return ReceiverKind.INSTANCE, ((target,) if target else ()), ()
        if receiver is not None and syntax.requested_owner is not None:
            target = self._qualify_type(
                syntax.requested_owner, unit, represented,
            )
            return ReceiverKind.INSTANCE, ((target,) if target else ()), ()
        if receiver is not None:
            target = self._qualify_type(receiver, unit, represented)
            if '.' in receiver and receiver.rsplit('.', 1)[-1][:1].islower():
                return ReceiverKind.UNKNOWN, (), (
                    'Qualified receiver expression has no represented static type.',
                )
            if (
                '.' not in receiver
                and receiver[:1].islower()
                and target not in represented
            ):
                return ReceiverKind.UNKNOWN, (), (
                    'Unbound lowercase receiver has no represented static type.',
                )
            if target is not None:
                return ReceiverKind.TYPE, (target,), ()
            return ReceiverKind.UNKNOWN, (), (
                'Receiver type could not be determined without fabrication.',
            )

        explicit = {
            item.name.rsplit('.', 1)[0]
            for item in unit.imports
            if (
                item.is_static and not item.is_wildcard
                and item.name.rsplit('.', 1)[-1] == syntax.member_name
            )
        }
        wildcard = {
            item.name for item in unit.imports
            if item.is_static and item.is_wildcard
        }
        if explicit:
            return ReceiverKind.STATIC_IMPORT, tuple(sorted(explicit)), ()
        if wildcard:
            return (
                ReceiverKind.WILDCARD_STATIC_IMPORT,
                tuple(sorted(wildcard)),
                ('Wildcard static import resolution remains conservative.',),
            )
        return ReceiverKind.UNQUALIFIED, (owner,), ()

    def _qualify_argument(
        self,
        hint: str,
        variables: Mapping[str, str],
        unit: CompilationUnit,
        represented: set[str],
    ) -> str:
        if hint.startswith('identifier:'):
            raw = variables.get(hint.partition(':')[2])
            qualified = self._qualify_type(raw, unit, represented)
            return f'type:{qualified}' if qualified else 'unknown'
        if hint.startswith('new:'):
            qualified = self._qualify_type(
                hint.partition(':')[2], unit, represented,
            )
            return f'type:{qualified}' if qualified else 'unknown'
        if hint.startswith('literal:'):
            literal = hint.partition(':')[2]
            if literal in {
                'boolean', 'byte', 'char', 'double', 'float',
                'int', 'long', 'short',
            }:
                return f'primitive:{literal}'
            if literal == 'String':
                return 'type:java.lang.String'
            return hint
        return 'unknown'

    @staticmethod
    def _qualify_type(
        raw: str | None,
        unit: CompilationUnit,
        represented: set[str],
    ) -> str | None:
        if raw is None:
            return None
        value = re.sub(r'<.*>', '', raw.replace('...', '')).strip()
        while value.endswith('[]'):
            value = value[:-2]
        if not value or not _is_java_structured_name(value):
            return None
        if value in {
            'boolean', 'byte', 'char', 'double', 'float',
            'int', 'long', 'short', 'void',
        }:
            return value
        if '.' in value and value.partition('.')[0][:1].islower():
            return value
        matches = {
            item.name + value[len(item.name.rsplit('.', 1)[-1]):]
            for item in unit.imports
            if (
                not item.is_static and not item.is_wildcard
                and item.name.rsplit('.', 1)[-1] == value.partition('.')[0]
            )
        }
        if len(matches) == 1:
            return next(iter(matches))
        package = unit.package.name if unit.package is not None else ''
        same_package = f'{package}.{value}' if package else value
        if same_package in represented:
            return same_package
        wildcard_matches = {
            f'{item.name}.{value}'
            for item in unit.imports
            if (
                not item.is_static and item.is_wildcard
                and f'{item.name}.{value}' in represented
            )
        }
        if len(wildcard_matches) == 1:
            return next(iter(wildcard_matches))
        if value in {
            'Boolean', 'Byte', 'Character', 'Class', 'Double', 'Float',
            'Integer', 'Long', 'Object', 'Short', 'String', 'Throwable',
        }:
            return f'java.lang.{value}'
        return same_package


def _request_sort_key(item: CallSiteRequest) -> tuple[object, ...]:
    return (
        item.source_path,
        item.source_range.start.line,
        item.source_range.start.column,
        item.source_range.end.line,
        item.source_range.end.column,
        item.caller_subject_id,
        item.invocation_kind.value,
        item.member_name,
        item.receiver or '',
        item.owner_type_hints,
        item.argument_hints,
    )


def _callable_declarations(
    unit: CompilationUnit,
) -> tuple[tuple[object, str, Mapping[str, str]], ...]:
    package = unit.package.name if unit.package is not None else ''
    result: list[tuple[object, str, Mapping[str, str]]] = []

    def visit(declaration: TypeDeclaration, enclosing: str = '') -> None:
        local = f'{enclosing}.{declaration.name}' if enclosing else declaration.name
        owner = f'{package}.{local}' if package else local
        fields = {item.name: item.type_name for item in declaration.fields}
        for item in declaration.constructors:
            if isinstance(item, ConstructorDeclaration):
                result.append((item, owner, fields))
        for item in declaration.methods:
            if isinstance(item, MethodDeclaration):
                result.append((item, owner, fields))
        for nested in declaration.nested_types:
            visit(nested, local)

    for root in unit.types:
        visit(root)
    return tuple(result)
