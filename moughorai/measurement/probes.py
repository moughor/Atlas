"""Optional, best-effort process memory probes.

Platform-specific metrics are facts only when the operating system exposes the
required counter.  Unsupported and temporarily unavailable observations remain
explicit; no counter is estimated from another value.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Protocol

from .models import MetricReason, MetricUnit, MetricValue


@dataclass(frozen=True, slots=True)
class ProcessMemoryReading:
    rss_bytes: MetricValue
    working_set_bytes: MetricValue
    commit_bytes: MetricValue


class ProcessMemoryProbe(Protocol):
    def read(self) -> ProcessMemoryReading: ...


def _unsupported_memory() -> MetricValue:
    return MetricValue.unsupported(
        MetricUnit.BYTES,
        MetricReason.PLATFORM_UNSUPPORTED,
    )


def _unavailable_memory() -> MetricValue:
    return MetricValue.unavailable(
        MetricUnit.BYTES,
        MetricReason.PROVIDER_UNAVAILABLE,
    )


class CurrentProcessMemoryProbe:
    """Read current-process counters on supported operating systems."""

    def read(self) -> ProcessMemoryReading:
        if sys.platform == "win32":
            return self._read_windows()
        if sys.platform.startswith("linux"):
            return self._read_linux()
        unavailable = _unsupported_memory()
        return ProcessMemoryReading(unavailable, unavailable, unavailable)

    @staticmethod
    def _read_linux() -> ProcessMemoryReading:
        try:
            values = Path("/proc/self/statm").read_text(encoding="ascii").split()
            resident_pages = int(values[1])
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            rss = MetricValue.measured(resident_pages * page_size, MetricUnit.BYTES)
        except (IndexError, OSError, TypeError, ValueError):
            rss = _unavailable_memory()
        # Linux does not expose Windows' process commit metric with equivalent
        # semantics.  Do not substitute virtual memory size.
        return ProcessMemoryReading(rss, rss, _unsupported_memory())

    @staticmethod
    def _read_windows() -> ProcessMemoryReading:
        try:
            import ctypes
            from ctypes import wintypes

            class ProcessMemoryCountersEx(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCountersEx()
            counters.cb = ctypes.sizeof(counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(ProcessMemoryCountersEx),
                wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            succeeded = psapi.GetProcessMemoryInfo(
                kernel32.GetCurrentProcess(),
                ctypes.byref(counters),
                counters.cb,
            )
            if not succeeded:
                raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
            working_set = MetricValue.measured(
                int(counters.WorkingSetSize),
                MetricUnit.BYTES,
            )
            commit = MetricValue.measured(int(counters.PrivateUsage), MetricUnit.BYTES)
            return ProcessMemoryReading(working_set, working_set, commit)
        except (AttributeError, ImportError, OSError, TypeError, ValueError):
            unavailable = _unavailable_memory()
            return ProcessMemoryReading(unavailable, unavailable, unavailable)
