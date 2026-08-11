'''Conservative deterministic resolution of represented Java call sites.'''

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
import re

from .call_sites import (
    CallResolutionState,
    CallSiteEvidence,
    CallSiteRequest,
    InvocationKind,
    ReceiverKind,
)
from .models import CallableIndexEntry


MAXIMUM_CALL_TARGET_CANDIDATES = 64

_REFLECTION_MEMBERS = frozenset({
    'forName', 'getConstructor', 'getDeclaredConstructor',
    'getDeclaredMethod', 'getMethod', 'invoke', 'newInstance',
})


class CallResolver:
    '''Resolve only targets supported by represented callable identities.'''

    def __init__(
        self,
        entries: Iterable[CallableIndexEntry],
        *,
        parents: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        ordered = tuple(sorted(
            entries,
            key=lambda item: (
                item.identity.owner_type,
                item.identity.name,
                item.identity.normalized_key,
                item.canonical_subject_id,
            ),
        ))
        self._entries = ordered
        self._owners = {item.identity.owner_type for item in ordered}
        self._by_owner_name: dict[
            tuple[str, str], tuple[CallableIndexEntry, ...]
        ] = {}
        grouped: dict[tuple[str, str], list[CallableIndexEntry]] = {}
        for item in ordered:
            grouped.setdefault((
                item.identity.owner_type,
                item.identity.name,
            ), []).append(item)
        self._by_owner_name = {
            key: tuple(value) for key, value in grouped.items()
        }
        self._parents = {
            owner: tuple(sorted(set(values)))
            for owner, values in (parents or {}).items()
        }
        children: dict[str, set[str]] = {}
        for child, values in self._parents.items():
            for parent in values:
                children.setdefault(parent, set()).add(child)
        self._children = {
            owner: tuple(sorted(values))
            for owner, values in children.items()
        }

    def resolve(self, request: CallSiteRequest) -> CallSiteEvidence:
        if self._unsupported(request):
            return CallSiteEvidence.create(
                request,
                CallResolutionState.UNSUPPORTED,
                limitations=(
                    'Reflection-like or dynamic call syntax is represented but '
                    'not statically resolved.',
                ),
            )
        if request.receiver_kind is ReceiverKind.UNKNOWN:
            return CallSiteEvidence.create(
                request,
                CallResolutionState.UNSUPPORTED,
                limitations=(
                    'The receiver expression is outside the supported source model.',
                ),
            )
        if not request.owner_type_hints:
            return CallSiteEvidence.create(
                request,
                CallResolutionState.UNRESOLVED,
                limitations=(
                    'No deterministic represented owner type is available.',
                ),
            )

        candidates = self._direct_candidates(request)
        if not candidates:
            state = (
                CallResolutionState.UNRESOLVED
                if any(owner in self._owners for owner in request.owner_type_hints)
                else CallResolutionState.EXTERNAL
            )
            limitation = (
                'The requested owner is represented but no compatible callable '
                'declaration was found.'
                if state is CallResolutionState.UNRESOLVED
                else 'The requested callable owner is outside represented source.'
            )
            return CallSiteEvidence.create(
                request, state, limitations=(limitation,),
            )

        selected = self._select_overload(request, candidates)
        if request.receiver_kind is ReceiverKind.WILDCARD_STATIC_IMPORT:
            return self._ambiguous(
                request,
                selected or candidates,
                'Wildcard static import target selection remains conservative.',
            )
        if len(selected) != 1:
            return self._ambiguous(
                request,
                selected or candidates,
                'Multiple represented overloads remain legal under available hints.',
            )

        declared = selected[0]
        if (
            request.invocation_kind is InvocationKind.CONSTRUCTOR_INVOCATION
            or request.receiver_kind in {
                ReceiverKind.TYPE,
                ReceiverKind.STATIC_IMPORT,
                ReceiverKind.SUPER,
                ReceiverKind.CONSTRUCTOR,
            }
        ):
            return self._resolved(request, declared)

        dispatch = self._dispatch_candidates(declared)
        if dispatch:
            limited, omitted = _bounded(dispatch)
            limitations = [
                'Runtime dispatch is not proven; represented override targets '
                'are conservative candidates.',
            ]
            if omitted:
                limitations.append(
                    f'{omitted} represented dispatch target(s) were omitted by '
                    'the deterministic candidate bound.'
                )
            return CallSiteEvidence.create(
                request,
                CallResolutionState.POLYMORPHIC,
                declared_target_id=declared.canonical_subject_id,
                candidate_target_ids=(
                    item.canonical_subject_id for item in limited
                ),
                limitations=limitations,
            )
        return self._resolved(
            request,
            declared,
            limitation=(
                'No represented override candidate exists; runtime execution '
                'or external subtype dispatch is not proven.',
            ),
        )

    def _direct_candidates(
        self,
        request: CallSiteRequest,
    ) -> tuple[CallableIndexEntry, ...]:
        results: list[CallableIndexEntry] = []
        for owner in request.owner_type_hints:
            if (
                request.invocation_kind is InvocationKind.CONSTRUCTOR_INVOCATION
                or request.invocation_kind is InvocationKind.METHOD_REFERENCE
                and request.member_name == 'new'
            ):
                owner_candidates = self._by_owner_name.get(
                    (owner, '<init>'), (),
                )
            else:
                owner_candidates = self._nearest_members(
                    owner, request.member_name,
                )
            results.extend(
                item for item in owner_candidates
                if self._arity_matches(item, request.argument_count)
            )
        return tuple(sorted(
            {item.canonical_subject_id: item for item in results}.values(),
            key=lambda item: (
                item.identity.normalized_key,
                item.canonical_subject_id,
            ),
        ))

    def _nearest_members(
        self,
        owner: str,
        name: str,
    ) -> tuple[CallableIndexEntry, ...]:
        pending = deque([(owner, 0)])
        seen: set[str] = set()
        by_depth: dict[int, list[CallableIndexEntry]] = {}
        while pending:
            current, depth = pending.popleft()
            if current in seen:
                continue
            seen.add(current)
            matches = self._by_owner_name.get((current, name), ())
            if matches:
                by_depth.setdefault(depth, []).extend(matches)
            if by_depth and depth >= min(by_depth):
                continue
            pending.extend(
                (parent, depth + 1)
                for parent in self._parents.get(current, ())
            )
        if not by_depth:
            return ()
        return tuple(by_depth[min(by_depth)])

    @staticmethod
    def _arity_matches(
        entry: CallableIndexEntry,
        argument_count: int | None,
    ) -> bool:
        if argument_count is None:
            return True
        parameters = entry.identity.parameter_types
        if parameters and parameters[-1].endswith('...'):
            return argument_count >= len(parameters) - 1
        return argument_count == len(parameters)

    def _select_overload(
        self,
        request: CallSiteRequest,
        candidates: Sequence[CallableIndexEntry],
    ) -> tuple[CallableIndexEntry, ...]:
        if len(candidates) <= 1 or request.argument_count is None:
            return tuple(candidates)
        if not request.argument_hints or all(
            hint == 'unknown' for hint in request.argument_hints
        ):
            return tuple(candidates)
        compatible = tuple(
            candidate for candidate in candidates
            if self._arguments_compatible(
                request.argument_hints,
                candidate.identity.parameter_types,
            )
        )
        return compatible or tuple(candidates)

    @classmethod
    def _arguments_compatible(
        cls,
        hints: Sequence[str],
        parameters: Sequence[str],
    ) -> bool:
        if parameters and parameters[-1].endswith('...'):
            expanded = tuple(parameters[:-1]) + tuple(
                parameters[-1] for _ in range(
                    max(0, len(hints) - len(parameters) + 1)
                )
            )
        else:
            expanded = tuple(parameters)
        if len(expanded) != len(hints):
            return False
        return all(
            cls._argument_compatible(hint, parameter)
            for hint, parameter in zip(hints, expanded, strict=True)
        )

    @staticmethod
    def _argument_compatible(hint: str, parameter: str) -> bool:
        if hint == 'unknown' or hint == 'literal:null':
            return not (
                hint == 'literal:null' and parameter.startswith('primitive:')
            )
        category, _, value = hint.partition(':')
        normalized = parameter.removesuffix('...')
        if category == 'primitive':
            return normalized == f'primitive:{value}'
        if category != 'type':
            return True
        requested = _simple_type(value)
        actual = _simple_type(normalized)
        return requested == actual

    def _dispatch_candidates(
        self,
        declared: CallableIndexEntry,
    ) -> tuple[CallableIndexEntry, ...]:
        owner = declared.identity.owner_type
        descendants: list[str] = []
        pending = deque(self._children.get(owner, ()))
        seen: set[str] = set()
        while pending:
            current = pending.popleft()
            if current in seen:
                continue
            seen.add(current)
            descendants.append(current)
            pending.extend(self._children.get(current, ()))
        matches = []
        for descendant in sorted(descendants):
            for candidate in self._by_owner_name.get((
                descendant, declared.identity.name,
            ), ()):
                if (
                    candidate.identity.parameter_types
                    == declared.identity.parameter_types
                ):
                    matches.append(candidate)
        return tuple(sorted(
            matches,
            key=lambda item: item.canonical_subject_id,
        ))

    @staticmethod
    def _unsupported(request: CallSiteRequest) -> bool:
        if request.member_name in _REFLECTION_MEMBERS and any(
            owner in {
                'java.lang.Class',
                'java.lang.reflect.Constructor',
                'java.lang.reflect.Method',
            }
            for owner in request.owner_type_hints
        ):
            return True
        return any(
            'unsupported' in limitation.casefold()
            for limitation in request.limitations
        )

    @staticmethod
    def _resolved(
        request: CallSiteRequest,
        target: CallableIndexEntry,
        *,
        limitation: Iterable[str] = (),
    ) -> CallSiteEvidence:
        return CallSiteEvidence.create(
            request,
            CallResolutionState.RESOLVED,
            target_subject_id=target.canonical_subject_id,
            limitations=(
                'A represented syntactic call site resolves to one represented '
                'target; runtime execution is not proven.',
                *limitation,
            ),
        )

    @staticmethod
    def _ambiguous(
        request: CallSiteRequest,
        candidates: Sequence[CallableIndexEntry],
        limitation: str,
    ) -> CallSiteEvidence:
        limited, omitted = _bounded(candidates)
        limitations = [limitation]
        if omitted:
            limitations.append(
                f'{omitted} represented candidate(s) were omitted by the '
                'deterministic candidate bound.'
            )
        return CallSiteEvidence.create(
            request,
            CallResolutionState.AMBIGUOUS,
            candidate_target_ids=(
                item.canonical_subject_id for item in limited
            ),
            limitations=limitations,
        )


def _simple_type(value: str) -> str:
    normalized = re.sub(r'<.*>', '', value)
    normalized = normalized.rsplit(':', 1)[-1]
    normalized = normalized.removesuffix('[]')
    return normalized.rsplit('.', 1)[-1]


def _bounded(
    candidates: Sequence[CallableIndexEntry],
) -> tuple[tuple[CallableIndexEntry, ...], int]:
    ordered = tuple(sorted(
        {item.canonical_subject_id: item for item in candidates}.values(),
        key=lambda item: item.canonical_subject_id,
    ))
    retained = ordered[:MAXIMUM_CALL_TARGET_CANDIDATES]
    return retained, len(ordered) - len(retained)
