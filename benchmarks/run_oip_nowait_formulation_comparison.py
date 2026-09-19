#!/usr/bin/env python3
"""Compare general EAN and affine No-Wait OIP formulations at 120% Nmax."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ropeway_skip_stop_optimization.benchmarking.frontend_results import (
    atomic_json,
    update_campaign_index,
)
from ropeway_skip_stop_optimization.benchmarking.thesis_contract import source_digest

BENCHMARKS = Path(__file__).resolve().parent
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))

from run_oip_type_catalog_campaign import (
    _expose_live_run,
    _mirror_live_run,
    _publish_run,
    _run_one,
)

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT / "frontend" / "public" / "generated" / "optimization"
CATALOG = {
    "f0": "all_stop_alternating",
    "f2": "all_stop_bd_ce",
    "f3": "all_stop_alternating",
}
ORDER = (
    ("f2", "ean"), ("f2", "nowait_templates"),
    ("f3", "nowait_templates"), ("f3", "ean"),
    ("f0", "ean"), ("f0", "nowait_templates"),
)


def now() -> str:
    return datetime.now(UTC).isoformat()


def load_calibration(path: Path, families: tuple[str, ...]) -> dict[str, int]:
    payload = json.loads(path.read_text())
    evidence = {item["family"]: item for item in payload.get("evidence", ())}
    missing = [family for family in families
               if not evidence.get(family, {}).get("capacity_proven")]
    if missing:
        raise ValueError(
            "comparison remains blocked until exact calibration is proven for "
            + ", ".join(missing)
        )
    return {family: int(evidence[family]["load_120"]) for family in families}


def new_manifest(args, loads: dict[str, int]) -> dict[str, Any]:
    trials = []
    selected = set(args.families)
    formulations = list(getattr(args, "formulations", ["ean", "nowait_templates"]))
    for family, formulation in ORDER:
        if family not in selected or formulation not in formulations:
            continue
        trial_id = f"{family}_{formulation}_k62"
        trials.append({
            "trial_id": trial_id,
            "policy_id": trial_id,
            "family": family,
            "load": "120% phase Nmax",
            "demand_total": loads[family],
            "available_fleet_count": 62,
            "type_catalog": CATALOG[family],
            "formulation": formulation,
            "objective": "served",
            "status": "planned",
            "attempts": [],
            "events": [],
        })
    return {
        "schema_version": 1,
        "campaign_id": args.output.resolve().name,
        "campaign_kind": "oip_type_catalog",
        "label": ("OIP Served-only · No-Wait templates" if formulations == ["nowait_templates"]
                  else "OIP Served-only · EAN vs No-Wait templates"),
        "status": "prepared",
        "objective": "served",
        "method": "joint_oip_cp_sat_cabin_types",
        "formulation": formulations[0] if len(formulations) == 1 else "ean_vs_nowait_templates",
        "operating_mode": "skip_stop",
        "k_values": [62],
        "families": list(args.families),
        "load_contract": loads,
        "reference_runs": {
            family: {"status": "planned", "demand_total": loads[family]}
            for family in args.families
        },
        "trial_count": len(trials),
        "completed_trial_count": 0,
        "sequence": 0,
        "trials": trials,
        "configuration": {
            "calibration": str(args.calibration.resolve()),
            "formulations": formulations,
            "families": list(args.families),
            "reference_time_limit_seconds": args.reference_time_limit_seconds,
            "trial_time_limit_seconds": args.trial_time_limit_seconds,
            "workers": args.workers,
            "seed": args.seed,
            "memory_limit_gib": args.memory_limit_gib,
            "source_digest": source_digest(ROOT),
        },
        "created_at_utc": now(),
        "updated_at_utc": now(),
    }


def save(output: Path, frontend: Path | None, manifest: dict[str, Any]) -> None:
    manifest["sequence"] += 1
    manifest["updated_at_utc"] = now()
    manifest["completed_trial_count"] = sum(
        item["status"] == "complete" for item in manifest["trials"]
    )
    atomic_json(output / "campaign.json", manifest)
    if frontend is not None:
        target = frontend / manifest["campaign_id"]
        atomic_json(target / "snapshot.json", manifest)
        update_campaign_index(frontend, manifest)


def reference_command(family: str, demand: int, output: Path, args) -> list[str]:
    return [
        sys.executable, str(ROOT / "benchmarks/run_oip_regular_all_stop_reference.py"),
        "--family", family, "--demand-total", str(demand), "--fixed-k", "62",
        "--time-limit", str(args.reference_time_limit_seconds),
        "--memory-limit-gib", str(args.memory_limit_gib), "--output", str(output),
    ]


def trial_command(trial: dict[str, Any], reference: Path, output: Path, args) -> list[str]:
    return [
        sys.executable, str(ROOT / "benchmarks/run_oip.py"),
        "--thesis-f2-pilot", "--demand-family", trial["family"],
        "--demand-total", str(trial["demand_total"]), "--fixed-k", "62",
        "--backend", "cp_sat", "--operation", "skip_stop",
        "--passenger-encoding", "od_inventory", "--maximum-wait-seconds", "0",
        "--type-catalog", trial["type_catalog"],
        "--formulation", trial["formulation"], "--objective", "served",
        "--time-limit", str(args.trial_time_limit_seconds),
        "--workers", str(args.workers), "--seed", str(args.seed),
        "--memory-limit-gib", str(args.memory_limit_gib),
        "--start-checkpoint", str(reference), "--all-stop-reference", str(reference),
        "--output", str(output),
    ]


def main() -> None:
    args = parse_args()
    loads = load_calibration(args.calibration, tuple(args.families))
    output = args.output.resolve()
    frontend = args.frontend_root.resolve() if args.frontend_root else None
    output.mkdir(parents=True, exist_ok=True)
    campaign_path = output / "campaign.json"
    expected = new_manifest(args, loads)
    if args.resume:
        if not campaign_path.is_file():
            raise ValueError("--resume requires campaign.json")
        manifest = json.loads(campaign_path.read_text())
        if manifest.get("configuration") != expected["configuration"]:
            raise ValueError("resume configuration or source changed")
        manifest["status"] = "running"
    else:
        if campaign_path.exists():
            raise ValueError("campaign already exists; use --resume")
        manifest = expected
    save(output, frontend, manifest)
    if args.build_only:
        print(f"Prepared {len(manifest['trials'])} Served-only formulation comparisons")
        return

    manifest["status"] = "running"
    save(output, frontend, manifest)
    references: dict[str, Path] = {}
    for family in args.families:
        directory = output / "references" / family
        references[family] = directory
        result_path = directory / "result.json"
        if result_path.is_file():
            result = json.loads(result_path.read_text())
            if result.get("movement_plan") is not None and result.get("passenger_plan") is not None:
                manifest["reference_runs"][family].update(
                    status="complete", served=result.get("served_passengers"),
                    unserved=result.get("unserved_passengers"),
                )
                save(output, frontend, manifest)
                continue
        directory.mkdir(parents=True, exist_ok=True)
        manifest["reference_runs"][family]["status"] = "running"
        save(output, frontend, manifest)
        guard = _run_one(
            reference_command(family, loads[family], directory, args), directory,
            args.reference_time_limit_seconds, args,
        )
        if guard.get("exit_code") != 0 or not result_path.is_file():
            manifest["reference_runs"][family]["status"] = "failed"
            manifest["status"] = "blocked_missing_all_stop_reference"
            save(output, frontend, manifest)
            return
        result = json.loads(result_path.read_text())
        if result.get("movement_plan") is None or result.get("passenger_plan") is None:
            manifest["reference_runs"][family]["status"] = "failed"
            manifest["status"] = "blocked_missing_all_stop_reference"
            save(output, frontend, manifest)
            return
        manifest["reference_runs"][family].update(
            status="complete", served=result.get("served_passengers"),
            unserved=result.get("unserved_passengers"),
        )
        save(output, frontend, manifest)
        if frontend is not None:
            _publish_run(frontend, directory, f"{manifest['campaign_id']}__reference__{family}")

    for trial in manifest["trials"]:
        if trial["status"] == "complete":
            continue
        attempt_no = len(trial["attempts"]) + 1
        attempt_dir = output / "trials" / trial["trial_id"] / f"attempt_{attempt_no}"
        attempt_dir.mkdir(parents=True, exist_ok=False)
        command = trial_command(trial, references[trial["family"]], attempt_dir, args)
        run_id = f"{manifest['campaign_id']}__{trial['trial_id']}__a{attempt_no}"
        attempt = {
            "attempt": attempt_no, "status": "running", "command": command,
            "directory": str(attempt_dir.relative_to(output)),
            "run_campaign_id": run_id, "started_at_utc": now(),
        }
        trial["attempts"].append(attempt)
        trial["status"] = "running"
        trial["run_campaign_id"] = run_id
        mirror_stop = None
        mirror_thread = None
        if frontend is not None:
            _expose_live_run(frontend, attempt_dir, run_id)
            mirror_stop = threading.Event()
            mirror_thread = threading.Thread(
                target=_mirror_live_run,
                args=(attempt_dir, frontend / run_id, mirror_stop), daemon=True,
            )
            mirror_thread.start()
        save(output, frontend, manifest)
        try:
            guard = _run_one(command, attempt_dir, args.trial_time_limit_seconds, args)
        finally:
            if mirror_stop is not None:
                mirror_stop.set()
            if mirror_thread is not None:
                mirror_thread.join(timeout=5)
        attempt.update(status="complete" if guard.get("exit_code") == 0 else "interrupted",
                       finished_at_utc=now(), supervisor=guard)
        detail_path, result_path = attempt_dir / "detail.json", attempt_dir / "result.json"
        if attempt["status"] == "complete" and detail_path.is_file() and result_path.is_file():
            detail = json.loads(detail_path.read_text())
            result = json.loads(result_path.read_text())
            peak_rss = guard.get("peak_process_tree_rss_bytes")
            if peak_rss is not None:
                detail["peak_rss_gb"] = peak_rss / 1024**3
                atomic_json(detail_path, detail)
            latest = detail.get("latest", {})
            trial.update(
                status="complete", solver_status=result.get("solver_status"),
                served=latest.get("served"), unserved=latest.get("unserved"),
                journey_time_seconds=latest.get("journey_time_seconds"),
                relative_gap=result.get("gap"), objective_value=result.get("objective_value"),
                best_bound=result.get("best_bound"), type_counts=result.get("type_counts"),
                build_seconds=result.get("build_seconds"), solve_seconds=result.get("runtime_seconds"),
                native_incumbent_seen=detail.get("native_incumbent_seen"),
                peak_rss_gb=detail.get("peak_rss_gb"),
            )
            if frontend is not None:
                _publish_run(frontend, attempt_dir, run_id)
        else:
            trial["status"] = "interrupted"
        save(output, frontend, manifest)
    manifest["status"] = (
        "complete" if all(item["status"] == "complete" for item in manifest["trials"])
        else "partial"
    )
    manifest["finished_at_utc"] = now()
    save(output, frontend, manifest)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--calibration", type=Path,
        default=ROOT / "results/oip_exact_phase_short_k62_20260918/references.json",
    )
    parser.add_argument("--frontend-root", type=Path, default=FRONTEND_ROOT)
    parser.add_argument("--reference-time-limit-seconds", type=float, default=300)
    parser.add_argument("--trial-time-limit-seconds", type=float, default=300)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument(
        "--families", nargs="+", choices=("f2", "f3", "f0"),
        default=["f2", "f3", "f0"],
        help="calibrated demand families to compare",
    )
    parser.add_argument("--formulations", nargs="+", choices=("ean", "nowait_templates"),
                        default=["ean", "nowait_templates"])
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.build_only and args.resume:
        parser.error("--build-only and --resume are mutually exclusive")
    if min(args.reference_time_limit_seconds, args.trial_time_limit_seconds,
           args.workers, args.memory_limit_gib) <= 0:
        parser.error("budgets, workers, and memory must be positive")
    if args.memory_limit_gib > 32:
        parser.error("memory limit must not exceed 32 GiB")
    if len(set(args.families)) != len(args.families):
        parser.error("families must not contain duplicates")
    return args


if __name__ == "__main__":
    main()
