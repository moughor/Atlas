"""Bounded helpers for statically inspecting Gradle source text."""

from __future__ import annotations


def literal_arguments(value: str) -> tuple[str, ...]:
    """Parse only comma-separated single- or double-quoted string literals."""
    result: list[str] = []
    position = 0
    length = len(value)
    while True:
        while position < length and value[position].isspace():
            position += 1
        if position == length:
            return tuple(result)
        quote = value[position]
        if quote not in {"'", '"'}:
            return ()
        closing = value.find(quote, position + 1)
        if closing < 0:
            return ()
        token = value[position + 1 : closing]
        if "\\" in token or "$" in token or any(
            ord(character) < 32 or ord(character) == 127
            for character in token
        ):
            return ()
        result.append(token)
        position = closing + 1
        while position < length and value[position].isspace():
            position += 1
        if position == length:
            return tuple(result)
        if value[position] != ",":
            return ()
        position += 1
        if not value[position:].strip():
            return ()


def strip_comments(source: str) -> str:
    """Mask comments with spaces while preserving strings and newlines."""
    result: list[str] = []
    position = 0
    quote: str | None = None
    while position < len(source):
        character = source[position]
        following = source[position + 1] if position + 1 < len(source) else ""
        if quote is not None:
            result.append(character)
            if character == "\\" and following:
                result.append(following)
                position += 2
                continue
            if character == quote:
                quote = None
            position += 1
            continue
        if character in {"'", '"'}:
            quote = character
            result.append(character)
            position += 1
            continue
        if character == "/" and following == "/":
            result.extend((" ", " "))
            position += 2
            while position < len(source) and source[position] not in "\r\n":
                result.append(" ")
                position += 1
            continue
        if character == "/" and following == "*":
            result.extend((" ", " "))
            position += 2
            while position < len(source):
                if source[position : position + 2] == "*/":
                    result.extend((" ", " "))
                    position += 2
                    break
                if source[position] in "\r\n":
                    result.append(source[position])
                else:
                    result.append(" ")
                position += 1
            continue
        result.append(character)
        position += 1
    return "".join(result)
