#!/usr/bin/env python3
"""Run the frozen short-horizon OIP cabin-type thesis campaign."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ropeway_skip_stop_optimization.benchmarking.frontend_results import (
    atomic_json,
    update_campaign_index,
)
from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT / "frontend" / "public" / "generated" / "optimization"
LOAD_B = {"f0": 10_764, "f2": 3_210, "f3": 7_869}
CATALOG = {"f0": "all_stop_alternating", "f2": "all_stop_bd_ce", "f3": "all_stop_alternating"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _trials() -> list[dict[str, Any]]:
    result = []
    for family in ("f2", "f3", "f0"):
        trial_id = f"{family}_b_k62"
        result.append({
            "trial_id": trial_id,
            "policy_id": trial_id,
            "family": family,
            "load": "B",
            "demand_total": LOAD_B[family],
            "available_fleet_count": 62,
            "type_catalog": CATALOG[family],
            "status": "planned",
            "reference_status": "planned",
            "attempts": [],
            "events": [],
        })
    return result


def _new_manifest(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "campaign_id": args.output.resolve().name,
        "campaign_kind": "oip_type_catalog",
        "label": "OIP joint cabin-type optimization · No-Wait",
        "status": "prepared" if args.build_only else "running",
        "objective": "lexicographic_unserved_then_journey_time",
        "method": "joint_oip_cp_sat_cabin_types",
        "formulation": "common_1ms_oip",
        "operating_mode": "skip_stop",
        "study_membership": "current_thesis",
        "sequence": 0,
        "trial_count": 3,
        "completed_trial_count": 0,
        "demand_family": "f0_f2_f3",
        "k_values": [62],
        "load_contract": {family: {"B": demand} for family, demand in LOAD_B.items()},
        "configuration": {
            "reference_time_limit_seconds": args.reference_time_limit_seconds,
            "trial_time_limit_seconds": args.trial_time_limit_seconds,
            "workers": args.workers,
            "seed": args.seed,
            "memory_limit_gib": args.memory_limit_gib,
            "maximum_wait_seconds": 0,
            "ticks_per_second": 1_000,
            "waiting_campaign_prepared": False,
        },
        "trials": _trials(),
        "created_at_utc": _now(),
        "updated_at_utc": _now(),
    }


def _save(output: Path, frontend: Path | None, manifest: dict[str, Any]) -> None:
    manifest["sequence"] += 1
    manifest["updated_at_utc"] = _now()
    manifest["completed_trial_count"] = sum(t["status"] == "complete" for t in manifest["trials"])
    atomic_json(output / "campaign.json", manifest)
    if frontend is not None:
        target = frontend / manifest["campaign_id"]
        atomic_json(target / "snapshot.json", manifest)
        update_campaign_index(frontend, manifest)


def _command(trial: dict[str, Any], output: Path, *, reference: bool, args: argparse.Namespace) -> list[str]:
    if reference:
        return [
            sys.executable,
            str(ROOT / "benchmarks" / "run_oip_regular_all_stop_reference.py"),
            "--family", trial["family"], "--demand-total", str(trial["demand_total"]),
            "--fixed-k", str(trial["available_fleet_count"]),
            "--time-limit", str(args.reference_time_limit_seconds),
            "--memory-limit-gib", str(args.memory_limit_gib),
            "--output", str(output),
        ]
    command = [
        sys.executable, str(ROOT / "benchmarks" / "run_oip.py"),
        "--thesis-f2-pilot", "--demand-family", trial["family"],
        "--demand-total", str(trial["demand_total"]),
        "--fixed-k", str(trial["available_fleet_count"]),
        "--backend", "cp_sat", "--passenger-encoding", "od_inventory",
        "--maximum-wait-seconds", "0", "--workers", str(args.workers),
        "--memory-limit-gib", str(args.memory_limit_gib), "--seed", str(args.seed),
        "--output", str(output),
    ]
    reference_dir = args.output.resolve() / "references" / trial["trial_id"]
    command += [
        "--operation", "skip_stop", "--type-catalog", trial["type_catalog"],
        "--time-limit", str(args.trial_time_limit_seconds),
        "--start-checkpoint", str(reference_dir),
        "--all-stop-reference", str(reference_dir),
    ]
    return command


def _publish_run(frontend: Path, source: Path, campaign_id: str) -> None:
    target = frontend / campaign_id
    if target.is_symlink():
        target.unlink()
    target.mkdir(parents=True, exist_ok=True)
    for name in ("detail.json", "snapshot.json", "manifest.json", "result.json", "movement_certificate.json"):
        if (source / name).is_file():
            shutil.copy2(source / name, target / name)
    if (target / "snapshot.json").is_file():
        snapshot = json.loads((target / "snapshot.json").read_text())
        snapshot["campaign_id"] = campaign_id
        snapshot["label"] = campaign_id.replace("_", " ")
        atomic_json(target / "snapshot.json", snapshot)
        update_campaign_index(frontend, snapshot)


def _expose_live_run(frontend: Path, source: Path, campaign_id: str) -> None:
    """Prepare a real public directory for files written by a running child."""
    target = frontend / campaign_id
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        target.unlink()
    target.mkdir(parents=True, exist_ok=True)
    _copy_live_run_files(source, target)


def _copy_live_run_files(source: Path, target: Path) -> None:
    for name in ("detail.json", "snapshot.json", "manifest.json", "result.json", "movement_certificate.json"):
        source_path = source / name
        if not source_path.is_file():
            continue
        temporary = target / f".{name}.tmp"
        shutil.copy2(source_path, temporary)
        temporary.replace(target / name)


def _mirror_live_run(source: Path, target: Path, stop: threading.Event) -> None:
    while not stop.wait(1.0):
        _copy_live_run_files(source, target)
    _copy_live_run_files(source, target)


def _run_one(command: list[str], directory: Path, seconds: float, args: argparse.Namespace) -> dict[str, Any]:
    return supervise(
        command, directory, seconds=seconds + 10,
        memory_bytes=int(args.memory_limit_gib * 1024**3),
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        system_memory_pressure_seconds=30,
    )


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    frontend = args.frontend_root.resolve() if args.frontend_root else None
    output.mkdir(parents=True, exist_ok=True)
    campaign_path = output / "campaign.json"
    if args.resume:
        if not campaign_path.is_file():
            raise ValueError("--resume requires campaign.json")
        manifest = json.loads(campaign_path.read_text())
        if manifest.get("configuration") != _new_manifest(args)["configuration"]:
            raise ValueError("resume configuration changed")
        manifest["status"] = "running"
    else:
        if campaign_path.exists():
            raise ValueError("campaign already exists; use --resume")
        manifest = _new_manifest(args)
    _save(output, frontend, manifest)
    if args.build_only:
        print(f"Prepared {len(manifest['trials'])} K62/Load-B No-Wait trials")
        return

    for trial in manifest["trials"]:
        reference_dir = output / "references" / trial["trial_id"]
        if trial["reference_status"] != "complete":
            reference_dir.mkdir(parents=True, exist_ok=True)
            trial["reference_status"] = "running"
            trial["status"] = "planned"
            _save(output, frontend, manifest)
            guard = _run_one(_command(trial, reference_dir, reference=True, args=args), reference_dir, args.reference_time_limit_seconds, args)
            result_path = reference_dir / "result.json"
            valid = guard.get("exit_code") == 0 and result_path.is_file()
            if valid:
                payload = json.loads(result_path.read_text())
                valid = payload.get("movement_plan") is not None and payload.get("passenger_plan") is not None
            trial["reference_status"] = "complete" if valid else "blocked"
            trial["reference_supervisor"] = guard
            if not valid:
                trial["status"] = "blocked_missing_all_stop_reference"
                _save(output, frontend, manifest)
                continue
            if frontend is not None:
                _publish_run(frontend, reference_dir, f"{manifest['campaign_id']}__reference__{trial['trial_id']}")
            _save(output, frontend, manifest)
        if trial["status"] == "complete":
            continue
        attempt_no = len(trial["attempts"]) + 1
        attempt_dir = output / "trials" / trial["trial_id"] / f"attempt_{attempt_no}"
        attempt_dir.mkdir(parents=True, exist_ok=False)
        command = _command(trial, attempt_dir, reference=False, args=args)
        run_campaign_id = f"{manifest['campaign_id']}__{trial['trial_id']}__a{attempt_no}"
        attempt = {
            "attempt": attempt_no,
            "status": "running",
            "command": command,
            "directory": str(attempt_dir.relative_to(output)),
            "run_campaign_id": run_campaign_id,
            "started_at_utc": _now(),
        }
        trial["attempts"].append(attempt)
        trial["status"] = "running"
        trial["run_campaign_id"] = run_campaign_id
        mirror_stop: threading.Event | None = None
        mirror_thread: threading.Thread | None = None
        if frontend is not None:
            _expose_live_run(frontend, attempt_dir, run_campaign_id)
            mirror_stop = threading.Event()
            mirror_thread = threading.Thread(
                target=_mirror_live_run,
                args=(attempt_dir, frontend / run_campaign_id, mirror_stop),
                daemon=True,
            )
            mirror_thread.start()
        _save(output, frontend, manifest)
        try:
            guard = _run_one(command, attempt_dir, args.trial_time_limit_seconds, args)
        finally:
            if mirror_stop is not None:
                mirror_stop.set()
            if mirror_thread is not None:
                mirror_thread.join(timeout=5)
        attempt["supervisor"] = guard
        attempt["finished_at_utc"] = _now()
        result_path = attempt_dir / "result.json"
        detail_path = attempt_dir / "detail.json"
        if guard.get("exit_code") == 0 and result_path.is_file() and detail_path.is_file():
            result = json.loads(result_path.read_text())
            detail = json.loads(detail_path.read_text())
            peak_rss_bytes = guard.get("peak_rss_bytes")
            if peak_rss_bytes is not None:
                detail["peak_rss_gb"] = peak_rss_bytes / 1024**3
                atomic_json(detail_path, detail)
            latest = detail.get("latest", {})
            trial.update({
                "status": "complete", "solver_status": result.get("solver_status"),
                "served": latest.get("served"), "unserved": latest.get("unserved"),
                "journey_time_seconds": latest.get("journey_time_seconds"),
                "relative_gap": result.get("gap"), "objective_value": result.get("objective_value"),
                "best_bound": result.get("best_bound"), "type_counts": result.get("type_counts"),
                "build_seconds": result.get("build_seconds"), "solve_seconds": result.get("runtime_seconds"),
                "run_campaign_id": run_campaign_id,
                "native_incumbent_seen": detail.get("native_incumbent_seen"),
                "inherited_start_value": detail.get("inherited_start_value"),
                "peak_rss_gb": detail.get("peak_rss_gb"),
            })
            attempt["status"] = "complete"
            if frontend is not None:
                _publish_run(frontend, attempt_dir, trial["run_campaign_id"])
        else:
            trial["status"] = attempt["status"] = "interrupted"
        _save(output, frontend, manifest)
    manifest["status"] = "complete" if all(t["status"] == "complete" for t in manifest["trials"]) else "partial"
    manifest["finished_at_utc"] = _now()
    _save(output, frontend, manifest)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frontend-root", type=Path, default=FRONTEND_ROOT)
    parser.add_argument("--reference-time-limit-seconds", type=float, default=300)
    parser.add_argument("--trial-time-limit-seconds", type=float, default=1800)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.build_only and args.resume:
        parser.error("--build-only and --resume are mutually exclusive")
    if min(args.reference_time_limit_seconds, args.trial_time_limit_seconds, args.workers, args.memory_limit_gib) <= 0:
        parser.error("budgets, workers, and memory must be positive")
    if args.memory_limit_gib > 32:
        parser.error("memory limit must not exceed 32 GiB")
    return args


if __name__ == "__main__":
    main()
