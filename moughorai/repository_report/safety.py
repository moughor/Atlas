from __future__ import annotations

from collections.abc import Mapping, Sequence
import re


_EMBEDDED_ABSOLUTE_PATH = re.compile(
    r"(?ix)"
    r"(?:"
    r"file://[^\s,;\)\]\}]+"
    r"|(?<![A-Za-z0-9])[A-Z]:[\\/][^\s,;\)\]\}]+"
    r"|(?<![:A-Za-z0-9])(?:\\\\|//)[^\s,;\)\]\}]+"
    r"|(?<![:/A-Za-z0-9])/(?:[^/\s,;\)\]\}]+)(?:/[^\s,;\)\]\}]*)*"
    r")"
)
_CANONICAL_DERIVED_ID = re.compile(
    r"^(?:evidence:|report-item:|repository-report:)[0-9a-f]{64}$"
)


def contains_absolute_path_text(value: str) -> bool:
    """Return whether text contains a machine-specific absolute path."""

    text = value.strip()
    if not text:
        return False
    return _EMBEDDED_ABSOLUTE_PATH.search(text) is not None


def contains_absolute_path(value: object) -> bool:
    """Recursively enforce the source-free report path boundary."""

    if isinstance(value, Mapping):
        return any(
            contains_absolute_path(key) or contains_absolute_path(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(contains_absolute_path(item) for item in value)
    if not isinstance(value, str):
        return False
    if _CANONICAL_DERIVED_ID.fullmatch(value):
        return False
    return contains_absolute_path_text(value)
