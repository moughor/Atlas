import pytest

from moughorai.java_ast.models import SourceLocation, SourceSpan


def test_source_span_length() -> None:
    span = SourceSpan(
        SourceLocation(offset=4, line=2, column=3),
        SourceLocation(offset=9, line=2, column=8),
    )

    assert span.length == 5


def test_source_location_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        SourceLocation(offset=-1, line=1, column=1)

    with pytest.raises(ValueError):
        SourceLocation(offset=0, line=0, column=1)

    with pytest.raises(ValueError):
        SourceLocation(offset=0, line=1, column=0)


def test_source_span_rejects_reversed_offsets() -> None:
    with pytest.raises(ValueError):
        SourceSpan(
            SourceLocation(offset=2, line=1, column=3),
            SourceLocation(offset=1, line=1, column=2),
        )
