#!/usr/bin/env python3
"""Refine every validated feasible candidate from completed OIP screenings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)

BENCHMARKS = Path(__file__).resolve().parent
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))

from run_oip_pattern_screening import (
    _publish_campaign_frontend,
    _publish_run_frontend,
    _refinement_result_fields,
)

ROOT = BENCHMARKS.parent
DEFAULT_FRONTEND_ROOT = ROOT / "frontend" / "public" / "generated" / "optimization"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_candidates(source_campaigns: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load immutable sources and retain every independently evaluated feasible trial."""
    sources: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for campaign_path in sorted(path.resolve() for path in source_campaigns):
        if not campaign_path.is_file():
            raise ValueError(f"source campaign does not exist: {campaign_path}")
        campaign = json.loads(campaign_path.read_text())
        if campaign.get("status") != "complete":
            raise ValueError(f"source campaign is not complete: {campaign_path}")
        source = {
            "campaign_id": campaign["campaign_id"],
            "path": str(campaign_path),
            "sha256": _sha256(campaign_path),
            "contract_id": campaign.get("contract_id"),
            "demand_family": campaign["demand_family"],
            "demand_total": campaign["demand_total"],
            "eligible_count": 0,
        }
        for trial in campaign.get("trials", []):
            attempts = trial.get("attempts") or []
            if (
                trial.get("movement_status") != "feasible"
                or trial.get("served") is None
                or not attempts
                or attempts[-1].get("status") != "complete"
            ):
                continue
            source_attempt = campaign_path.parent / attempts[-1]["directory"]
            for required in ("result.json", "detail.json", "movement_certificate.json"):
                if not (source_attempt / required).is_file():
                    raise ValueError(
                        f"eligible source lacks {required}: {source_attempt}"
                    )
            key = campaign["campaign_id"], trial["trial_id"]
            if key in seen:
                raise ValueError(f"duplicate source candidate: {key}")
            seen.add(key)
            source["eligible_count"] += 1
            candidates.append(
                {
                    "refinement_id": f"{campaign['campaign_id']}__{trial['trial_id']}",
                    "stage": "joint_refinement",
                    "source_campaign_id": campaign["campaign_id"],
                    "source_campaign_sha256": source["sha256"],
                    "source_trial_id": trial["trial_id"],
                    "source_attempt_directory": str(source_attempt),
                    "source_result_sha256": _sha256(source_attempt / "result.json"),
                    "source_served": trial["served"],
                    "source_unserved": trial.get("unserved"),
                    "source_journey_time_seconds": trial.get("journey_time_seconds"),
                    "demand_family": campaign["demand_family"],
                    "demand_total": campaign["demand_total"],
                    "policy_id": trial["policy_id"],
                    "allocation_id": trial["allocation_id"],
                    "allocation_label": trial["allocation_label"],
                    "available_fleet_count": trial["available_fleet_count"],
                    "pattern_identity": trial["pattern_identity"],
                    "pattern_composition": trial["pattern_composition"],
                    "patterns_by_cabin_id": trial["patterns_by_cabin_id"],
                    "status": "planned",
                    "attempts": [],
                    "events": [],
                }
            )
        sources.append(source)
    candidates.sort(
        key=lambda item: (
            item["available_fleet_count"],
            item["demand_total"],
            item["demand_family"],
            item["allocation_id"],
        )
    )
    return sources, candidates


def freeze_campaign(args: argparse.Namespace) -> dict[str, Any]:
    sources, candidates = collect_candidates(args.source_campaigns)
    identity = {
        "sources": sources,
        "refinement_time_limit_seconds": args.refinement_time_limit_seconds,
        "seed": args.seed,
        "workers": args.workers,
        "memory_limit_gib": args.memory_limit_gib,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    now = _now()
    return {
        "schema_version": 1,
        "campaign_id": args.output.resolve().name,
        "campaign_kind": "oip_pattern_refinement_followup",
        "label": "OIP fixed-pattern warm-start refinements · 300 s",
        "status": "prepared",
        "contract_id": sources[0].get("contract_id") if sources else None,
        "study_membership": "current_thesis",
        "objective": "lexicographic_unserved_then_journey_time",
        "method": "oip_fixed_pattern_joint_cp_sat",
        "formulation": "optimized_initial_placement",
        "operating_mode": "no_wait",
        "configuration_fingerprint": fingerprint,
        "frozen_identity": identity,
        "source_campaigns": sources,
        "trial_count": 0,
        "completed_trial_count": 0,
        "trials": [],
        "refinement_count": len(candidates),
        "completed_refinement_count": 0,
        "refinements": candidates,
        "k_values": sorted({item["available_fleet_count"] for item in candidates}),
        "allocation_order": sorted({item["allocation_id"] for item in candidates}),
        "demand_family": "F0/F2/F3",
        "demand_total": None,
        "sequence": 0,
        "resume_count": 0,
        "execution_started_unix": None,
        "deadline_unix": None,
        "created_at_utc": now,
        "updated_at_utc": now,
    }


def main() -> None:
    args = parse_args()
    output = args.output.resolve()
    frontend_root = args.frontend_root.resolve() if args.frontend_root else None
    frozen = freeze_campaign(args)
    campaign_path = output / "campaign.json"
    if output.exists() and not args.resume and any(output.iterdir()):
        raise ValueError(f"output directory already contains a campaign: {output}")
    output.mkdir(parents=True, exist_ok=True)
    if args.resume:
        if not campaign_path.is_file():
            raise ValueError("--resume requires an existing campaign.json")
        manifest = json.loads(campaign_path.read_text())
        if manifest.get("configuration_fingerprint") != frozen["configuration_fingerprint"]:
            raise ValueError("follow-up sources or configuration changed")
        manifest["resume_count"] = int(manifest.get("resume_count", 0)) + 1
        manifest["status"] = "running"
    else:
        manifest = frozen

    def save() -> None:
        manifest["updated_at_utc"] = _now()
        manifest["sequence"] = int(manifest.get("sequence", 0)) + 1
        manifest["completed_refinement_count"] = sum(
            item["status"] == "complete" for item in manifest["refinements"]
        )
        atomic_json(campaign_path, manifest)
        if frontend_root is not None:
            _publish_campaign_frontend(frontend_root, manifest)

    if args.build_only:
        save()
        print(f"Prepared {manifest['refinement_count']} refinements in {campaign_path}")
        return

    started = time.time()
    if manifest.get("execution_started_unix") is None:
        manifest["execution_started_unix"] = started
        manifest["deadline_unix"] = started + args.wall_limit_seconds
    deadline = float(manifest["deadline_unix"])
    manifest["status"] = "running"
    save()

    for refinement in manifest["refinements"]:
        if refinement["status"] == "complete":
            continue
        if time.time() + 2 >= deadline:
            refinement["status"] = "not_started_deadline"
            save()
            continue
        source_dir = Path(refinement["source_attempt_directory"])
        if _sha256(source_dir / "result.json") != refinement["source_result_sha256"]:
            raise ValueError(f"source result changed: {source_dir}")
        attempt_index = len(refinement["attempts"]) + 1
        attempt_dir = output / "refinements" / refinement["refinement_id"] / f"attempt_{attempt_index}"
        attempt_dir.mkdir(parents=True, exist_ok=False)
        run_campaign_id = f"{manifest['campaign_id']}__{refinement['refinement_id']}__a{attempt_index}"
        command = [
            sys.executable,
            str(ROOT / "benchmarks" / "run_oip.py"),
            "--thesis-f2-pilot",
            "--demand-family", refinement["demand_family"],
            "--demand-total", str(refinement["demand_total"]),
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
            # The native 300-s limit is followed by extraction, independent
            # validation and atomic publication. Keep the process guard out of
            # that valid completion path while retaining a hard outer bound.
            seconds=args.refinement_time_limit_seconds + 120,
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
            refinement.update(_refinement_result_fields(result, detail, run_campaign_id))
            refinement["status"] = "complete"
            if frontend_root is not None:
                _publish_run_frontend(
                    frontend_root, attempt_dir, run_campaign_id, refinement, manifest
                )
        else:
            attempt["status"] = "interrupted"
            refinement["status"] = "interrupted"
            refinement["termination"] = guard.get("supervisor_reason") or "worker_failure"
        save()

    unfinished = [item for item in manifest["refinements"] if item["status"] != "complete"]
    manifest["status"] = "complete" if not unfinished else "partial"
    manifest["finished_at_utc"] = _now()
    manifest["wall_seconds"] = time.time() - started
    save()
    print(
        f"OIP refinement follow-up {manifest['status']}: "
        f"{manifest['completed_refinement_count']}/{manifest['refinement_count']} complete"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-campaigns", nargs="+", type=Path, required=True)
    parser.add_argument("--refinement-time-limit-seconds", type=float, default=300)
    parser.add_argument("--wall-limit-seconds", type=float, default=15_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frontend-root", type=Path, default=DEFAULT_FRONTEND_ROOT)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.refinement_time_limit_seconds <= 0:
        parser.error("refinement time limit must be positive")
    if args.wall_limit_seconds <= 0:
        parser.error("wall limit must be positive")
    if args.workers <= 0:
        parser.error("workers must be positive")
    if not 0 < args.memory_limit_gib <= 32:
        parser.error("memory limit must lie in (0, 32] GiB")
    if args.build_only and args.resume:
        parser.error("--build-only and --resume are mutually exclusive")
    return args


if __name__ == "__main__":
    main()
