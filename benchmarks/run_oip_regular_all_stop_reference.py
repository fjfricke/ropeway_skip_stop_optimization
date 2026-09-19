#!/usr/bin/env python3
"""Build and independently passenger-evaluate a regular OIP all-stop start."""

from __future__ import annotations

import argparse
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.frontend_results import atomic_json
from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import (
    prepare_oip_pattern_waiting_pilot,
)
from types import SimpleNamespace
from ropeway_skip_stop_optimization.optimization.oip.phase_reference import (
    solve_phase_reference,
)
from ropeway_skip_stop_optimization.optimization.oip import (
    OipOperation,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("f0", "f2", "f3"), required=True)
    parser.add_argument("--demand-total", type=int, required=True)
    parser.add_argument("--fixed-k", type=int, choices=(50, 62), required=True)
    parser.add_argument("--time-limit", type=float, default=300)
    parser.add_argument("--deadline-unix", type=float)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    deadline = min(time.time() + args.time_limit, args.deadline_unix or float("inf"))
    prepared = prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0,
        demand_total=args.demand_total,
        cabin_count=args.fixed_k,
        demand_family=args.family,
        operation=OipOperation.ALL_STOP,
    )
    domain = prepared.domain
    remaining = deadline - time.time()
    phase_stats, certificate = solve_phase_reference(
        domain,
        seconds=max(0, remaining - 10),
        require_full_service=False,
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "phase_search.json", phase_stats)
    if certificate is None:
        raise RuntimeError(
            f"no validated common-phase solution: {phase_stats['status']}"
        )
    movement, fleet, passengers = certificate
    seed = SimpleNamespace(movement_plan=movement, fleet_plan=fleet)
    selected_phase_seconds = domain.grid.seconds(phase_stats["phase_tick"])
    # Served only: Journey Time is measured from the validated assignment.
    evaluation = {
        "status": "feasible",
        "solver_status": str(phase_stats["native_status"]),
        "passenger_plan": asdict(passengers),
        "served_passengers": phase_stats["served"],
        "unserved_passengers": phase_stats["unserved"],
        "journey_time_seconds": phase_stats["journey_time_seconds"],
        "runtime_seconds": phase_stats["total_seconds"],
        "best_bound": None,
        "mip_gap": None,
    }
    phase_results = [phase_stats]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stations = tuple(dict.fromkeys(item.station_id for item in domain.artifact.timings))
    manifest = {
        "schema_version": 1,
        "deadline_unix": deadline,
        "completion_reserve_seconds": 10,
        "headway_contract": domain.scenario.experiment_metadata["headway_contract"],
        "reference_kind": "regular_all_stop_exact_common_phase",
        "phase_search": "all_grid_phase_cells",
        "served_optimal_over_phase": phase_stats["native_status"] == 2,
        "domain_fingerprint": domain.fingerprint,
        "comparison_fingerprint": domain.comparison_fingerprint,
        "operation": "all_stop",
        "fixed_k": args.fixed_k,
        "k_max": args.fixed_k,
        "fixed_stop_patterns": [list(stations) for _ in range(args.fixed_k)],
        "type_catalog": None,
        "horizon_seconds": domain.artifact.config.horizon_seconds,
        "operation_seconds": domain.artifact.config.operational_end_seconds,
        "common_phase_seconds": selected_phase_seconds,
        "phase_screen": phase_results,
    }
    result = {
        "validation_status": "valid",
        "served_upper_bound": phase_stats.get("served_upper_bound"),
        "served_optimal_over_phase": phase_stats["native_status"] == 2,
        "status": "feasible"
        if evaluation["passenger_plan"] is not None
        else "movement_only",
        "solver_status": evaluation["solver_status"],
        "movement_plan": asdict(seed.movement_plan),
        "fleet_plan": asdict(seed.fleet_plan),
        "passenger_plan": evaluation["passenger_plan"],
        "passenger_evaluation": evaluation,
        "served_passengers": evaluation["served_passengers"],
        "unserved_passengers": evaluation["unserved_passengers"],
        "journey_time_seconds": evaluation["journey_time_seconds"],
        "type_counts": {"all_stop": args.fixed_k},
        "common_phase_seconds": selected_phase_seconds,
    }
    latest = {
        "seconds": evaluation["runtime_seconds"],
        "ub": None,
        "lb": None,
        "gap_percent": None,
        "served_upper_bound": phase_stats.get("served_upper_bound"),
        "served": evaluation["served_passengers"],
        "unserved": evaluation["unserved_passengers"],
        "journey_time_seconds": evaluation["journey_time_seconds"],
        "used_fleet": args.fixed_k,
        "type_counts": {"all_stop": args.fixed_k},
    }
    detail = {
        "eyebrow": "Regelmäßige All-Stop-OIP-Referenz",
        "title": f"{args.family.upper()} · Last {args.demand_total} · K={args.fixed_k}",
        "subtitle": "No-Wait · regelmäßige Anfangsaufstellung · vollständige gemeinsame Phasensuche",
        "status": result["status"],
        "demand_total": args.demand_total,
        "fleet_cap": args.fixed_k,
        "maximum_wait_seconds": 0,
        "type_counts": {"all_stop": args.fixed_k},
        "latest": latest,
        "points": [latest] if latest["served"] is not None else [],
        "initial_states": [asdict(item) for item in seed.fleet_plan.initial_states],
        "native_incumbent_seen": False,
    }
    snapshot = {
        "schema_version": 1,
        "campaign_id": output.name,
        "campaign_kind": "oip_comparison",
        "label": detail["title"],
        "status": result["status"],
        "objective": "served",
        "method": "regular_all_stop_initial_placement",
        "operating_mode": "all_stop",
        "formulation": "common_1ms_oip",
        "sequence": 1,
        "trial_count": 1,
        "completed_trial_count": int(evaluation["passenger_plan"] is not None),
        "trials": [],
        "events": [],
        "updated_at_utc": datetime.now(UTC).isoformat(),
    }
    atomic_json(output / "manifest.json", manifest)
    atomic_json(output / "result.json", result)
    atomic_json(output / "detail.json", detail)
    atomic_json(output / "snapshot.json", snapshot)
    print(f"regular all-stop reference: {result['status']} · {output}")


if __name__ == "__main__":
    main()
