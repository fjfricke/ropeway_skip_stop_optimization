"""Run one fixed-demand thesis K series with explicit warm-start provenance."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


ROOT = Path(__file__).resolve().parents[1]
SINGLE = ROOT / "benchmarks/run_thesis_experiment.py"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _patterns(result: dict) -> tuple[str, ...]:
    value = (((result.get("run") or {}).get("best") or {}).get("movement") or {}).get("genome") or {}
    patterns = value.get("pattern_ids") or ()
    return tuple(str(item) for item in patterns)


def _resize_patterns(patterns: tuple[str, ...], target: int) -> tuple[str, ...]:
    """Create exact-K parent information; the resulting timetable is re-searched."""
    if not patterns or target <= 0:
        return ()
    if target <= len(patterns):
        return patterns[:target]
    return tuple(patterns[index % len(patterns)] for index in range(target))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--method", choices=("evolution", "labelled_arc_flow"), required=True)
    parser.add_argument("--operating-mode", choices=("all_stop", "skip_stop"), default="skip_stop")
    parser.add_argument("--topology", choices=("t5r", "t6r"), required=True)
    parser.add_argument("--geometry", default="g500")
    parser.add_argument("--demand-family", choices=("f0", "f2", "f3", "f4"), required=True)
    parser.add_argument("--demand-profile", default="p0")
    parser.add_argument("--demand", type=int, required=True)
    parser.add_argument("--k", type=int, action="append", required=True)
    parser.add_argument("--stage-time-limit", type=float, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument("--release-resolution-seconds", type=int, default=30)
    args = parser.parse_args()
    if args.demand <= 0 or args.stage_time_limit <= 0 or any(k <= 0 for k in args.k):
        parser.error("demand, K and stage time must be positive")
    if len(set(args.k)) != len(args.k):
        parser.error("K values must be unique")
    if args.method == "labelled_arc_flow" and args.topology != "t5r":
        parser.error("the frozen Journey matrix currently contains only T5R")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema": "thesis_fixed_k_series_v1",
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "method": args.method,
        "operatingMode": args.operating_mode,
        "topology": args.topology,
        "geometry": args.geometry,
        "demandFamily": args.demand_family,
        "demandProfile": args.demand_profile,
        "demand": args.demand,
        "seed": args.seed,
        "kValues": args.k,
        "stages": [],
        "status": "running",
        "transferSemantics": (
            "pattern_sequence_parent_only_dispatch_researched_and_revalidated"
            if args.method == "evolution"
            else "no_cross_k_checkpoint_fixed_starts_rebuilt"
        ),
    }
    started = time.monotonic()

    def persist() -> None:
        manifest["cumulativeWallSeconds"] = time.monotonic() - started
        atomic_json(args.output_dir / "campaign.json", manifest)

    persist()
    previous_patterns: tuple[str, ...] = ()
    for index, cabins in enumerate(args.k):
        stage = args.output_dir / f"k{cabins}"
        command = [
            sys.executable, str(SINGLE),
            "--topology", args.topology,
            "--geometry", args.geometry,
            "--demand-family", args.demand_family,
            "--demand-profile", args.demand_profile,
            "--objective", "unserved" if args.method == "evolution" else "journey_time",
            "--demand", str(args.demand),
            "--method", args.method,
            "--operating-mode", args.operating_mode,
            "--cabins", str(cabins),
            "--time-limit", str(args.stage_time_limit),
            "--workers", str(args.workers),
            "--memory-limit-gib", str(args.memory_limit_gib),
            "--seed", str(args.seed),
            "--release-resolution-seconds", str(args.release_resolution_seconds),
            "--output-dir", str(stage),
        ]
        transfer = ()
        if args.method == "evolution":
            command.extend((
                "--catalog", "od_endpoints_v1",
                "--population-size", "32",
                "--offspring-size", "8",
            ))
            transfer = _resize_patterns(previous_patterns, cabins)
            if transfer:
                transfer_path = args.output_dir / f"k{cabins}_parent_patterns.json"
                atomic_json(transfer_path, [transfer])
                command.extend(("--initial-pattern-sequences", str(transfer_path)))
        entry = {
            "k": cabins,
            "status": "running",
            "parentK": args.k[index - 1] if transfer and index else None,
            "transferredPatternCount": len(transfer),
            "transferIsValidatedIncumbent": False,
            "stageDir": stage.name,
        }
        manifest["stages"].append(entry)
        persist()
        before = time.monotonic()
        completed = subprocess.run(command, cwd=ROOT, check=False)
        entry["wallSeconds"] = time.monotonic() - before
        entry["cumulativeWallSeconds"] = time.monotonic() - started
        entry["exitCode"] = completed.returncode
        result_path = stage / "result.json"
        if completed.returncode or not result_path.is_file():
            entry["status"] = "failed"
            manifest["status"] = "failed"
            manifest["stopReason"] = "stage_failed"
            persist()
            break
        result = _read(result_path)
        previous_patterns = _patterns(result)
        entry["status"] = "complete"
        native = result.get("run") or {}
        entry["validatedBestAvailable"] = (
            bool(native.get("best"))
            if args.method == "evolution"
            else native.get("independent_validation_status") == "feasible"
        )
        entry["result"] = str(Path(stage.name) / "result.json")
        persist()
    else:
        manifest["status"] = "complete"
        manifest["completedAt"] = datetime.now(timezone.utc).isoformat()
        persist()
    if manifest["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
