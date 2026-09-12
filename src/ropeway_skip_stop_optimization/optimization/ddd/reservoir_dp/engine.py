"""Build and supervise the pinned native RPID engine."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
from pathlib import Path

import psutil

from .config import ReservoirDpConfig, ReservoirDpSearchMode, ReservoirDpVariant
from .preparation import PreparedReservoirDp


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _crate() -> Path:
    return _repo_root() / "native" / "ropeway_reservoir_dp"


def _binary() -> Path:
    return _crate() / "target" / "release" / "ropeway-reservoir-dp"


def _build_engine() -> tuple[Path, float]:
    started = time.perf_counter()
    result = subprocess.run(
        ["cargo", "build", "--release", "--locked"],
        cwd=_crate(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            "failed to build reservoir DP engine:\n"
            + (result.stderr or result.stdout)[-4000:]
        )
    return _binary(), time.perf_counter() - started


def native_source_hash() -> str:
    crate = _crate()
    digest = hashlib.sha256()
    files = [crate / "Cargo.toml", crate / "Cargo.lock", *sorted((crate / "src").glob("*.rs"))]
    for path in files:
        digest.update(path.relative_to(crate).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _rss(process: psutil.Process) -> int:
    result = 0
    for member in (process, *process.children(recursive=True)):
        try:
            result += member.memory_info().rss
        except psutil.Error:
            pass
    return result


def _terminate(process: subprocess.Popen) -> None:
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
    except psutil.Error:
        children = []
    for member in reversed(children):
        try:
            member.terminate()
        except psutil.Error:
            pass
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        for member in reversed(children):
            try:
                member.kill()
            except psutil.Error:
                pass
        process.kill()
        process.wait()


def run_native_engine(
    prepared: PreparedReservoirDp, config: ReservoirDpConfig
) -> dict:
    config.validate()
    variant = ReservoirDpVariant(config.variant)
    search_mode = ReservoirDpSearchMode(config.search_mode)
    binary, build_seconds = _build_engine()
    with tempfile.TemporaryDirectory(prefix="ropeway-reservoir-dp-") as directory:
        directory = Path(directory)
        input_path, output_path = directory / "input.json", directory / "output.json"
        input_path.write_text(prepared.json)
        command = [
            str(binary),
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--time-limit",
            str(config.time_limit_seconds),
            "--workers",
            str(config.workers),
            "--initial-beam-width",
            str(config.initial_beam_width),
            "--max-beam-width",
            str(config.max_beam_width),
            "--keep-all-layers",
            str(config.keep_all_layers).lower(),
            "--variant",
            str(variant),
            "--search-mode",
            str(search_mode),
        ]
        started = time.perf_counter()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        monitor = psutil.Process(process.pid)
        peak_rss = 0
        termination = None
        wall_limit = config.time_limit_seconds + 5
        memory_limit = int(config.memory_limit_gib * 1024**3)
        while process.poll() is None:
            peak_rss = max(peak_rss, _rss(monitor))
            elapsed = time.perf_counter() - started
            if peak_rss > memory_limit:
                termination = "memory_limit"
                _terminate(process)
                break
            if elapsed > wall_limit:
                termination = "supervisor_deadline"
                _terminate(process)
                break
            time.sleep(0.05)
        stdout, stderr = process.communicate()
        wall_seconds = time.perf_counter() - started
        if termination:
            return {
                "schema": "reservoir_symbolic_dp_result_v1",
                "status": termination,
                "has_valid_plan": False,
                "build_seconds": build_seconds,
                "wall_seconds": wall_seconds,
                "peak_rss_bytes": peak_rss,
                "stdout": stdout[-2000:],
                "stderr": stderr[-2000:],
            }
        if process.returncode or not output_path.exists():
            raise RuntimeError(
                f"reservoir DP engine failed ({process.returncode}):\n"
                + (stderr or stdout)[-4000:]
            )
        result = json.loads(output_path.read_text())
        if (
            result.get("schema") != "reservoir_symbolic_dp_result_v1"
            or result.get("source_fingerprint")
            != prepared.payload["source_fingerprint"]
        ):
            raise ValueError("native reservoir DP result fingerprint mismatch")
        result.update(
            build_seconds=build_seconds,
            wall_seconds=wall_seconds,
            peak_rss_bytes=peak_rss,
            stdout=stdout[-2000:],
            stderr=stderr[-2000:],
            native_source_hash=native_source_hash(),
        )
        return result
