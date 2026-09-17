"""Run the bounded two-hour calibration for the versioned thesis pipeline."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import psutil

from ropeway_skip_stop_optimization.benchmarking.thesis_all_stop_capacity import (
    AllStopCapacitySearchConfig,
    search_fixed_k_all_stop_capacity,
)
from ropeway_skip_stop_optimization.benchmarking.thesis_cases import (
    ExperimentCaseSpec,
    ThesisDemandFamily,
    ThesisDemandProfile,
    ThesisGeometry,
    ThesisObjective,
    ThesisTopology,
    core_thesis_experiment_groups,
    geometric_fleet_caps,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


ROOT = Path(__file__).resolve().parents[1]
SINGLE = ROOT / "benchmarks/run_thesis_experiment.py"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--wall-limit-seconds", type=float, default=7200)
    p.add_argument("--memory-limit-gib", type=float, default=32)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--dry-run", action="store_true")
    return p


def main() -> None:
    args = parser().parse_args()
    if not 0 < args.wall_limit_seconds <= 7200:
        raise ValueError("calibration wall limit must lie in (0, 7200] seconds")
    if not 0 < args.memory_limit_gib <= 32:
        raise ValueError("memory limit must lie in (0, 32] GiB")
    if args.workers <= 0:
        raise ValueError("workers must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    started_civil, started_awake = time.time(), time.monotonic()
    deadline = started_civil + args.wall_limit_seconds
    manifest = {
        "schema": "thesis_calibration_campaign_v1",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "wall_limit_seconds": args.wall_limit_seconds,
        "memory_limit_gib": args.memory_limit_gib,
        "workers": args.workers,
        "core_experiment_groups": [asdict(group) for group in core_thesis_experiment_groups()],
        "runs": [],
        "resolution_assessment": {},
        "journey_demand_calibration": None,
        "complete": False,
    }

    def persist():
        manifest["civil_elapsed_seconds"] = time.time() - started_civil
        manifest["awake_elapsed_seconds"] = time.monotonic() - started_awake
        atomic_json(args.output_dir / "campaign.json", manifest)

    def enough_time(seconds: float) -> bool:
        suspended = (time.time() - started_civil) - (time.monotonic() - started_awake) > 5
        return not suspended and time.time() + seconds <= deadline

    def run_job(name: str, seconds: int, flags: list[str]) -> dict | None:
        if not enough_time(seconds):
            manifest["stop_reason"] = "GLOBAL_DEADLINE_OR_SUSPEND"
            persist()
            return None
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        snapshot = {
            "available_bytes": memory.available,
            "used_percent": memory.percent,
            "swap_used_bytes": swap.used,
        }
        out = args.output_dir / name
        command = [
            sys.executable,
            str(SINGLE),
            *flags,
            "--time-limit", str(seconds),
            "--workers", str(args.workers),
            "--memory-limit-gib", str(args.memory_limit_gib),
            "--output-dir", str(out),
        ]
        entry = {
            "name": name,
            "budget_seconds": seconds,
            "command": command,
            "pre_run_memory": snapshot,
            "status": "PLANNED" if args.dry_run else "RUNNING",
        }
        manifest["runs"].append(entry)
        persist()
        if args.dry_run:
            return entry
        before = time.time()
        completed = subprocess.run(command, cwd=ROOT, check=False)
        entry["actual_wall_seconds"] = time.time() - before
        entry["exit_code"] = completed.returncode
        result_path = out / "result.json"
        supervisor_path = out / "supervisor.json"
        entry["result"] = _read(result_path)
        entry["supervisor"] = _read(supervisor_path)
        entry["status"] = "COMPLETE" if completed.returncode == 0 and entry["result"] else "FAILED"
        persist()
        return entry

    families = (ThesisDemandFamily.F2, ThesisDemandFamily.F0, ThesisDemandFamily.F4)
    capacity_runs = {}
    for family in families:
        for resolution in (30, 15):
            name = f"resolution_{family.value}_r{resolution}"
            entry = run_job(
                name,
                120,
                [
                    "--topology", "t5r", "--geometry", "g800",
                    "--demand-family", family.value, "--demand-profile", "p0",
                    "--objective", "unserved", "--demand", "12000",
                    "--release-resolution-seconds", str(resolution),
                    "--method", "all_stop_phase", "--capacity-search",
                    "--capacity-initial-demand", "1000",
                ],
            )
            if entry is None:
                return
            capacity_runs[family.value, resolution] = entry

    if args.dry_run:
        # Dynamic follow-ups depend on the capacity probes; record their exact
        # nominal count and stop without inventing demands.
        manifest["dynamic_plan"] = {
            "line_screening": "2 formulations x 3 demand levels x 180 s",
            "arc_flow_screening": "3 K values x 180 s",
            "line_confirmation": "2 seeds x 900 s",
            "arc_flow_confirmation": "2 seeds x 900 s",
        }
        manifest["complete"] = True
        persist()
        return

    selected_capacity = {}
    for family in families:
        r30 = _capacity_summary(capacity_runs[family.value, 30])
        r15 = _capacity_summary(capacity_runs[family.value, 15])
        deviation = None
        if r30["capacity"] is not None and r15["capacity"] is not None:
            deviation = abs(r30["capacity"] - r15["capacity"]) / max(1, r15["capacity"])
        accepted = deviation is not None and deviation <= 0.01
        r5 = None
        fine_deviation = None
        if deviation is not None and deviation > 0.01:
            entry = run_job(
                f"resolution_{family.value}_r5",
                120,
                [
                    "--topology", "t5r", "--geometry", "g800",
                    "--demand-family", family.value, "--demand-profile", "p0",
                    "--objective", "unserved", "--demand", "12000",
                    "--release-resolution-seconds", "5",
                    "--method", "all_stop_phase", "--capacity-search",
                    "--capacity-initial-demand", "1000",
                ],
            )
            if entry is None:
                return
            r5 = _capacity_summary(entry)
            if r15["capacity"] is not None and r5["capacity"] is not None:
                fine_deviation = abs(r15["capacity"] - r5["capacity"]) / max(1, r5["capacity"])
        chosen_resolution = 30 if accepted else 15
        chosen = r30 if accepted else r15
        if r5 is not None and (fine_deviation is None or fine_deviation > 0.01):
            chosen_resolution, chosen = 5, r5
        manifest["resolution_assessment"][family.value] = {
            "r30": r30,
            "r15": r15,
            "r5": r5,
            "relative_capacity_deviation": deviation,
            "relative_fine_capacity_deviation": fine_deviation,
            "r30_accepted": accepted,
            "selected_resolution_seconds": chosen_resolution,
            "statement_open": deviation is None,
        }
        selected_capacity[family.value] = chosen
    persist()

    f2 = selected_capacity["f2"]
    kappa = f2["capacity"] or f2["proven_feasible_demand"]
    if not kappa:
        manifest["stop_reason"] = "NO_VALIDATED_F2_ALL_STOP_CAPACITY_LOWER_BOUND"
        persist()
        return
    manifest["line_demand_basis"] = {
        "value": kappa,
        "kind": "exact_capacity" if f2["capacity"] is not None else "proven_feasible_lower_bound",
    }
    resolution = manifest["resolution_assessment"]["f2"]["selected_resolution_seconds"]
    line_demand = math.ceil(1.1 * kappa)
    fleet_caps = geometric_fleet_caps(
        f2["all_stop_reference_cabins"], f2["physical_dispatch_bound"]
    )[:3]
    manifest["line_screening"] = {
        "demand": line_demand,
        "fleet_caps": fleet_caps,
        "all_five_fleet_caps": geometric_fleet_caps(
            f2["all_stop_reference_cabins"], f2["physical_dispatch_bound"]
        ),
    }
    line_entries = []
    for fleet_cap in fleet_caps:
        for formulation in ("shared_rounds", "shared_rides"):
            entry = run_job(
                f"line_{formulation}_k{fleet_cap}_n{line_demand}",
                180,
                [
                    "--topology", "t5r", "--geometry", "g800",
                    "--demand-family", "f2", "--demand-profile", "p0",
                    "--objective", "unserved", "--demand", str(line_demand),
                    "--release-resolution-seconds", str(resolution),
                    "--method", "line_planning", "--formulation", formulation,
                    "--catalog", "relevant", "--max-cabins", str(fleet_cap),
                    "--seed", "0",
                ],
            )
            if entry is None:
                return
            line_entries.append(entry)

    journey_spec = ExperimentCaseSpec(
        ThesisTopology.T5R,
        ThesisGeometry.G300,
        ThesisDemandFamily.F3,
        ThesisDemandProfile.P0,
        ThesisObjective.JOURNEY_TIME,
        200,
        30,
    )
    if enough_time(120):
        journey_capacity = search_fixed_k_all_stop_capacity(
            journey_spec,
            AllStopCapacitySearchConfig(
                maximum_demand=200,
                initial_demand=50,
                time_limit_seconds=min(120, deadline - time.time()),
                workers=args.workers,
            ),
            cabins=1,
        )
        manifest["journey_demand_calibration"] = journey_capacity
        persist()
    else:
        return
    k1_capacity = journey_capacity["capacity"] or journey_capacity["proven_feasible_demand"]
    journey_demand = max(1, math.floor(0.5 * k1_capacity))
    arc_entries = []
    for cabins in (1, 5, 20):
        entry = run_job(
            f"arc_k{cabins}",
            180,
            [
                "--topology", "t5r", "--geometry", "g300",
                "--demand-family", "f3", "--demand-profile", "p0",
                "--objective", "journey_time", "--demand", str(journey_demand),
                "--method", "labelled_arc_flow", "--operating-mode", "skip_stop",
                "--cabins", str(cabins), "--seed", "0",
            ],
        )
        if entry is None:
            return
        arc_entries.append(entry)

    best_formulation = min(
        ("shared_rounds", "shared_rides"),
        key=lambda formulation: _line_rank(line_entries, formulation, fleet_caps[-1]),
    )
    manifest["selected_line_formulation"] = best_formulation
    for seed in (1, 2):
        if run_job(
            f"line_confirm_{best_formulation}_seed{seed}",
            900,
            [
                "--topology", "t5r", "--geometry", "g800",
                "--demand-family", "f2", "--demand-profile", "p0",
                "--objective", "unserved", "--demand", str(line_demand),
                "--release-resolution-seconds", str(resolution),
                "--method", "line_planning", "--formulation", best_formulation,
                "--catalog", "relevant", "--max-cabins", str(fleet_caps[-1]),
                "--seed", str(seed),
            ],
        ) is None:
            return

    # K20 is deliberately the scaling case, irrespective of which small K has
    # the best objective. The confirmation asks whether useful progress
    # continues on the difficult model.
    manifest["selected_arc_cabins"] = 20
    for seed in (1, 2):
        if run_job(
            f"arc_confirm_k20_seed{seed}",
            900,
            [
                "--topology", "t5r", "--geometry", "g300",
                "--demand-family", "f3", "--demand-profile", "p0",
                "--objective", "journey_time", "--demand", str(journey_demand),
                "--method", "labelled_arc_flow", "--operating-mode", "skip_stop",
                "--cabins", "20", "--seed", str(seed),
            ],
        ) is None:
            return

    manifest["complete"] = True
    manifest["stop_reason"] = "COMPLETED_PLANNED_CALIBRATION"
    persist()
    _write_report(args.output_dir, manifest)


def _read(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _capacity_summary(entry):
    run = (entry.get("result") or {}).get("run") or {}
    case = (entry.get("result") or {}).get("case") or {}
    return {
        "capacity": run.get("capacity"),
        "capacity_proven": run.get("capacity_proven", False),
        "proven_feasible_demand": run.get("proven_feasible_demand", 0),
        "proven_infeasible_demand": run.get("proven_infeasible_demand"),
        "all_stop_reference_cabins": case.get("all_stop_reference_cabins"),
        "physical_dispatch_bound": case.get("physical_dispatch_bound"),
    }


def _line_rank(entries, formulation, fleet_cap):
    candidate = next(
        (entry for entry in entries if formulation in entry["name"] and f"k{fleet_cap}_" in entry["name"]),
        None,
    )
    run = ((candidate or {}).get("result") or {}).get("run") or {}
    selected = run.get("selected_stage")
    metrics = run.get("timed_metrics") if selected == "timing" else run.get("no_wait_metrics")
    if metrics is None:
        metrics = (run.get("construction") or {}).get("physical_plan_metrics")
    unserved = math.inf if metrics is None else metrics.get("unserved", math.inf)
    construction = run.get("construction") or {}
    bound = construction.get("line_domain_unserved_lower_bound")
    return (unserved, -(bound if bound is not None else -math.inf), candidate["actual_wall_seconds"])


def _write_report(output: Path, manifest: dict) -> None:
    lines = [
        "# Thesis calibration result",
        "",
        f"Completed: `{manifest['complete']}`; stop: `{manifest.get('stop_reason')}`.",
        f"Actual wall time: {manifest['civil_elapsed_seconds']:.1f} s.",
        "",
        "## Demand resolution",
        "",
        "| Family | kappa 30 s | kappa 15 s | deviation | selected |",
        "|---|---:|---:|---:|---:|",
    ]
    for family, item in manifest["resolution_assessment"].items():
        deviation = item["relative_capacity_deviation"]
        lines.append(
            f"| {family.upper()} | {item['r30']['capacity']} | {item['r15']['capacity']} | "
            f"{'open' if deviation is None else f'{100 * deviation:.3f}%'} | {item['selected_resolution_seconds']} s |"
        )
    lines.extend(
        (
            "",
            "## Formulation selections",
            "",
            f"Line formulation selected for confirmation: `{manifest.get('selected_line_formulation')}`.",
            f"Arc-Flow scaling confirmation: `K={manifest.get('selected_arc_cabins')}`.",
            "",
            "Every raw run, event stream, checkpoint, source identity, model size, and supervisor record is stored in its run directory.",
        )
    )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
