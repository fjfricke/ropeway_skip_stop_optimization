#!/usr/bin/env python3
"""Run and publish the frozen OIP fixed-pattern fleet screening."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

import gurobipy
import ortools

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.benchmarking.oip_pattern_screening import (
    OipScreeningDemandFamily,
    demand_fingerprint,
    materialize_pattern_allocation,
    pattern_allocations,
)
from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import (
    prepare_oip_pattern_waiting_pilot,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FRONTEND_ROOT = ROOT / "frontend" / "public" / "generated" / "optimization"
def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    frontend_root = args.frontend_root.resolve() if args.frontend_root else None
    started = time.time()
    deadline = started + args.wall_limit_seconds
    frozen = freeze_campaign(args, started, deadline)

    if output.exists() and not args.resume:
        if any(output.iterdir()):
            raise ValueError(f"output directory already contains a campaign: {output}")
    output.mkdir(parents=True, exist_ok=True)
    campaign_path = output / "campaign.json"
    if args.resume:
        if not campaign_path.is_file():
            raise ValueError("--resume requires an existing campaign.json")
        manifest = json.loads(campaign_path.read_text())
        if manifest.get("configuration_fingerprint") != frozen["configuration_fingerprint"]:
            raise ValueError("resume configuration does not match the frozen campaign")
        manifest["status"] = "running"
        manifest["resume_count"] = int(manifest.get("resume_count", 0)) + 1
        manifest["deadline_unix"] = deadline
    else:
        manifest = frozen

    def save() -> None:
        manifest["updated_at_utc"] = _now()
        manifest["sequence"] = int(manifest.get("sequence", 0)) + 1
        manifest["completed_trial_count"] = sum(
            trial["status"] == "complete" for trial in manifest["trials"]
        )
        manifest["completed_refinement_count"] = sum(
            trial["status"] == "complete"
            for trial in manifest.get("refinements", [])
        )
        atomic_json(campaign_path, manifest)
        if frontend_root is not None:
            _publish_campaign_frontend(frontend_root, manifest)

    if args.build_only:
        manifest["status"] = "prepared"
        save()
        print(f"Prepared {len(manifest['trials'])} trials in {campaign_path}")
        return

    manifest["status"] = "running"
    save()
    for trial in manifest["trials"]:
        if trial["status"] == "complete":
            continue
        if time.time() + 2 >= deadline:
            trial["status"] = "not_started_deadline"
            save()
            continue
        attempt_index = len(trial["attempts"]) + 1
        attempt_dir = output / "trials" / trial["trial_id"] / f"attempt_{attempt_index}"
        attempt_dir.mkdir(parents=True, exist_ok=False)
        run_campaign_id = (
            f"{manifest['campaign_id']}__{trial['allocation_id']}__"
            f"k{trial['available_fleet_count']}__a{attempt_index}"
        )
        command = [
            sys.executable,
            str(ROOT / "benchmarks" / "run_oip.py"),
            "--thesis-f2-pilot",
            "--demand-family", manifest["configuration"]["family"],
            "--demand-total", str(manifest["configuration"]["demand_total"]),
            "--backend", "cp_sat",
            "--movement-only",
            "--fixed-k", str(trial["available_fleet_count"]),
            "--pattern-mix", trial["allocation_id"],
            "--maximum-wait-seconds", "0",
            "--time-limit", str(args.trial_time_limit_seconds),
            "--passenger-evaluation-time-limit",
            str(args.passenger_evaluation_time_limit_seconds),
            "--workers", str(args.workers),
            "--memory-limit-gib", str(args.memory_limit_gib),
            "--seed", str(args.seed),
            "--output", str(attempt_dir),
        ]
        attempt = {
            "attempt_index": attempt_index,
            "status": "running",
            "started_at_utc": _now(),
            "run_campaign_id": run_campaign_id,
            "directory": str(attempt_dir.relative_to(output)),
            "command": command,
        }
        trial["attempts"].append(attempt)
        trial["status"] = "running"
        save()
        guard = supervise(
            command,
            attempt_dir,
            seconds=(
                args.trial_time_limit_seconds
                + args.passenger_evaluation_time_limit_seconds
                + 5
            ),
            memory_bytes=int(args.memory_limit_gib * 1024**3),
            global_deadline=deadline,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            system_memory_pressure_seconds=30,
        )
        attempt["supervisor"] = guard
        attempt["finished_at_utc"] = _now()
        result_path = attempt_dir / "result.json"
        detail_path = attempt_dir / "detail.json"
        if result_path.is_file() and detail_path.is_file() and guard["exit_code"] == 0:
            result = json.loads(result_path.read_text())
            detail = json.loads(detail_path.read_text())
            attempt["status"] = "complete"
            attempt["movement_status"] = result.get("status")
            attempt["passenger_status"] = (
                result.get("passenger_evaluation") or {}
            ).get("status")
            trial.update(_trial_result_fields(result, detail, run_campaign_id))
            trial["status"] = "complete"
            if frontend_root is not None:
                _publish_run_frontend(
                    frontend_root, attempt_dir, run_campaign_id, trial
                )
        else:
            attempt["status"] = "interrupted"
            trial["status"] = "interrupted"
            trial["termination"] = guard.get("supervisor_reason") or "worker_failure"
        save()

    if not args.screening_only and all(
        trial["status"] == "complete" for trial in manifest["trials"]
    ):
        if not manifest.get("refinements"):
            manifest["refinements"] = _select_refinements(
                manifest,
                candidates_per_k=args.refinement_candidates_per_k,
            )
            manifest["refinement_count"] = len(manifest["refinements"])
            save()
        for refinement in manifest["refinements"]:
            if refinement["status"] == "complete":
                continue
            if time.time() + 2 >= deadline:
                refinement["status"] = "not_started_deadline"
                save()
                continue
            attempt_index = len(refinement["attempts"]) + 1
            attempt_dir = (
                output / "refinements" / refinement["refinement_id"]
                / f"attempt_{attempt_index}"
            )
            attempt_dir.mkdir(parents=True, exist_ok=False)
            source_dir = output / refinement["source_attempt_directory"]
            run_campaign_id = (
                f"{manifest['campaign_id']}__refine__"
                f"{refinement['allocation_id']}__k{refinement['available_fleet_count']}"
                f"__a{attempt_index}"
            )
            command = [
                sys.executable,
                str(ROOT / "benchmarks" / "run_oip.py"),
                "--thesis-f2-pilot",
                "--demand-family", manifest["configuration"]["family"],
                "--demand-total", str(manifest["configuration"]["demand_total"]),
                "--backend", "cp_sat",
                "--fixed-k", str(refinement["available_fleet_count"]),
                "--pattern-mix", refinement["allocation_id"],
                "--maximum-wait-seconds", "0",
                "--time-limit", str(args.refinement_time_limit_seconds),
                "--workers", str(args.workers),
                "--memory-limit-gib", str(args.memory_limit_gib),
                "--seed", str(args.seed),
                "--start-checkpoint", str(source_dir),
                "--output", str(attempt_dir),
            ]
            attempt = {
                "attempt_index": attempt_index,
                "status": "running",
                "started_at_utc": _now(),
                "run_campaign_id": run_campaign_id,
                "directory": str(attempt_dir.relative_to(output)),
                "command": command,
            }
            refinement["attempts"].append(attempt)
            refinement["status"] = "running"
            save()
            guard = supervise(
                command,
                attempt_dir,
                seconds=args.refinement_time_limit_seconds + 5,
                memory_bytes=int(args.memory_limit_gib * 1024**3),
                global_deadline=deadline,
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                system_memory_pressure_seconds=30,
            )
            attempt["supervisor"] = guard
            attempt["finished_at_utc"] = _now()
            result_path = attempt_dir / "result.json"
            detail_path = attempt_dir / "detail.json"
            if result_path.is_file() and detail_path.is_file() and guard["exit_code"] == 0:
                result = json.loads(result_path.read_text())
                detail = json.loads(detail_path.read_text())
                attempt["status"] = "complete"
                refinement.update(
                    _refinement_result_fields(result, detail, run_campaign_id)
                )
                refinement["status"] = "complete"
                if frontend_root is not None:
                    _publish_run_frontend(
                        frontend_root, attempt_dir, run_campaign_id, refinement
                    )
            else:
                attempt["status"] = "interrupted"
                refinement["status"] = "interrupted"
                refinement["termination"] = (
                    guard.get("supervisor_reason") or "worker_failure"
                )
            save()

    unfinished = [trial for trial in manifest["trials"] if trial["status"] != "complete"]
    unfinished.extend(
        trial
        for trial in manifest.get("refinements", [])
        if trial["status"] != "complete"
    )
    manifest["status"] = "complete" if not unfinished else "partial"
    manifest["finished_at_utc"] = _now()
    manifest["wall_seconds"] = time.time() - started
    save()
    print(
        f"OIP pattern screening {manifest['status']}: "
        f"{manifest['completed_trial_count']}/{manifest['trial_count']} screenings, "
        f"{manifest.get('completed_refinement_count', 0)}/"
        f"{manifest.get('refinement_count', 0)} refinements"
    )


def freeze_campaign(args, started: float, deadline: float) -> dict[str, Any]:
    family_catalog = pattern_allocations(
        args.family, ("S0", "S1", "S2", "S3", "S4")
    )
    requested_allocations = tuple(dict.fromkeys(
        args.allocations or tuple(item.id for item in family_catalog)
    ))
    requested_k = tuple(sorted(set(args.k_values)))
    prepared_by_k = {
        cabin_count: prepare_oip_pattern_waiting_pilot(
            maximum_wait_seconds=0,
            cabin_count=cabin_count,
            demand_total=args.demand_total,
            ticks_per_second=1_000,
            demand_family=args.family.value,
        )
        for cabin_count in requested_k
    }
    fingerprints = {
        demand_fingerprint(
            prepared.domain.scenario,
            horizon_seconds=prepared.passenger_horizon_seconds,
            operation_seconds=prepared.operation_seconds,
        )
        for prepared in prepared_by_k.values()
    }
    if len(fingerprints) != 1:
        raise ValueError("demand or operating windows vary across K")
    first = prepared_by_k[requested_k[0]]
    station_ids = tuple(
        dict.fromkeys(timing.station_id for timing in first.domain.artifact.timings)
    )
    catalog = {
        item.id: item for item in pattern_allocations(args.family, station_ids)
    }
    unknown = set(requested_allocations) - set(catalog)
    if unknown:
        raise ValueError(f"unknown pattern allocations: {sorted(unknown)!r}")
    trials = []
    seen: set[tuple[int, str]] = set()
    for cabin_count in requested_k:
        domain = prepared_by_k[cabin_count].domain
        for allocation_id in requested_allocations:
            allocation = materialize_pattern_allocation(
                catalog[allocation_id], cabin_count, station_ids
            )
            duplicate_key = cabin_count, allocation.identity
            if duplicate_key in seen:
                continue
            seen.add(duplicate_key)
            trials.append(
                {
                    "trial_id": f"{allocation_id}__k{cabin_count}",
                    "policy_id": allocation_id,
                    "allocation_id": allocation_id,
                    "allocation_label": allocation.label,
                    "available_fleet_count": cabin_count,
                    "pattern_identity": allocation.identity,
                    "pattern_composition": allocation.composition,
                    "patterns_by_cabin_id": allocation.patterns_by_cabin_id,
                    "domain_fingerprint": domain.fingerprint,
                    "comparison_fingerprint": domain.comparison_fingerprint,
                    "demand_fingerprint": next(iter(fingerprints)),
                    "status": "planned",
                    "attempts": [],
                    "events": [],
                }
            )
    source_revision = _git_revision()
    configuration = {
        "family": args.family.value,
        "allocations": requested_allocations,
        "k_values": requested_k,
        "trial_time_limit_seconds": args.trial_time_limit_seconds,
        "passenger_evaluation_time_limit_seconds": args.passenger_evaluation_time_limit_seconds,
        "refinement_candidates_per_k": args.refinement_candidates_per_k,
        "refinement_time_limit_seconds": args.refinement_time_limit_seconds,
        "screening_only": args.screening_only,
        "wall_limit_seconds": args.wall_limit_seconds,
        "seed": args.seed,
        "workers": args.workers,
        "memory_limit_gib": args.memory_limit_gib,
        "demand_total": args.demand_total,
        "maximum_wait_seconds": 0,
    }
    configuration_fingerprint = hashlib.sha256(
        json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "campaign_id": args.output.resolve().name,
        "campaign_kind": "oip_pattern_screening",
        "label": f"{args.family.value.upper()} fixed-pattern fleet screening",
        "objective": "validated service and journey time by K",
        "method": "oip_fixed_pattern_cp_sat",
        "formulation": "common_1ms_oip",
        "operating_mode": "skip_stop_no_wait",
        "status": "prepared",
        "started_unix": started,
        "deadline_unix": deadline,
        "started_at_utc": _now(),
        "updated_at_utc": _now(),
        "sequence": 0,
        "configuration": configuration,
        "configuration_fingerprint": configuration_fingerprint,
        "demand_fingerprint": next(iter(fingerprints)),
        "demand_family": args.family.value,
        "demand_total": args.demand_total,
        "passenger_horizon_seconds": first.passenger_horizon_seconds,
        "operation_seconds": first.operation_seconds,
        "cycle_seconds": first.cycle_seconds,
        "source_revision": source_revision,
        "versions": {
            "python": sys.version.split()[0],
            "ortools": ortools.__version__,
            "gurobi": ".".join(map(str, gurobipy.gurobi.version())),
        },
        "allocation_order": requested_allocations,
        "k_values": requested_k,
        "trial_count": len(trials),
        "completed_trial_count": 0,
        "trials": trials,
        "refinement_count": 0,
        "completed_refinement_count": 0,
        "refinements": [],
        "resume_count": 0,
    }


def _select_refinements(
    manifest: dict[str, Any], *, candidates_per_k: int
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for cabin_count in manifest["k_values"]:
        candidates = [
            trial
            for trial in manifest["trials"]
            if trial["available_fleet_count"] == cabin_count
            and trial.get("served") is not None
            and trial.get("attempts")
            and trial["attempts"][-1].get("status") == "complete"
        ]
        candidates.sort(
            key=lambda trial: (
                -int(trial["served"]),
                float(trial.get("journey_time_seconds") or float("inf")),
                manifest["allocation_order"].index(trial["allocation_id"]),
            )
        )
        for rank, source in enumerate(candidates[:candidates_per_k], start=1):
            source_attempt = source["attempts"][-1]
            selected.append(
                {
                    "refinement_id": (
                        f"k{cabin_count}__rank{rank}__{source['allocation_id']}"
                    ),
                    "stage": "joint_refinement",
                    "rank_within_k": rank,
                    "source_trial_id": source["trial_id"],
                    "source_attempt_directory": source_attempt["directory"],
                    "source_served": source["served"],
                    "source_unserved": source.get("unserved"),
                    "source_journey_time_seconds": source.get(
                        "journey_time_seconds"
                    ),
                    "policy_id": source["policy_id"],
                    "allocation_id": source["allocation_id"],
                    "allocation_label": source["allocation_label"],
                    "available_fleet_count": cabin_count,
                    "pattern_identity": source["pattern_identity"],
                    "pattern_composition": source["pattern_composition"],
                    "patterns_by_cabin_id": source["patterns_by_cabin_id"],
                    "status": "planned",
                    "attempts": [],
                    "events": [],
                }
            )
    return selected


def _trial_result_fields(
    result: dict[str, Any], detail: dict[str, Any], run_campaign_id: str
) -> dict[str, Any]:
    passenger = result.get("passenger_evaluation") or {}
    return {
        "movement_status": result.get("status", "unknown"),
        "solver_status": result.get("solver_status"),
        "passenger_status": passenger.get("status"),
        "served": passenger.get("served_passengers"),
        "unserved": passenger.get("unserved_passengers"),
        "journey_time_seconds": passenger.get("journey_time_seconds"),
        "build_seconds": detail.get("build_seconds"),
        "solve_seconds": detail.get("search_seconds"),
        "passenger_build_seconds": passenger.get("build_seconds"),
        "passenger_solve_seconds": passenger.get("runtime_seconds"),
        "peak_rss_gb": detail.get("peak_rss_gb"),
        "model_stats": detail.get("model_stats"),
        "run_campaign_id": run_campaign_id,
        "termination": detail.get("termination"),
    }


def _refinement_result_fields(
    result: dict[str, Any], detail: dict[str, Any], run_campaign_id: str
) -> dict[str, Any]:
    return {
        "movement_status": result.get("status", "unknown"),
        "solver_status": result.get("solver_status"),
        "passenger_status": result.get("status"),
        "served": result.get("served_passengers"),
        "unserved": result.get("unserved_passengers"),
        "journey_time_seconds": result.get("journey_time_seconds"),
        "objective_value": result.get("objective_value"),
        "best_bound": result.get("best_bound"),
        "relative_gap": result.get("gap"),
        "build_seconds": detail.get("build_seconds"),
        "solve_seconds": detail.get("search_seconds"),
        "peak_rss_gb": detail.get("peak_rss_gb"),
        "model_stats": detail.get("model_stats"),
        "run_campaign_id": run_campaign_id,
        "termination": detail.get("termination"),
    }


def _publish_campaign_frontend(frontend_root: Path, manifest: dict[str, Any]) -> None:
    frontend_root.mkdir(parents=True, exist_ok=True)
    campaign_dir = frontend_root / manifest["campaign_id"]
    snapshot = {
        key: manifest.get(key)
        for key in (
            "schema_version", "campaign_id", "campaign_kind", "label", "status",
            "objective", "method", "formulation", "operating_mode", "sequence",
            "updated_at_utc", "trial_count", "completed_trial_count", "demand_total",
            "demand_family", "passenger_horizon_seconds", "operation_seconds", "allocation_order",
            "k_values", "trials", "refinement_count",
            "completed_refinement_count", "refinements",
        )
    }
    atomic_json(campaign_dir / "snapshot.json", snapshot)
    _update_frontend_index(frontend_root, snapshot)


def _publish_run_frontend(
    frontend_root: Path,
    attempt_dir: Path,
    run_campaign_id: str,
    trial: dict[str, Any],
) -> None:
    target = frontend_root / run_campaign_id
    target.mkdir(parents=True, exist_ok=True)
    for name in ("detail.json", "movement_certificate.json", "result.json", "manifest.json"):
        source = attempt_dir / name
        if source.is_file():
            shutil.copy2(source, target / name)
    source_snapshot = json.loads((attempt_dir / "snapshot.json").read_text())
    source_snapshot.update(
        campaign_id=run_campaign_id,
        label=(
            f"{trial['allocation_label']} · K={trial['available_fleet_count']}"
        ),
        status="complete",
        completed_trial_count=1,
    )
    atomic_json(target / "snapshot.json", source_snapshot)
    _update_frontend_index(frontend_root, source_snapshot)


def _update_frontend_index(frontend_root: Path, snapshot: dict[str, Any]) -> None:
    index_path = frontend_root / "index.json"
    payload = json.loads(index_path.read_text()) if index_path.exists() else {
        "schema_version": 1,
        "campaigns": [],
    }
    summary_keys = (
        "campaign_id", "campaign_kind", "label", "status", "objective", "method",
        "operating_mode", "formulation", "sequence", "trial_count",
        "completed_trial_count", "updated_at_utc",
    )
    summary = {key: snapshot.get(key) for key in summary_keys}
    campaigns = [
        item for item in payload.get("campaigns", [])
        if item.get("campaign_id") != snapshot["campaign_id"]
    ]
    campaigns.append(summary)
    campaigns.sort(key=lambda item: str(item.get("campaign_id")))
    payload["campaigns"] = campaigns
    atomic_json(index_path, payload)


def _git_revision() -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
        check=False,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True,
            text=True, check=False,
        ).stdout.strip()
    )
    return {"commit": commit or None, "dirty": dirty}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", type=OipScreeningDemandFamily, choices=tuple(OipScreeningDemandFamily), default=OipScreeningDemandFamily.F2)
    parser.add_argument("--allocations", nargs="+", default=None)
    parser.add_argument("--k-values", nargs="+", type=int, default=(40, 50, 62))
    parser.add_argument("--trial-time-limit-seconds", type=float, default=60)
    parser.add_argument("--passenger-evaluation-time-limit-seconds", type=float, default=30)
    parser.add_argument("--refinement-candidates-per-k", type=int, default=2)
    parser.add_argument("--refinement-time-limit-seconds", type=float, default=180)
    parser.add_argument("--screening-only", action="store_true")
    parser.add_argument("--demand-total", type=int, default=3_210)
    parser.add_argument("--wall-limit-seconds", type=float, default=3600)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frontend-root", type=Path, default=DEFAULT_FRONTEND_ROOT)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if any(value <= 0 for value in args.k_values):
        parser.error("all K values must be positive")
    if args.wall_limit_seconds > 3600:
        parser.error("the frozen two-stage campaign is capped at 60 minutes")
    if args.demand_total <= 0:
        parser.error("demand total must be positive")
    if not 1 <= args.refinement_candidates_per_k <= 3:
        parser.error("refinement candidates per K must lie in [1, 3]")
    if args.refinement_time_limit_seconds <= 0:
        parser.error("refinement time limit must be positive")
    if not 0 < args.memory_limit_gib <= 32:
        parser.error("memory limit must lie in (0, 32] GiB")
    if args.build_only and args.resume:
        parser.error("--build-only and --resume are mutually exclusive")
    return args


if __name__ == "__main__":
    main()
