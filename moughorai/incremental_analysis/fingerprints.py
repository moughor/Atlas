"""Deterministic content fingerprints used by incremental analysis."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, order=True)
class FileFingerprint:
    path: Path
    size: int
    sha256: str

    def __post_init__(self) -> None:
        if self.size < 0:
            raise ValueError("fingerprint size must be non-negative")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise ValueError("sha256 must be a lowercase hexadecimal digest")


class FingerprintService:
    """Hashes bytes and project files without relying on timestamps."""

    @staticmethod
    def digest_bytes(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def fingerprint(self, path: Path, *, root: Path | None = None) -> FileFingerprint:
        absolute = path if path.is_absolute() else (root / path if root else path)
        content = absolute.read_bytes()
        logical = absolute.relative_to(root) if root is not None else path
        return FileFingerprint(logical, len(content), self.digest_bytes(content))

    def scan(self, root: Path, paths: Iterable[Path]) -> tuple[FileFingerprint, ...]:
        values = (self.fingerprint(path, root=root) for path in paths)
        return tuple(sorted(values, key=lambda item: item.path.as_posix().casefold()))
