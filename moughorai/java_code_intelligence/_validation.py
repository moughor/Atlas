'''Decode-local reuse for completed pure Java value validation.'''

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import re
from typing import Iterator


_MAXIMUM_VALIDATED_TEXT_VALUES_PER_WIDTH = 65_536
_CONTROL_CHARACTER = re.compile(r'[\x00-\x1f]')


@dataclass(slots=True)
class _DecodeValidationMemo:
    texts_by_width: dict[int, dict[str, str]] = field(default_factory=dict)


_DECODE_VALIDATION_MEMO: ContextVar[_DecodeValidationMemo | None] = ContextVar(
    'java_decode_validation_memo', default=None,
)


@contextmanager
def reconstruction_validation_scope() -> Iterator[None]:
    '''Bound successful validation reuse to one canonical reconstruction.'''

    if _DECODE_VALIDATION_MEMO.get() is not None:
        yield
        return
    token = _DECODE_VALIDATION_MEMO.set(_DecodeValidationMemo())
    try:
        yield
    finally:
        _DECODE_VALIDATION_MEMO.reset(token)


def validated_text(
    value: object,
    label: str,
    maximum: int,
) -> str:
    '''Fully validate each unique immutable text value once per decode.'''

    if not isinstance(value, str):
        raise TypeError(f'{label} must be a string')
    memo = _DECODE_VALIDATION_MEMO.get()
    proven_values = None
    if memo is not None:
        proven_values = memo.texts_by_width.get(maximum)
        proven = (
            proven_values.get(value)
            if proven_values is not None
            else None
        )
        if proven is not None:
            return proven
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f'{label} is empty or oversized')
    if _CONTROL_CHARACTER.search(normalized) is not None:
        raise ValueError(f'{label} contains control characters')
    if (
        memo is not None
        and (
            proven_values is None
            or len(proven_values) < _MAXIMUM_VALIDATED_TEXT_VALUES_PER_WIDTH
        )
    ):
        if proven_values is None:
            proven_values = {}
            memo.texts_by_width[maximum] = proven_values
        proven_values[value] = normalized
    return normalized
