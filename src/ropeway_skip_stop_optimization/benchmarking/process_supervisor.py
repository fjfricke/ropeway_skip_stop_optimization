"""Solver-neutral process-tree supervision for benchmark campaigns."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import Any


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    temporary.replace(path)


def _signal_owned_process_tree(process: subprocess.Popen[Any], sig: int) -> None:
    """Handle macOS group-signal denial and the exit-at-deadline race."""
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
    if process.poll() is None:
        process.send_signal(sig)


def _owned_processes(group_id: int, known: dict[int, Any]) -> list[Any]:
    """Return live members even after the process-group leader has exited."""
    import psutil

    if hasattr(os, "getpgid"):
        for item in psutil.process_iter(("pid", "status")):
            try:
                if os.getpgid(item.pid) == group_id:
                    known[item.pid] = item
            except (OSError, psutil.Error):
                pass
    live = []
    for pid, item in tuple(known.items()):
        try:
            if item.is_running() and item.status() != psutil.STATUS_ZOMBIE:
                live.append(item)
            else:
                known.pop(pid, None)
        except psutil.Error:
            known.pop(pid, None)
    return live


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
    known_processes: dict[int, Any] = {}
    checkpoint_results: SimpleQueue[BaseException | None] = SimpleQueue()
    checkpoint_thread: threading.Thread | None = None
    with (output / "process.log").open("w") as stream:
        process = subprocess.Popen(
            command, stdout=stream, stderr=subprocess.STDOUT,
            start_new_session=True, env=env,
        )
        while True:
            process.poll()
            live_processes = _owned_processes(process.pid, known_processes)
            if process.returncode is not None and not live_processes:
                break
            if checkpoint_thread is not None and not checkpoint_thread.is_alive():
                try:
                    checkpoint_error = checkpoint_results.get_nowait()
                except Empty:
                    checkpoint_error = RuntimeError("checkpoint validator returned no result")
                checkpoint_thread = None
                if checkpoint_error is not None:
                    reason = "INVALID_CHECKPOINT"
                    _atomic_json(
                        output / "validation_error.json",
                        {"error": f"{type(checkpoint_error).__name__}: {checkpoint_error}"},
                    )
            checkpoint = output / "best.json"
            if checkpoint_callback and checkpoint.is_file() and checkpoint_thread is None:
                stamp = checkpoint.stat().st_mtime_ns
                if stamp != last_checkpoint:
                    elapsed_at_launch = time.monotonic() - started
                    callback = checkpoint_callback

                    def validate_checkpoint(
                        path: Path = checkpoint,
                        elapsed: float = elapsed_at_launch,
                        validator: Callable[[Path, float], None] = callback,
                    ) -> None:
                        try:
                            validator(path, elapsed)
                        except BaseException as exc:  # noqa: BLE001
                            checkpoint_results.put(exc)
                        else:
                            checkpoint_results.put(None)
                    checkpoint_thread = threading.Thread(
                        target=validate_checkpoint,
                        name="checkpoint-validator",
                        daemon=True,
                    )
                    checkpoint_thread.start()
                    last_checkpoint = stamp
            rss, thread_count = 0, 0
            for item in live_processes:
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
                if _owned_processes(process.pid, known_processes):
                    time.sleep(0.05)
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
