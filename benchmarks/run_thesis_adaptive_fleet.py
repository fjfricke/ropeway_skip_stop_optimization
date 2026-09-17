"""Run a progressive fleet-cap line campaign with validated warm starts."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.thesis_adaptive_fleet import (
    AdaptiveFleetPolicy,
)
from ropeway_skip_stop_optimization.benchmarking.thesis_cases import (
    ExperimentCaseSpec,
    ThesisDemandFamily,
    ThesisDemandProfile,
    ThesisGeometry,
    ThesisObjective,
    ThesisTopology,
    prepare_experiment_case,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    read_reservoir_cp_checkpoint_for_fleet_resize,
    reservoir_cp_plan_from_payload,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)


ROOT = Path(__file__).resolve().parents[1]
SINGLE = ROOT / "benchmarks/run_thesis_experiment.py"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--output-dir", type=Path, required=True)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--initial-checkpoint", type=Path)
    source.add_argument("--initial-result", type=Path)
    p.add_argument("--demand", type=int, default=2750)
    p.add_argument("--release-resolution-seconds", type=int, default=30)
    p.add_argument("--hard-cap", type=int, default=84)
    p.add_argument("--maximum-stages", type=int, default=3)
    p.add_argument("--stage-time-limit", type=float, default=300)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--memory-limit-gib", type=float, default=32)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--log-search-progress", action="store_true")
    return p


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _metrics(run: dict) -> dict:
    construction = run.get("construction") or {}
    return (
        run.get("no_wait_metrics")
        or construction.get("physical_plan_metrics")
        or construction.get("reference_metrics")
        or {}
    )


def _last_incumbent(run: dict) -> float | None:
    events = (run.get("construction") or {}).get("events") or []
    values = [e.get("elapsed_seconds") for e in events if e.get("kind") == "incumbent"]
    return max((float(v) for v in values if v is not None), default=None)


def main() -> None:
    a = parser().parse_args()
    if a.maximum_stages <= 0 or a.stage_time_limit <= 0:
        raise ValueError("stage count and time limit must be positive")
    if not 0 < a.memory_limit_gib <= 32 or a.workers <= 0:
        raise ValueError("invalid solver resource configuration")
    a.output_dir.mkdir(parents=True, exist_ok=False)
    spec = ExperimentCaseSpec(
        ThesisTopology.T5R,
        ThesisGeometry.G800,
        ThesisDemandFamily.F2,
        ThesisDemandProfile.P0,
        ThesisObjective.UNSERVED,
        a.demand,
        a.release_resolution_seconds,
    )
    base = prepare_experiment_case(spec, fleet_cap=a.hard_cap)
    policy = AdaptiveFleetPolicy(
        base.all_stop_reference_cabins,
        min(a.hard_cap, base.physical_dispatch_bound),
    )
    policy.validate()

    source_raw = _read(a.initial_result) if a.initial_result else None
    if source_raw is not None:
        payload = ((source_raw.get("run") or {}).get("construction") or {}).get("plan")
        if payload is None:
            raise ValueError("initial result contains no construction plan")
        source_plan = reservoir_cp_plan_from_payload(payload)
        # Validate initially against the hard-cap target, then retarget to K0.
        source_metrics = validate_reservoir_cp_plan(base.problem, source_plan)
    else:
        source_plan = read_reservoir_cp_checkpoint_for_fleet_resize(
            a.initial_checkpoint, base.problem
        )
        source_metrics = validate_reservoir_cp_plan(base.problem, source_plan)

    cap = policy.initial_cap(source_metrics.used_fleet)
    initial = prepare_experiment_case(spec, fleet_cap=cap)
    validate_reservoir_cp_plan(initial.problem, source_plan)
    checkpoint = a.output_dir / "initial_seed.json"
    write_reservoir_cp_checkpoint(checkpoint, initial.problem, source_plan)
    manifest = {
        "schema": "thesis_adaptive_fleet_campaign_v1",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "case_spec": asdict(spec),
        "policy": asdict(policy),
        "effective_step": policy.step,
        "solver_settings": {
            "formulation": "shared_rides",
            "catalog": "relevant",
            "workers": a.workers,
            "memory_limit_gib": a.memory_limit_gib,
            "stage_time_limit_seconds": a.stage_time_limit,
            "construction_share": 0.7,
        },
        "initial_metrics": asdict(source_metrics),
        "stages": [],
        "complete": False,
    }
    started = time.monotonic()

    def persist() -> None:
        manifest["elapsed_seconds"] = time.monotonic() - started
        atomic_json(a.output_dir / "campaign.json", manifest)

    persist()
    previous_served = source_metrics.served
    previous_used = source_metrics.used_fleet
    stagnant_caps = 0
    for stage_index in range(a.maximum_stages):
        stage = a.output_dir / f"k{cap}_stage{stage_index + 1}"
        command = [
            sys.executable,
            str(SINGLE),
            "--topology", "t5r",
            "--geometry", "g800",
            "--demand-family", "f2",
            "--demand-profile", "p0",
            "--objective", "unserved",
            "--demand", str(a.demand),
            "--release-resolution-seconds", str(a.release_resolution_seconds),
            "--maximum-wait-seconds", "1200.0",
            "--method", "line_planning",
            "--formulation", "shared_rides",
            "--catalog", "relevant",
            "--max-cabins", str(cap),
            "--time-limit", str(a.stage_time_limit),
            "--workers", str(a.workers),
            "--memory-limit-gib", str(a.memory_limit_gib),
            "--seed", str(a.seed + stage_index),
            "--checkpoint-import", str(checkpoint),
            "--allow-fleet-resize-checkpoint",
            "--output-dir", str(stage),
        ]
        if a.log_search_progress:
            command.append("--log-search-progress")
        entry = {"cap": cap, "command": command, "status": "RUNNING"}
        manifest["stages"].append(entry)
        persist()
        before = time.monotonic()
        completed = subprocess.run(command, cwd=ROOT, check=False)
        entry["wall_seconds"] = time.monotonic() - before
        entry["exit_code"] = completed.returncode
        result_path = stage / "result.json"
        if completed.returncode or not result_path.is_file():
            entry["status"] = "FAILED"
            manifest["stop_reason"] = "STAGE_FAILED"
            persist()
            break
        result = _read(result_path)
        run = result["run"]
        metrics = _metrics(run)
        if not metrics:
            entry["status"] = "FAILED"
            manifest["stop_reason"] = "NO_VALIDATED_CONSTRUCTION_PLAN"
            persist()
            break
        served, used = int(metrics["served"]), int(metrics["used_fleet"])
        last = _last_incumbent(run)
        construction_budget = float(
            run.get("construction_budget_seconds", a.stage_time_limit * 0.7)
        )
        entry.update(
            status="COMPLETE",
            served=served,
            unserved=int(metrics["unserved"]),
            used_fleet=used,
            cap_utilization=used / cap,
            last_incumbent_seconds=last,
            late_progress=(last is not None and last >= 0.75 * construction_budget),
            reference_status=(run.get("construction") or {}).get("reference_status"),
            native_plan_found=(run.get("construction") or {}).get("native_plan_found"),
        )
        improved = served > previous_served or used > previous_used
        stagnant_caps = 0 if improved else stagnant_caps + 1
        entry["improved_over_input"] = improved
        entry["consecutive_stagnant_caps"] = stagnant_caps
        next_checkpoint = stage / "construction_best.json"
        if not next_checkpoint.is_file():
            raise RuntimeError("stage did not export its construction checkpoint")
        checkpoint = next_checkpoint
        previous_served, previous_used = served, used
        if served == a.demand:
            manifest["stop_reason"] = "FULL_SERVICE"
            break
        if stagnant_caps >= 2:
            manifest["stop_reason"] = "PRACTICAL_FLEET_PLATEAU"
            break
        next_cap = policy.next_cap(cap, used)
        entry["next_cap"] = next_cap
        if next_cap == cap:
            manifest["stop_reason"] = "HARD_CAP_REACHED"
            break
        cap = next_cap
        persist()
    else:
        manifest["stop_reason"] = "MAXIMUM_STAGES"
    manifest["complete"] = True
    persist()


if __name__ == "__main__":
    main()
