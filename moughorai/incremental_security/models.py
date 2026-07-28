from __future__ import annotations
from dataclasses import dataclass
from moughorai.security_analysis import SecurityFinding, SecurityReport

@dataclass(frozen=True, slots=True)
class CacheEntry:
    path: str
    fingerprint: str
    findings: tuple[SecurityFinding, ...] = ()
    warnings: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class IncrementalCache:
    version: int = 1
    analyzer_key: str = ""
    entries: tuple[CacheEntry, ...] = ()
    def by_path(self) -> dict[str, CacheEntry]:
        return {entry.path: entry for entry in self.entries}

@dataclass(frozen=True, slots=True)
class IncrementalScanMetrics:
    total_files: int
    analyzed_files: int
    reused_files: int
    invalidated_files: int
    removed_files: int
    cache_hit_ratio: float

@dataclass(frozen=True, slots=True)
class IncrementalScanResult:
    report: SecurityReport
    cache: IncrementalCache
    metrics: IncrementalScanMetrics
    analyzed_paths: tuple[str, ...] = ()
    reused_paths: tuple[str, ...] = ()
    invalidated_paths: tuple[str, ...] = ()
    removed_paths: tuple[str, ...] = ()
