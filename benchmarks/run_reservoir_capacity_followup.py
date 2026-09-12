"""Sequential R2 30-minute comparison, queued behind the original campaign."""

import argparse
import hashlib
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import psutil
from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-campaign", type=Path, required=True)
    parser.add_argument("--after-pid", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--memory-gib", type=float, default=24)
    parser.add_argument("--threads", type=int, default=12)
    a = parser.parse_args()
    if a.memory_gib <= 0 or a.threads < 1:
        raise ValueError("Invalid resource limits")
    out = a.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    previous = a.previous_campaign.resolve()
    atomic_json(out / "status.json", dict(state="queued", after_pid=a.after_pid))
    try:
        parent = psutil.Process(a.after_pid)
        if "run_reservoir_capacity_campaign.py" not in " ".join(parent.cmdline()):
            raise ValueError("Queue predecessor is not the expected campaign")
        children = parent.children(recursive=True)
        while parent.is_running() and parent.status() != psutil.STATUS_ZOMBIE:
            for child in parent.children(recursive=True):
                if child not in children:
                    children.append(child)
            time.sleep(1)
        psutil.wait_procs(children)
    except psutil.NoSuchProcess:
        pass
    if not (previous / "completed.json").exists():
        raise RuntimeError("Previous campaign did not complete cleanly")
    atomic_json(out / "status.json", dict(state="correctness"))
    with (out / "correctness.log").open("w") as log:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_reservoir_capacity_phases.py",
                "tests/test_reservoir_capacity_runner.py",
                "tests/test_reservoir_capacity_additional.py",
                "-q",
            ],
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    sources = out / "sources"
    shutil.copytree(
        ROOT / "src",
        sources / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    (sources / "benchmarks").mkdir()
    for name in ("run_reservoir_capacity_arc_flow.py", Path(__file__).name):
        shutil.copy2(ROOT / "benchmarks" / name, sources / "benchmarks" / name)
    reference = out / "reference.json"
    shutil.copy2(previous / "prepare/R2_ss.json", reference)
    atomic_json(
        out / "source_hashes.json",
        {
            str(p.relative_to(sources)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sources.rglob("*")
            if p.is_file()
        },
    )
    started = time.time()
    deadline = started + 3600
    atomic_json(
        out / "manifest.json",
        dict(
            started_unix=started,
            deadline_unix=deadline,
            seconds_per_run=1800,
            threads=a.threads,
            memory_gib=a.memory_gib,
            gurobi_soft_memory_gb=a.memory_gib * 1024**3 / 1e9,
            seed=0,
            reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
            versions={
                p: importlib.metadata.version(p) for p in ("gurobipy", "ortools")
            },
            schedule=["phase_arc_flow", "cp_sat"],
        ),
    )
    env = dict(os.environ, PYTHONPATH=str(sources / "src"))
    for method in ("phase_arc_flow", "cp_sat"):
        if time.time() >= deadline:
            break
        run = out / method
        run.mkdir()
        atomic_json(out / "status.json", dict(state="running", method=method))
        command = [
            sys.executable,
            str(sources / "benchmarks/run_reservoir_capacity_arc_flow.py"),
            "--_worker",
            "--method",
            method,
            "--reference",
            str(reference),
            "--output-dir",
            str(run),
            "--time-limit",
            "1800",
            "--threads",
            str(a.threads),
            "--memory-gib",
            str(a.memory_gib),
            "--seed",
            "0",
            "--deadline-unix",
            str(deadline),
        ]
        atomic_json(run / "command.json", command)
        supervise(
            command,
            run,
            seconds=1800,
            memory_bytes=int(a.memory_gib * 1024**3),
            global_deadline=deadline,
            env=env,
        )
    atomic_json(
        out / "status.json",
        dict(state="completed", total_seconds=time.time() - started),
    )


if __name__ == "__main__":
    main()
