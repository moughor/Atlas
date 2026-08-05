from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from urllib.parse import unquote


_EMBEDDED_ABSOLUTE_PATH = re.compile(
    r"(?ix)"
    r"(?:"
    r"file://[^\s,;\)\]\}]+"
    r"|(?<![A-Za-z0-9])[A-Z]:[\\/][^\s,;\)\]\}]+"
    r"|(?<![:A-Za-z0-9])(?:\\\\|//)[^\s,;\)\]\}]+"
    r"|(?<![/A-Za-z0-9])/(?:[^/\s,;\)\]\}]+)(?:/[^\s,;\)\]\}]*)*"
    r")"
)
def contains_absolute_path_text(value: str) -> bool:
    """Return whether text contains a machine-specific absolute path."""

    text = value.strip()
    if not text:
        return False
    # Percent encoding can hide a machine root even when the original text has
    # no literal slash. Decode until stable so nested percent encoding cannot
    # bypass the same boundary. Every successful unquote consumes at least one
    # percent escape, so this loop is bounded by the input length rather than by
    # an arbitrary security-sensitive limit.
    candidate = text
    if _EMBEDDED_ABSOLUTE_PATH.search(candidate) is not None:
        return True
    while True:
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded
        if _EMBEDDED_ABSOLUTE_PATH.search(candidate) is not None:
            return True
    return False


def contains_absolute_path(value: object) -> bool:
    """Return whether a nested value contains a machine-specific absolute path."""

    if isinstance(value, Mapping):
        return any(
            contains_absolute_path(key) or contains_absolute_path(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(contains_absolute_path(item) for item in value)
    if not isinstance(value, str):
        return False
    return contains_absolute_path_text(value)
