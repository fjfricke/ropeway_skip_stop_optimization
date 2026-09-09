"""Explicit sequential execution of the approved follow-up jobs.

No scheduling or daemon: this process waits for every requested job, writes
exit metadata, and stops on failure. Every solver gets a fresh child process.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "benchmarks/output/solver_followup_20260909"
EXAMPLE = "five_station_circle_cw_half_skip_no_wait_headway_b_v0"


def run(name, command, *, log_only=False):
    folder = OUTPUT / name
    if log_only:
        log_folder = OUTPUT / "job_logs" / name
        log_folder.mkdir(parents=True, exist_ok=False)
    else:
        folder.mkdir(parents=True, exist_ok=False)
        log_folder = folder
    argv = ["/usr/bin/caffeinate", "-i", sys.executable, *command]
    metadata = dict(
        argv=argv,
        git_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        started_utc=datetime.now(timezone.utc).isoformat(),
    )
    started = perf_counter()
    with (log_folder / "terminal.log").open("w") as log:
        child = subprocess.Popen(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        metadata["pid"] = child.pid
        (log_folder / "launch.json").write_text(json.dumps(metadata, indent=2))
        print(f"START {name}: PID {child.pid}", flush=True)
        status = child.wait()
    (log_folder / "process_exit.json").write_text(
        json.dumps(
            dict(
                exit_code=status,
                wall_seconds=perf_counter() - started,
                finished_utc=datetime.now(timezone.utc).isoformat(),
            ),
            indent=2,
        )
    )
    print(f"END {name}: exit {status}, {perf_counter() - started:.1f}s", flush=True)
    if status:
        raise SystemExit(f"{name} failed; inspect {log_folder}/terminal.log")


def cp(name, k, seed, hint):
    folder = OUTPUT / name
    run(
        name,
        [
            "benchmarks/run_ddd_fixed_k_cp_sat.py",
            "--example",
            EXAMPLE,
            "--cabins",
            str(k),
            "--maximum-wait-seconds",
            "1200",
            "--waiting-step-seconds",
            "0.000001",
            "--time-limit",
            "600",
            "--num-workers",
            "8",
            "--seed",
            str(seed),
            "--cost-encoding",
            "product",
            "--resume-checkpoint",
            str(OUTPUT / "frozen" / hint / "cp_seed.json"),
            "--log-search-progress",
            "--output-dir",
            str(folder),
        ],
    )
    run(
        f"post_ip_{name}",
        ["benchmarks/prepare_solver_followup.py", "polish", "--run-dir", str(folder)],
        log_only=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["cp_repeats", "k38", "matrix", "anonymous"])
    args = parser.parse_args()
    if args.phase == "cp_repeats":
        for seed in (1, 2):
            cp(f"k39_waiting_600s_seed{seed}", 39, seed, "k39_waiting")
    elif args.phase == "k38":
        cp("k38_waiting_600s_seed0", 38, 0, "k38_all_stop_in_waiting")
    elif args.phase == "matrix":
        for family in ("diffuse", "local", "express"):
            for timing in ("batch", "distributed"):
                for mode in ("all_stop", "skip_stop"):
                    name = f"matrix/{family}_{timing}/{mode}"
                    run(
                        name,
                        [
                            "benchmarks/run_ring_demand_case.py",
                            "--family",
                            family,
                            "--timing",
                            timing,
                            "--mode",
                            mode,
                            "--time-limit",
                            "120",
                            "--output-dir",
                            str(OUTPUT / name),
                        ],
                        log_only=True,
                    )
    else:
        run(
            "k39_anonymous_1800s_seed0",
            ["benchmarks/run_solver_followup_anonymous.py"],
            log_only=True,
        )


if __name__ == "__main__":
    main()
