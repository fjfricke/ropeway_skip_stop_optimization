"""Revalidate a saved CP-SAT run; never optimize movement or overwrite its files."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig, prepare_ddd_fixed_k_arc_flow_run,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_cp_sat_waiting import with_exit_waiting
from ropeway_skip_stop_optimization.benchmarking.ddd_cp_sat_warmup import with_empty_warmup
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    read_ddd_cp_sat_checkpoint, stable_fingerprint, validate_ddd_cp_sat_domain,
)
from ropeway_skip_stop_optimization.optimization.ddd.ean_plan_adapter import DddReferenceToEanMovementPlanAdapter
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import DddFixedKOperatingMode, DddFixedKStartPolicy
from ropeway_skip_stop_optimization.optimization.ean.horizon_audit import audit_ean_exact_horizon
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanFixedMovementPassengerModelBuilder, EanPassengerAssignmentDomain,
)


def audit_run(run_dir: Path, *, passenger_seconds: float) -> dict:
    started = perf_counter()
    config = json.loads((run_dir / "config.json").read_text())
    prepared = prepare_ddd_fixed_k_arc_flow_run(DddFixedKArcFlowRunConfig(
        example_id=config["example_id"], cabin_count=config["cabin_count"],
        operating_mode=DddFixedKOperatingMode(config["operating_mode"]),
        start_policy=DddFixedKStartPolicy(config["start_policy"]),
        cp_seed_time_limit_seconds=0,
    ))
    if config.get("maximum_wait_seconds", 0) > 0:
        prepared = with_exit_waiting(prepared, maximum_seconds=config["maximum_wait_seconds"],
                                     step_seconds=config["waiting_step_seconds"])
    prepared = with_empty_warmup(prepared, seconds=config.get("warmup_seconds", 0))
    problem = prepared.problem
    manifest = validate_ddd_cp_sat_domain(problem)
    incumbent = read_ddd_cp_sat_checkpoint(run_dir / "incumbent.json", problem=problem, manifest=manifest)
    plan = DddReferenceToEanMovementPlanAdapter(
        waiting_policy=problem.resolved_trajectory_problem.waiting_policy,
    ).build(problem=problem.resolved_trajectory_problem.structural_movement_problem,
            solution=incumbent.solution, artifact=problem.artifact)
    audit = audit_ean_exact_horizon(problem.artifact, plan)
    result = {
        "source_run": str(run_dir.resolve()),
        "source_checkpoint_sha256": hashlib.sha256((run_dir / "incumbent.json").read_bytes()).hexdigest(),
        "source_config_sha256": hashlib.sha256((run_dir / "config.json").read_bytes()).hexdigest(),
        "domain_fingerprint": stable_fingerprint(manifest),
        "contract": audit.contract,
        "operational_end_seconds": plan.model_end_seconds,
        "original_cp_objective": incumbent.objective,
        "original_cp_served_count": sum(incumbent.ride_counts.values()),
        "finite_validation_passed": audit.finite_validation.is_valid,
        "finite_validation_issues": [asdict(i) for i in audit.finite_validation.issues],
        "exported_headway_violation_count": len(audit.exported_headway_violations),
        "exported_headway_violations": [asdict(v) for v in audit.exported_headway_violations],
        "visits_clearing_after_horizon": audit.visits_clearing_after_horizon,
        "continuation_status": audit.continuation_status,
        "tail_scope": "all available checkpoint occurrences of exported visits; no future visits constructed",
        "passenger_validation": {"status": "NOT_RUN"},
    }
    if passenger_seconds > 0 and audit.finite_validation.is_valid:
        import gurobipy as gp
        from gurobipy import GRB
        with gp.Model() as model:
            model.Params.OutputFlag = 0
            model.Params.Threads = 1
            model.Params.TimeLimit = passenger_seconds
            model.Params.MIPGap = 0
            assignment = EanFixedMovementPassengerModelBuilder().build(
                model=model, scenario=prepared.scenario, artifact=problem.artifact,
                movement_plan=plan, passenger_build=problem.passenger_build,
                objective=problem.objective, assignment_domain=EanPassengerAssignmentDomain.INTEGER,
                grb=GRB, gp=gp,
            )
            solve_started = perf_counter()
            model.optimize()
            payload = {"status_code": model.Status, "scope": "FIXED_MOVEMENT_FINITE_HORIZON",
                       "status": "OPTIMAL" if model.Status == GRB.OPTIMAL else "NOT_PROVEN_OPTIMAL",
                       "solve_seconds": perf_counter() - solve_started}
            if model.SolCount:
                counts = assignment.extract_assignment()
                payload.update(objective=model.ObjVal,
                               assignment=asdict(counts))
            result["passenger_validation"] = payload
    result["total_wall_seconds"] = perf_counter() - started
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--passenger-seconds", type=float, default=0)
    args = parser.parse_args()
    if not 0 <= args.passenger_seconds < float("inf"):
        parser.error("passenger-seconds must be finite and nonnegative")
    if args.output.exists():
        parser.error("output already exists; choose a new audit path")
    result = audit_run(args.run_dir, passenger_seconds=args.passenger_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(result, output, indent=2, default=lambda obj: obj.value, allow_nan=False)
        output.write("\n")
    print(json.dumps({k: result[k] for k in (
        "finite_validation_passed", "exported_headway_violation_count", "continuation_status", "total_wall_seconds",
    )}))


if __name__ == "__main__":
    main()
