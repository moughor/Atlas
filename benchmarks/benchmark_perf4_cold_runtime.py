"""Process-cold benchmark for Atlas interactive snapshot replay.

This runner never analyzes the target workspace.  It drives the public interactive
session over an existing configured-active snapshot and records externally observed
milestones.  Operating-system file caches are deliberately left uncontrolled, so
results are process-cold / OS-warm-or-uncontrolled rather than disk-cold.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
from statistics import median
import subprocess
import sys
from threading import Condition, Thread
from time import perf_counter, sleep
from typing import Any


_PROMPT = b"atlas> "
_READY = b"Atlas session ready."
_COMMANDS = (
    ("search", "/search mapEventToSepJmsEvent"),
    ("use", "/use 1"),
    ("first_answer", "/answer"),
    ("second_answer", "/answer"),
    ("detail", "/answer detail"),
    ("full", "/answer full"),
    ("stats", "/stats"),
)


class _ProcessMemoryCountersEx(ctypes.Structure):
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


def _read_memory(process: subprocess.Popen[bytes]) -> tuple[int, int] | None:
    if sys.platform != "win32" or process.poll() is not None:
        return None
    try:
        counters = _ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ProcessMemoryCountersEx),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(
            wintypes.HANDLE(int(process._handle)),  # type: ignore[attr-defined]
            ctypes.byref(counters),
            counters.cb,
        ):
            return None
        return int(counters.WorkingSetSize), int(counters.PrivateUsage)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _wait_for(condition: Condition, predicate, timeout: float, label: str) -> None:
    deadline = perf_counter() + timeout
    with condition:
        while not predicate():
            remaining = deadline - perf_counter()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for {label}")
            condition.wait(min(remaining, 0.25))


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stage_memory(
    samples: list[tuple[float, int, int]],
    start: float,
    end: float,
) -> dict[str, int | None]:
    selected = [item for item in samples if start <= item[0] <= end]
    if not selected:
        return {"working_set_bytes": None, "private_bytes": None}
    return {
        "working_set_bytes": max(item[1] for item in selected),
        "private_bytes": max(item[2] for item in selected),
    }


def run_once(
    workspace: Path,
    source_root: Path,
    *,
    timeout: float,
) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(source_root)
    started = perf_counter()
    process = subprocess.Popen(
        [sys.executable, "-B", "-m", "moughorai.atlas_cli", "ai", "session", "."],
        cwd=workspace,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    assert process.stdin is not None and process.stdout is not None
    condition = Condition()
    output = bytearray()
    prompt_events: list[tuple[float, int, int]] = []
    ready_events: list[float] = []
    memory_samples: list[tuple[float, int, int]] = []
    reader_error: list[BaseException] = []

    def read_output() -> None:
        prompt_cursor = 0
        ready_cursor = 0
        try:
            while True:
                value = process.stdout.read(1)
                if not value:
                    break
                with condition:
                    output.extend(value)
                    if len(output) >= len(_READY):
                        position = output.find(_READY, ready_cursor)
                        if position >= 0:
                            ready_events.append(perf_counter())
                            ready_cursor = position + len(_READY)
                    if len(output) >= len(_PROMPT):
                        position = output.find(_PROMPT, prompt_cursor)
                        if position >= 0:
                            prompt_events.append((
                                perf_counter(), position, position + len(_PROMPT)
                            ))
                            prompt_cursor = position + len(_PROMPT)
                    condition.notify_all()
        except BaseException as exc:  # pragma: no cover - diagnostic containment
            with condition:
                reader_error.append(exc)
                condition.notify_all()

    def sample_memory() -> None:
        while process.poll() is None:
            reading = _read_memory(process)
            if reading is not None:
                memory_samples.append((perf_counter(), *reading))
            sleep(0.02)

    reader = Thread(target=read_output, name="perf4-output", daemon=True)
    sampler = Thread(target=sample_memory, name="perf4-memory", daemon=True)
    reader.start()
    sampler.start()

    sent_at: dict[str, float] = {}
    try:
        _wait_for(
            condition,
            lambda: bool(prompt_events) or bool(reader_error) or process.poll() is not None,
            timeout,
            "session-ready prompt",
        )
        if not prompt_events:
            raise RuntimeError("session terminated before its first prompt")
        for expected_prompts, (name, command) in enumerate(_COMMANDS, start=2):
            sent_at[name] = perf_counter()
            process.stdin.write((command + "\n").encode("utf-8"))
            process.stdin.flush()
            _wait_for(
                condition,
                lambda count=expected_prompts: (
                    len(prompt_events) >= count
                    or bool(reader_error)
                    or process.poll() is not None
                ),
                timeout,
                f"{name} completion prompt",
            )
            if len(prompt_events) < expected_prompts:
                raise RuntimeError(f"session terminated during {name}")
        process.stdin.write(b"/exit\n")
        process.stdin.flush()
        process.wait(timeout=timeout)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        reader.join(timeout=5)
        sampler.join(timeout=5)

    if reader_error:
        raise RuntimeError("interactive output reader failed") from reader_error[0]
    if process.returncode != 0:
        raise RuntimeError(
            f"interactive session exited {process.returncode}: "
            + bytes(output[-4000:]).decode("utf-8", errors="replace")
        )
    if not ready_events:
        raise RuntimeError("session-ready marker was not emitted")

    stage_output: dict[str, bytes] = {}
    completion_times: dict[str, float] = {}
    for index, (name, _command) in enumerate(_COMMANDS, start=1):
        completion, prompt_start, _prompt_end = prompt_events[index]
        previous_prompt_end = prompt_events[index - 1][2]
        stage_output[name] = bytes(output[previous_prompt_end:prompt_start])
        completion_times[name] = completion

    stage_times = {
        name: completion_times[name] - sent_at[name]
        for name, _command in _COMMANDS
    }
    intervals = {
        "session_ready": (started, ready_events[0]),
        **{
            name: (sent_at[name], completion_times[name])
            for name, _command in _COMMANDS
        },
    }
    text = bytes(output).decode("utf-8", errors="replace")
    snapshot_id_match = re.search(
        r"^snapshot-id: ([0-9a-f]{64})\r?$",
        text,
        re.MULTILINE,
    )
    snapshot_path_match = re.search(r"^snapshot: (.+)$", text, re.MULTILINE)
    stats_match = re.search(rb"\{\"component_build_counts\".+?\}\r?\n", stage_output["stats"])
    if stats_match is None:
        raise RuntimeError("runtime statistics were not emitted")
    return {
        "session_ready_seconds": ready_events[0] - started,
        "time_to_first_useful_answer_seconds": completion_times["first_answer"] - started,
        "stage_seconds": stage_times,
        "memory": {
            name: _stage_memory(memory_samples, *interval)
            for name, interval in intervals.items()
        },
        "peak_memory": _stage_memory(memory_samples, started, completion_times["full"]),
        "snapshot_id": snapshot_id_match.group(1) if snapshot_id_match else None,
        "snapshot_path": snapshot_path_match.group(1).strip() if snapshot_path_match else None,
        "search_contains_expected_target": (
            b"method:1866238c68d2edfabdb458cd" in stage_output["search"]
            and b"sygma-it-sygma-it-services" in stage_output["search"]
        ),
        "output_hashes": {
            name: _hash(stage_output[name])
            for name in ("first_answer", "second_answer", "detail", "full")
        },
        "repeat_answer_byte_identical": (
            stage_output["first_answer"] == stage_output["second_answer"]
        ),
        "stats": json.loads(stats_match.group(0)),
    }


def _summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    def distribution(values: list[float]) -> dict[str, float]:
        return {
            "median": median(values),
            "minimum": min(values),
            "maximum": max(values),
        }

    metrics = {
        "session_ready_seconds": [item["session_ready_seconds"] for item in samples],
        "time_to_first_useful_answer_seconds": [
            item["time_to_first_useful_answer_seconds"] for item in samples
        ],
    }
    for name, _command in _COMMANDS:
        metrics[f"{name}_seconds"] = [
            item["stage_seconds"][name] for item in samples
        ]
    return {
        "run_count": len(samples),
        "cache_state": "process-cold/os-warm-or-uncontrolled",
        "distributions": {
            name: distribution(values) for name, values in metrics.items()
        },
        "samples": samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=300.0)
    arguments = parser.parse_args()
    if arguments.runs < 1:
        parser.error("--runs must be positive")
    workspace = arguments.workspace.expanduser().resolve()
    source_root = arguments.source_root.expanduser().resolve()
    samples = []
    for run_number in range(1, arguments.runs + 1):
        sample = run_once(workspace, source_root, timeout=arguments.timeout)
        samples.append(sample)
        print(json.dumps({"run": run_number, **sample}, sort_keys=True), flush=True)
    print(json.dumps(_summary(samples), sort_keys=True))


if __name__ == "__main__":
    main()
