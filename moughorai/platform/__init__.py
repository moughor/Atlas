"""Domain-neutral infrastructure shared across Atlas intelligence domains."""

from .safety import contains_absolute_path, contains_absolute_path_text

__all__ = [
    "contains_absolute_path",
    "contains_absolute_path_text",
]
