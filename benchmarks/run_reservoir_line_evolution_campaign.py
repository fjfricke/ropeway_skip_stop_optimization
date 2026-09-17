"""Run the frozen 60-minute no-wait reservoir line evolution comparison."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

import psutil

from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


ROOT = Path(__file__).resolve().parents[1]
EVOLUTION = ROOT / "benchmarks/run_reservoir_line_evolution.py"
NATIVE = ROOT / "benchmarks/run_reservoir_lines.py"
ALL_STOP_PHASE = ROOT / "benchmarks/run_reservoir_all_stop_phase.py"


def _read(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def _quality(entry: dict) -> tuple[int, float]:
    result = entry.get("result") or {}
    if entry["method"] == "native":
        unserved = result.get("validated_unserved")
        elapsed = result.get("runner_total_wall_seconds", float("inf"))
    else:
        passengers = ((result.get("best") or {}).get("passengers") or {})
        unserved = passengers.get("unserved")
        elapsed = result.get("runner_total_wall_seconds", float("inf"))
    return (10**12 if unserved is None else int(unserved), float(elapsed))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--r0-reference", type=Path, required=True)
    parser.add_argument("--r2-reference", type=Path, required=True)
    parser.add_argument("--r0-all-stop", type=Path, required=True)
    parser.add_argument("--r2-all-stop", type=Path, required=True)
    parser.add_argument("--dispatch-window-end", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wall-limit-seconds", type=float, default=3600)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 0 < args.wall_limit_seconds <= 3600:
        parser.error("--wall-limit-seconds must lie in (0, 3600]")
    if not 0 < args.memory_limit_gib <= 32:
        parser.error("--memory-limit-gib must lie in (0, 32]")
    args.output.mkdir(parents=True, exist_ok=False)
    civil, awake = time.time(), time.monotonic()
    deadline = civil + args.wall_limit_seconds
    cases = {
        "R0": (args.r0_reference.resolve(), args.r0_all_stop.resolve()),
        "R2": (args.r2_reference.resolve(), args.r2_all_stop.resolve()),
    }
    manifest = {
        "schema": "reservoir_line_evolution_campaign_v1",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "wall_limit_seconds": args.wall_limit_seconds,
        "memory_limit_gib": args.memory_limit_gib,
        "workers": args.workers,
        "cases": {key: [str(x) for x in value] for key, value in cases.items()},
        "runs": [],
        "complete": False,
    }

    def persist():
        manifest["civil_elapsed_seconds"] = time.time() - civil
        manifest["awake_elapsed_seconds"] = time.monotonic() - awake
        atomic_json(args.output / "campaign.json", manifest)

    def enough(seconds: float) -> bool:
        suspended = (time.time() - civil) - (time.monotonic() - awake) > 5
        return not suspended and time.time() + seconds + 3 <= deadline

    def run_job(
        name, method, case, seconds, seed=0, profile="mixed_global",
        *, domain_override=None, initial_override=None,
    ):
        if not enough(seconds):
            manifest["stop_reason"] = "GLOBAL_DEADLINE_OR_SUSPEND"
            persist()
            return None
        domain, initial = cases[case]
        domain = domain if domain_override is None else Path(domain_override)
        initial = initial if initial_override is None else Path(initial_override)
        out = args.output / name
        if method == "all_stop_phase":
            artifact = out / "artifact"
            command = [
                sys.executable, str(ALL_STOP_PHASE),
                "--reference-checkpoint", str(domain),
                "--output", str(artifact),
                "--dispatch-window-end", str(args.dispatch_window_end),
                "--time-limit", str(max(1, seconds - 3)),
                "--workers", str(args.workers), "--seed", str(seed),
            ]
        elif method == "native":
            artifact = out / "artifact"
            command = [
                sys.executable, str(NATIVE),
                "--reference-checkpoint", str(domain),
                "--initial-checkpoint", str(initial),
                "--output", str(artifact),
                "--dispatch-window-end", str(args.dispatch_window_end),
                "--variant", "intervals", "--preparation", "encoding_specific",
                "--formulation", "shared_rounds", "--catalog", "relevant",
                "--mode", "exact_service", "--time-limit", str(max(1, seconds - 3)),
                "--workers", str(args.workers), "--memory-limit-gib", str(args.memory_limit_gib),
                "--seed", str(seed),
            ]
        else:
            command = [
                sys.executable, str(EVOLUTION),
                "--reference-checkpoint", str(domain),
                "--initial-checkpoint", str(initial),
                "--output", str(out), "--engine", method,
                "--operator-profile", profile,
                "--dispatch-window-end", str(args.dispatch_window_end),
                "--time-limit", str(seconds), "--passenger-time-limit", "2",
                "--workers", str(args.workers), "--memory-limit-gib", str(args.memory_limit_gib),
                "--seed", str(seed),
            ]
        entry = {
            "name": name, "method": method, "case": case, "profile": profile,
            "seed": seed, "budget_seconds": seconds, "command": command,
            "memory_before": {
                "available_bytes": psutil.virtual_memory().available,
                "swap_used_bytes": psutil.swap_memory().used,
            },
            "status": "PLANNED" if args.dry_run else "RUNNING",
        }
        manifest["runs"].append(entry)
        persist()
        if args.dry_run:
            return entry
        before = time.time()
        if method in ("native", "all_stop_phase"):
            out.mkdir()
            guard = supervise(
                command, out, seconds=seconds,
                memory_bytes=int(args.memory_limit_gib * 1024**3),
                global_deadline=deadline, system_memory_pressure_seconds=30,
            )
            entry["supervisor"] = guard
            result_path = artifact / "result.json"
            exit_code = guard.get("return_code")
        else:
            # Single-run CLIs print complete certificates. Keep those large
            # payloads in the run directory rather than flooding the campaign
            # terminal; result.json remains the canonical machine output.
            with (out.parent / f"{out.name}.log").open("w") as stream:
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    check=False,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                )
            exit_code = completed.returncode
            result_path = out / "result.json"
            entry["supervisor"] = _read(out / "supervisor.json")
        entry["actual_wall_seconds"] = time.time() - before
        entry["exit_code"] = exit_code
        entry["result"] = _read(result_path)
        entry["status"] = "COMPLETE" if entry["result"] else "INCOMPLETE"
        persist()
        return entry

    # Re-prove/re-evaluate each regular all-stop reference under the current
    # lifecycle before it becomes the common initialization for all methods.
    for case in cases:
        all_stop = cases[case][1]
        entry = run_job(
            f"{case}_all_stop_reference", "all_stop_phase", case, 120,
            domain_override=all_stop, initial_override=all_stop,
        )
        if entry is None:
            return
        improved = args.output / f"{case}_all_stop_reference" / "artifact" / "best.json"
        if improved.exists():
            cases[case] = (cases[case][0], improved.resolve())

    screening = []
    specifications = [
        ("ga", "local"), ("ga", "local_block"), ("ga", "mixed_global"),
        ("random", "mixed_global"), ("tpe", "mixed_global"),
        ("native", "mixed_global"),
    ]
    for case in cases:
        for method, profile in specifications:
            entry = run_job(f"screen_{case}_{method}_{profile}", method, case, 120, 0, profile)
            if entry is None:
                return
            screening.append(entry)
    if args.dry_run:
        manifest["confirmation_plan"] = "best GA, best of TPE/random, native; R2 seeds 1 and 2"
        manifest["complete"] = True
        persist()
        return

    r2 = [entry for entry in screening if entry["case"] == "R2"]
    ga = min((x for x in r2 if x["method"] == "ga"), key=_quality)
    control = min((x for x in r2 if x["method"] in ("random", "tpe")), key=_quality)
    manifest["selection"] = {
        "ga_profile": ga["profile"],
        "blackbox_control": control["method"],
        "screening_quality": {x["name"]: _quality(x) for x in r2},
    }
    persist()
    for seed in (1, 2):
        for method, profile in (
            ("ga", ga["profile"]),
            (control["method"], control["profile"]),
            ("native", "mixed_global"),
        ):
            if run_job(f"confirm_R2_{method}_{profile}_s{seed}", method, "R2", 240, seed, profile) is None:
                return
    manifest["complete"] = True
    manifest["completed_utc"] = datetime.now(timezone.utc).isoformat()
    persist()


if __name__ == "__main__":
    main()
