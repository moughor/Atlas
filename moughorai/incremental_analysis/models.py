from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from moughorai.global_symbols import SymbolId
@dataclass(frozen=True)
class IncrementalAnalysisPlan:
    changed_files:tuple[Path,...]=(); removed_files:tuple[Path,...]=(); directly_changed_symbols:tuple[SymbolId,...]=(); impacted_symbols:tuple[SymbolId,...]=(); files_to_analyze:tuple[Path,...]=()
    @property
    def is_noop(self): return not self.changed_files and not self.removed_files
