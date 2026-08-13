'''Decode-local reuse for completed pure Java value validation.'''

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Iterator


_MAXIMUM_VALIDATED_TEXT_VALUES = 65_536


@dataclass(slots=True)
class _DecodeValidationMemo:
    texts: dict[tuple[int, str], str] = field(default_factory=dict)


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
    key = (maximum, value)
    if memo is not None:
        proven = memo.texts.get(key)
        if proven is not None:
            return proven
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f'{label} is empty or oversized')
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f'{label} contains control characters')
    if (
        memo is not None
        and len(memo.texts) < _MAXIMUM_VALIDATED_TEXT_VALUES
    ):
        memo.texts[key] = normalized
    return normalized
