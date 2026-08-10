"""Narrow canonicalization rules owned by Benchmark Intelligence."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import unicodedata


_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


def normalize_text(value: str) -> str:
    """Return one deterministic Unicode representation of text."""

    if not isinstance(value, str):
        raise TypeError("canonical text must be a string")
    normalized = unicodedata.normalize("NFC", value)
    try:
        normalized.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(
            "canonical text must contain only Unicode scalar values"
        ) from error
    return normalized


def normalize_decimal(value: str) -> str:
    """Normalize one finite, base-ten decimal string without using floats."""

    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError("decimal value must use strict finite decimal notation")
    try:
        number = Decimal(value)
    except InvalidOperation as error:  # defensive: the lexical check is stricter
        raise ValueError("decimal value is invalid") from error
    if not number.is_finite():
        raise ValueError("decimal value must be finite")
    if number == 0:
        return "0"
    normalized = format(number, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized


def _normalize_json(value: object) -> object:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        raise TypeError("canonical JSON does not accept binary floating-point values")
    if isinstance(value, str):
        return normalize_text(value)
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise TypeError("canonical JSON object keys must be strings")
            key = normalize_text(raw_key)
            if key in result:
                raise ValueError("canonical JSON keys collide after NFC normalization")
            result[key] = _normalize_json(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: object) -> str:
    """Serialize a JSON-compatible value using the Benchmark V1 contract."""

    return json.dumps(
        _normalize_json(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_json_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    if not isinstance(value, bytes):
        raise TypeError("SHA-256 input must be bytes")
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: object) -> str:
    return sha256_hex(canonical_json_bytes(value))
