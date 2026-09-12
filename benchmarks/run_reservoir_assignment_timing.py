"""Run the one-pass load-aware assignment and exact timing pilot."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_assignment import (
    ReservoirAssignmentMasterConfig,
    ReservoirAssignmentPipelineConfig,
    ReservoirAssignmentTimingConfig,
    ReservoirConflictConfig,
    assignment_from_plan,
    assignment_from_payload,
    assignment_to_payload,
    conflict_from_payload,
    conflict_to_payload,
    extract_assignment_conflict,
    solve_assignment_master,
    solve_assignment_pipeline,
    solve_assignment_timing,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)


def main():
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument(
        "--stage",
        choices=("master", "timing", "pipeline", "conflict"),
        default="pipeline",
    )
    p.add_argument("--reference-checkpoint", required=True, type=Path)
    p.add_argument("--assignment-input", type=Path)
    p.add_argument("--conflict-input", action="append", type=Path, default=[])
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--additional-served", type=int, default=10)
    p.add_argument(
        "--assignment-profile",
        choices=("balanced", "total_work"),
        default="balanced",
    )
    p.add_argument("--fleet-cap", type=int)
    p.add_argument("--master-seconds", type=float, default=60)
    p.add_argument("--timing-seconds", type=float, default=120)
    p.add_argument("--threads", type=int, default=12)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--memory-gib", type=float, default=24)
    p.add_argument("--no-witness-hints", action="store_true")
    p.add_argument("--free-nonservice-routes", action="store_true")
    p.add_argument("--fix-witness-waits", action="store_true")
    p.add_argument("--fix-witness-resource-order", action="store_true")
    p.add_argument(
        "--passenger-fixing",
        choices=("exact", "commitments", "reassign"),
        default="exact",
    )
    p.add_argument("--log-solvers", action="store_true")
    p.add_argument("--conflict-seconds", type=float, default=180)
    p.add_argument("--conflict-deletion-seconds", type=float, default=300)
    p.add_argument("--conflict-replay-seconds", type=float, default=120)
    p.add_argument("--conflict-deletion-slice-seconds", type=float, default=15)
    a = p.parse_args()
    if a.conflict_input and a.stage != "master":
        p.error("--conflict-input is supported only for --stage master")
    if a.passenger_fixing != "exact" and a.stage not in ("timing", "conflict"):
        p.error("--passenger-fixing is supported only for timing/conflict stages")
    timing_only = (
        a.fix_witness_waits
        or a.fix_witness_resource_order
        or a.free_nonservice_routes
        or a.no_witness_hints
    )
    if timing_only and a.stage not in ("timing", "conflict"):
        p.error("timing controls are supported only for timing/conflict stages")
    a.output.mkdir(parents=True, exist_ok=False)
    domain, reference_plan = load_reference(a.reference_checkpoint)
    reference = validate_reservoir_cp_plan(domain.problem, reference_plan)
    demand = sum(g.count for g in domain.problem.demand_groups)
    target = min(demand, reference.served + a.additional_served)
    atomic_json(a.output / "domain.json", domain.problem.manifest)
    atomic_json(a.output / "reference_metrics.json", asdict(reference))
    assignment = plan = None
    conflicts = tuple(
        conflict_from_payload(json.loads(path.read_text()))
        for path in a.conflict_input
    )
    if a.stage == "pipeline":
        result, assignment, plan = solve_assignment_pipeline(
            domain.problem,
            reference_plan,
            ReservoirAssignmentPipelineConfig(
                additional_served=a.additional_served,
                assignment_profile=a.assignment_profile,
                fleet_cap=a.fleet_cap,
                master_seconds=a.master_seconds,
                timing_seconds=a.timing_seconds,
                threads=a.threads,
                seed=a.seed,
                soft_memory_gb=a.memory_gib,
                use_witness_hints=not a.no_witness_hints,
                fix_routes=not a.free_nonservice_routes,
                log_solvers=a.log_solvers,
            ),
        )
    elif a.stage == "master":
        result, assignment = solve_assignment_master(
            domain.problem,
            ReservoirAssignmentMasterConfig(
                target_served=target,
                profile=a.assignment_profile,
                fleet_cap=a.fleet_cap,
                time_limit_seconds=a.master_seconds,
                threads=a.threads,
                seed=a.seed,
                soft_memory_gb=a.memory_gib,
                log_to_console=a.log_solvers,
                conflict_cuts=conflicts,
            ),
            reference_plan=reference_plan,
        )
    elif a.stage == "conflict":
        if a.assignment_input is None:
            p.error("--assignment-input is required for --stage conflict")
        assignment = assignment_from_payload(json.loads(a.assignment_input.read_text()))
        timing_config = ReservoirAssignmentTimingConfig(
            time_limit_seconds=a.timing_seconds,
            workers=1,
            seed=a.seed,
            log_search_progress=a.log_solvers,
            use_witness_hints=not a.no_witness_hints,
            fix_routes=not a.free_nonservice_routes,
            fix_witness_waits=a.fix_witness_waits,
            fix_witness_resource_order=a.fix_witness_resource_order,
            passenger_fixing=a.passenger_fixing,
        )
        result, conflict = extract_assignment_conflict(
            domain.problem,
            assignment,
            timing_config,
            ReservoirConflictConfig(
                time_limit_seconds=a.conflict_seconds,
                deletion_limit_seconds=a.conflict_deletion_seconds,
                replay_limit_seconds=a.conflict_replay_seconds,
                deletion_slice_seconds=a.conflict_deletion_slice_seconds,
                workers=1,
                seed=a.seed,
            ),
        )
        if conflict is not None:
            atomic_json(a.output / "conflict.json", conflict_to_payload(conflict))
    else:
        assignment = (
            assignment_from_plan(domain.problem, reference_plan)
            if a.assignment_input is None
            else assignment_from_payload(json.loads(a.assignment_input.read_text()))
        )
        result, plan = solve_assignment_timing(
            domain.problem,
            assignment,
            ReservoirAssignmentTimingConfig(
                time_limit_seconds=a.timing_seconds,
                workers=a.threads,
                seed=a.seed,
                log_search_progress=a.log_solvers,
                use_witness_hints=not a.no_witness_hints,
                fix_routes=not a.free_nonservice_routes,
                fix_witness_waits=a.fix_witness_waits,
                fix_witness_resource_order=a.fix_witness_resource_order,
                passenger_fixing=a.passenger_fixing,
            ),
        )
    atomic_json(a.output / "result.json", result)
    if assignment is not None and a.stage != "conflict":
        atomic_json(a.output / "assignment.json", assignment_to_payload(assignment))
    if plan is not None:
        write_reservoir_cp_checkpoint(a.output / "plan.json", domain.problem, plan)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
