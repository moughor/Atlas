from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from moughorai.security_analysis import SecurityReport, SecurityProgram


@dataclass(frozen=True, slots=True)
class JavaSourceUnit:
    path: str
    source: str

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError("path must not be empty")


@dataclass(frozen=True, slots=True)
class JavaParseWarning:
    path: str
    line: int
    message: str


@dataclass(frozen=True, slots=True)
class JavaSecurityParseResult:
    program: SecurityProgram
    warnings: tuple[JavaParseWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class JavaProjectScanResult:
    report: SecurityReport
    source_files: int
    configuration_files: int
    warnings: tuple[JavaParseWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class JavaProjectInput:
    sources: tuple[JavaSourceUnit, ...] = ()
    configurations: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_directory(cls, root: str | Path) -> "JavaProjectInput":
        base = Path(root)
        if not base.exists():
            raise FileNotFoundError(base)
        sources = tuple(
            JavaSourceUnit(str(path.relative_to(base)).replace("\\", "/"), path.read_text(encoding="utf-8"))
            for path in sorted(base.rglob("*.java"))
        )
        configurations = tuple(
            (str(path.relative_to(base)).replace("\\", "/"), path.read_text(encoding="utf-8"))
            for pattern in ("application.properties", "application.yml", "application.yaml")
            for path in sorted(base.rglob(pattern))
        )
        return cls(sources, configurations)
