from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
class Propagation(str,Enum):
    REQUIRED='REQUIRED'; REQUIRES_NEW='REQUIRES_NEW'; MANDATORY='MANDATORY'; SUPPORTS='SUPPORTS'; NOT_SUPPORTED='NOT_SUPPORTED'; NEVER='NEVER'; NESTED='NESTED'
@dataclass(frozen=True,order=True)
class TransactionBoundary:
    symbol: str
    propagation: Propagation=Propagation.REQUIRED
    read_only: bool=False
    rollback_for: tuple[str,...]=()
    no_rollback_for: tuple[str,...]=()
@dataclass(frozen=True,order=True)
class TransactionCall:
    caller: str
    callee: str
@dataclass(frozen=True)
class TransactionFlow:
    root: str
    symbols: tuple[str,...]
    suspended_at: tuple[str,...]=()
    new_transactions: tuple[str,...]=()
