"""Solver-neutral process-tree supervision for benchmark campaigns."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    temporary.replace(path)


def _signal_owned_process_tree(process: subprocess.Popen[Any], sig: int) -> None:
    """Handle macOS group-signal denial and the exit-at-deadline race."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, sig)
        return
    except ProcessLookupError:
        return
    except PermissionError:
        if process.poll() is not None:
            return
    import psutil

    try:
        descendants = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        descendants = []
    for child in reversed(descendants):
        try:
            child.send_signal(sig)
        except psutil.NoSuchProcess:
            pass
    process.send_signal(sig)


def _macos_memory_free_percent() -> float | None:
    if sys.platform != "darwin":
        return None
    try:
        completed = subprocess.run(
            ["memory_pressure", "-Q"], capture_output=True, check=False,
            text=True, timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in completed.stdout.splitlines():
        prefix = "System-wide memory free percentage:"
        if line.startswith(prefix):
            try:
                return float(line.removeprefix(prefix).strip().removesuffix("%"))
            except ValueError:
                return None
    return None


def supervise(
    command: Sequence[str],
    output: Path,
    *,
    seconds: float,
    memory_bytes: int = 8 * 1024**3,
    global_deadline: float | None = None,
    checkpoint_callback: Callable[[Path, float], None] | None = None,
    env: Mapping[str, str] | None = None,
    system_memory_pressure_seconds: float | None = None,
) -> dict[str, Any]:
    """Enforce civil/awake deadlines and RSS for an isolated process tree."""
    import psutil

    output.mkdir(parents=True, exist_ok=True)
    started, civil = time.monotonic(), time.time()
    deadline = min(civil + seconds, global_deadline or float("inf"))
    peak, cpu, threads = 0, {}, 0
    minimum_available = None
    minimum_pressure_free_percent = None
    initial_swap = psutil.swap_memory().used
    peak_swap = initial_swap
    critical_since = None
    next_pressure_sample = 0.0
    reason, last_checkpoint = None, None
    with (output / "process.log").open("w") as stream:
        process = subprocess.Popen(
            command, stdout=stream, stderr=subprocess.STDOUT,
            start_new_session=True, env=env,
        )
        while process.poll() is None:
            checkpoint = output / "best.json"
            if checkpoint_callback and checkpoint.is_file():
                stamp = checkpoint.stat().st_mtime_ns
                if stamp != last_checkpoint:
                    try:
                        checkpoint_callback(checkpoint, time.monotonic() - started)
                    except Exception as exc:  # noqa: BLE001
                        reason = "INVALID_CHECKPOINT"
                        _atomic_json(
                            output / "validation_error.json",
                            {"error": f"{type(exc).__name__}: {exc}"},
                        )
                    last_checkpoint = stamp
            try:
                parent = psutil.Process(process.pid)
                tree = [parent, *parent.children(recursive=True)]
                rss, thread_count = 0, 0
                for item in tree:
                    try:
                        rss += item.memory_info().rss
                        times = item.cpu_times()
                        cpu[item.pid] = times.user + times.system
                        thread_count += item.num_threads()
                    except psutil.Error:
                        pass
                peak, threads = max(peak, rss), max(threads, thread_count)
                if rss > memory_bytes:
                    reason = "MEMORY_LIMIT"
            except psutil.Error:
                pass
            elapsed = time.monotonic() - started
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory().used
            peak_swap = max(peak_swap, swap)
            minimum_available = memory.available if minimum_available is None else min(minimum_available, memory.available)
            if system_memory_pressure_seconds is not None and elapsed >= next_pressure_sample:
                pressure_free = _macos_memory_free_percent()
                next_pressure_sample = elapsed + 1.0
                if pressure_free is not None:
                    minimum_pressure_free_percent = pressure_free if minimum_pressure_free_percent is None else min(minimum_pressure_free_percent, pressure_free)
                critical = ((pressure_free is not None and pressure_free <= 5.0)
                            or memory.available <= max(512 * 1024**2, int(memory.total * 0.02)))
                if critical:
                    critical_since = critical_since or elapsed
                    if elapsed - critical_since >= system_memory_pressure_seconds:
                        reason = "SYSTEM_MEMORY_PRESSURE"
                else:
                    critical_since = None
            if time.time() - civil - elapsed > 5:
                reason = "SUSPEND_DETECTED"
            if time.time() >= deadline or elapsed >= seconds:
                reason = reason or "WALL_DEADLINE"
            if reason:
                _signal_owned_process_tree(process, signal.SIGTERM)
                try:
                    process.wait(timeout=min(1, max(0.01, deadline - time.time())))
                except subprocess.TimeoutExpired:
                    _signal_owned_process_tree(process, signal.SIGKILL)
                break
            time.sleep(min(0.1, max(0.001, deadline - time.time())))
        process.wait()
    metrics = {
        "exit_code": process.returncode,
        "supervisor_reason": reason,
        "civil_wall_seconds": time.time() - civil,
        "awake_wall_seconds": time.monotonic() - started,
        "peak_process_tree_rss_bytes": peak,
        "sampled_process_tree_cpu_seconds": sum(cpu.values()),
        "peak_sampled_thread_count": threads,
        "minimum_system_available_bytes": minimum_available,
        "minimum_macos_memory_free_percent": minimum_pressure_free_percent,
        "initial_swap_used_bytes": initial_swap,
        "peak_swap_used_bytes": peak_swap,
        "final_swap_used_bytes": psutil.swap_memory().used,
        "system_memory_pressure_grace_seconds": system_memory_pressure_seconds,
    }
    _atomic_json(output / "supervisor.json", metrics)
    return metrics
