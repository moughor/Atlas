from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from moughorai.domains.benchmark import (
    CapturedSourceV1,
    CaptureValidationError,
    parse_fire_strike_submission_fixture,
    sha256_hex,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "benchmark_intelligence"
    / "fire_strike_submission_v1.json"
)


def test_identical_bytes_have_stable_digest_identity_and_metadata() -> None:
    payload = b"<html>Atlas fixture</html>"

    first = CapturedSourceV1(
        payload,
        source_identifier="source:hwbot",
        media_type="TEXT/HTML",
    )
    second = CapturedSourceV1(
        payload,
        media_type="text/html",
        source_identifier="source:hwbot",
    )

    assert first.sha256 == second.sha256 == sha256_hex(payload)
    assert first.capture_id == second.capture_id
    assert first.to_metadata_dict() == second.to_metadata_dict()
    assert first.to_metadata_json() == second.to_metadata_json()
    assert first.to_metadata_bytes() == second.to_metadata_bytes()


def test_one_byte_mutation_changes_capture_identity() -> None:
    first = CapturedSourceV1(b"\x00\x01\x02")
    second = CapturedSourceV1(b"\x00\x01\x03")

    assert first.sha256 != second.sha256
    assert first.capture_id != second.capture_id


@pytest.mark.parametrize("payload", [b"", bytes(range(256)), b"\xff\x00\x80\xfe"])
def test_empty_and_arbitrary_binary_payloads_are_retained_exactly(
    payload: bytes,
) -> None:
    capture = CapturedSourceV1(payload)

    assert capture.payload is payload
    assert capture.byte_length == len(payload)
    assert capture.sha256 == sha256_hex(payload)


@pytest.mark.parametrize("payload", [bytearray(b"atlas"), memoryview(b"atlas"), "atlas"])
def test_mutable_or_non_byte_payloads_are_rejected(payload: object) -> None:
    with pytest.raises(TypeError, match="payload must be bytes"):
        CapturedSourceV1(payload)  # type: ignore[arg-type]


def test_bytes_subclasses_are_rejected_including_stateful_length_override() -> None:
    class BytesSubclass(bytes):
        pass

    class StatefulLengthBytes(bytes):
        def __new__(cls, value: bytes):
            instance = super().__new__(cls, value)
            instance.reported_length = len(value)
            return instance

        def __len__(self) -> int:
            return self.reported_length

    for payload in (BytesSubclass(b"atlas"), StatefulLengthBytes(b"atlas")):
        with pytest.raises(TypeError, match="payload must be bytes"):
            CapturedSourceV1(payload)


def test_digest_is_not_cached_and_tracks_base_level_payload_replacement() -> None:
    capture = CapturedSourceV1(
        b"original",
        source_identifier="source:hwbot",
        media_type="application/octet-stream",
    )

    assert "_sha256" not in {item.name for item in fields(capture)}
    assert "_sha256" not in CapturedSourceV1.__slots__
    assert not hasattr(capture, "_sha256")

    mutated = b"mutated"
    object.__setattr__(capture, "payload", mutated)
    digest = sha256_hex(mutated)
    metadata = capture.to_metadata_dict()

    assert capture.payload is mutated
    assert capture.sha256 == digest
    assert capture.capture_id == f"capture:sha256:{digest}"
    assert capture.byte_length == len(mutated)
    assert metadata == {
        "byte_length": len(mutated),
        "capture_id": f"capture:sha256:{digest}",
        "media_type": "application/octet-stream",
        "sha256": digest,
        "source_identifier": "source:hwbot",
    }
    assert capture.to_metadata_bytes() == CapturedSourceV1(
        mutated,
        source_identifier="source:hwbot",
        media_type="application/octet-stream",
    ).to_metadata_bytes()


def test_lowercase_expected_digest_verifies_without_becoming_metadata() -> None:
    payload = b"verified capture"
    digest = sha256_hex(payload)

    capture = CapturedSourceV1(payload, expected_sha256=digest)

    assert capture.sha256 == digest
    assert set(capture.to_metadata_dict()) == {
        "byte_length",
        "capture_id",
        "media_type",
        "sha256",
        "source_identifier",
    }
    assert "expected" not in capture.to_metadata_json()
    assert "schema_version" not in capture.to_metadata_json()


def test_uppercase_expected_digest_is_rejected() -> None:
    payload = b"verified capture"

    with pytest.raises(CaptureValidationError, match="64 lowercase"):
        CapturedSourceV1(payload, expected_sha256=sha256_hex(payload).upper())


@pytest.mark.parametrize(
    "expected",
    ["", "0" * 63, "0" * 65, "g" * 64, "sha256:" + "0" * 64],
)
def test_malformed_expected_digest_is_rejected(expected: str) -> None:
    with pytest.raises(CaptureValidationError, match="64 lowercase"):
        CapturedSourceV1(b"payload", expected_sha256=expected)


def test_valid_but_incorrect_expected_digest_fails_explicitly() -> None:
    with pytest.raises(CaptureValidationError, match="does not match"):
        CapturedSourceV1(b"\xff", expected_sha256="0" * 64)


def test_source_and_media_metadata_do_not_affect_capture_identity() -> None:
    payload = b"same exact source bytes"
    captures = (
        CapturedSourceV1(payload),
        CapturedSourceV1(
            payload,
            source_identifier="source:hwbot",
            media_type="text/html",
        ),
        CapturedSourceV1(
            payload,
            source_identifier="source:ul-3dmark",
            media_type="application/json",
        ),
    )

    assert len({capture.capture_id for capture in captures}) == 1
    assert len({capture.sha256 for capture in captures}) == 1
    assert len({capture.to_metadata_bytes() for capture in captures}) == 3


@pytest.mark.parametrize(
    "source_identifier",
    ["source:hwbot", "source:ul-3dmark", "source:elmor", "source:atlas-fixture"],
)
def test_valid_source_identifiers_are_preserved(source_identifier: str) -> None:
    capture = CapturedSourceV1(b"payload", source_identifier=source_identifier)

    assert capture.source_identifier == source_identifier


@pytest.mark.parametrize(
    "source_identifier",
    [
        "", "hwbot", "source:", "source:-hwbot", "source:HWBot",
        "source:hw_bot", "source:hwbot/source", "source:hwbót",
    ],
)
def test_invalid_source_identifiers_are_rejected(source_identifier: str) -> None:
    with pytest.raises(CaptureValidationError, match="source:<lowercase-slug>"):
        CapturedSourceV1(b"payload", source_identifier=source_identifier)


@pytest.mark.parametrize(
    ("media_type", "expected"),
    [
        ("text/html", "text/html"),
        ("APPLICATION/JSON", "application/json"),
        ("image/png", "image/png"),
        ("application/octet-stream", "application/octet-stream"),
        ("application/vnd.atlas+json", "application/vnd.atlas+json"),
    ],
)
def test_bare_media_types_are_normalized(media_type: str, expected: str) -> None:
    capture = CapturedSourceV1(b"payload", media_type=media_type)

    assert capture.media_type == expected


@pytest.mark.parametrize(
    "media_type",
    [
        "", "text", "/html", "text/", " text/html", "text/html ",
        "text /html", "text/ html", "text/html; charset=utf-8", "téxt/html",
    ],
)
def test_invalid_media_types_are_rejected(media_type: str) -> None:
    with pytest.raises(CaptureValidationError, match="bare type/subtype"):
        CapturedSourceV1(b"payload", media_type=media_type)


@pytest.mark.parametrize("field", ["source_identifier", "media_type"])
@pytest.mark.parametrize("surrogate", ["\ud800", "\udc00"])
def test_unpaired_surrogates_are_rejected_in_metadata(
    field: str,
    surrogate: str,
) -> None:
    with pytest.raises(CaptureValidationError, match="invalid Unicode"):
        CapturedSourceV1(b"payload", **{field: surrogate})


def test_optional_metadata_serializes_as_explicit_null() -> None:
    capture = CapturedSourceV1(b"")

    assert capture.to_metadata_dict()["source_identifier"] is None
    assert capture.to_metadata_dict()["media_type"] is None
    assert '"media_type":null' in capture.to_metadata_json()
    assert '"source_identifier":null' in capture.to_metadata_json()
    assert "payload" not in capture.to_metadata_json()


def test_capture_model_is_immutable() -> None:
    capture = CapturedSourceV1(b"immutable")

    with pytest.raises(FrozenInstanceError):
        capture.payload = b"changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        capture.media_type = "text/html"  # type: ignore[misc]


def test_repeated_construction_is_byte_stable() -> None:
    values = tuple(
        CapturedSourceV1(
            b"repeatable",
            source_identifier="source:hwbot",
            media_type="application/octet-stream",
        )
        for _ in range(3)
    )

    assert len({capture.capture_id for capture in values}) == 1
    assert len({capture.to_metadata_bytes() for capture in values}) == 1


def test_pr146_fixture_passes_unchanged_through_capture_boundary() -> None:
    payload = FIXTURE.read_bytes()
    capture = CapturedSourceV1(
        payload,
        expected_sha256=sha256_hex(payload),
        source_identifier="source:atlas-fixture",
        media_type="application/json",
    )

    submission = parse_fire_strike_submission_fixture(
        capture.payload,
        capture.sha256,
    )

    assert capture.payload is payload
    assert all(
        evidence.capture_sha256 == capture.sha256
        for evidence in (
            submission.overall_score,
            submission.graphics_score,
            submission.physics_score,
            submission.combined_score,
        )
    )
