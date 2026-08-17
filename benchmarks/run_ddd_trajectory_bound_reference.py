from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import UTC, datetime
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    THREE_STATION_EXHAUSTIVE_BOUND_CASE_ID,
    build_three_station_exhaustive_bound_artifact,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.examples.three_station import (
    build_three_station_scenario,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddExhaustiveTrajectoryMasterBuilder,
    DddTrajectoryFactorizedLpOptimizer,
    DddTrajectoryFactorizedMipReferenceOptimizer,
    EanArtifactToDddMovementProblemAdapter,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Enumerate a tiny complete no-wait trajectory master and measure "
            "its certified root-LP gap."
        )
    )
    parser.add_argument("--cabins", type=int, default=3)
    parser.add_argument("--horizon", type=float, default=250.0)
    parser.add_argument(
        "--objective",
        choices=tuple(item.value for item in EanPassengerObjective),
        default=EanPassengerObjective.JOURNEY_TIME.value,
    )
    parser.add_argument("--max-trajectories-per-start", type=int, default=100_000)
    parser.add_argument("--max-total-trajectories", type=int, default=100_000)
    parser.add_argument("--max-pair-checks", type=int, default=2_000_000)
    parser.add_argument("--solver-output", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/output/ddd_trajectory_bound_reference"),
    )
    args = parser.parse_args()

    objective = EanPassengerObjective(args.objective)
    artifact = build_three_station_exhaustive_bound_artifact(
        cabin_count=args.cabins,
        horizon_seconds=args.horizon,
    )
    scenario = replace(
        build_three_station_scenario(),
        id=artifact.scenario_id,
    )
    movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
    problem = build_initial_ddd_network_problem(movement)
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)
    exhaustive = DddExhaustiveTrajectoryMasterBuilder(
        max_trajectories_per_start=args.max_trajectories_per_start,
        max_total_trajectories=args.max_total_trajectories,
        max_incompatibility_pair_checks=args.max_pair_checks,
    ).build(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=objective,
    )
    lp = DddTrajectoryFactorizedLpOptimizer(output_flag=args.solver_output).solve(
        exhaustive.master_problem
    )
    mip = DddTrajectoryFactorizedMipReferenceOptimizer(
        output_flag=args.solver_output
    ).solve(exhaustive.master_problem)

    absolute_gap = (
        mip.objective_value - lp.objective_value
        if mip.objective_value is not None and lp.objective_value is not None
        else None
    )
    relative_gap = (
        absolute_gap / abs(mip.objective_value)
        if absolute_gap is not None
        and mip.objective_value is not None
        and abs(mip.objective_value) > 1e-9
        else None
    )
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "case_id": THREE_STATION_EXHAUSTIVE_BOUND_CASE_ID,
        "scope": "fixed_starts_no_wait_complete_trajectory_master",
        "cabins": args.cabins,
        "horizon_seconds": args.horizon,
        "objective": objective.value,
        "demand_group_count": len(passenger_build.demand_groups),
        "ride_candidate_count": len(passenger_build.ride_candidates),
        "trajectory_count_by_cabin_id": exhaustive.trajectory_count_by_cabin_id,
        "trajectory_count": exhaustive.trajectory_count,
        "generation_branch_count": exhaustive.generation_branch_count,
        "self_conflict_pruned_count": exhaustive.self_conflict_pruned_count,
        "incompatibility_pair_check_count": (
            exhaustive.incompatibility_pair_check_count
        ),
        "incompatibility_pair_count": len(
            exhaustive.master_problem.incompatibility_pairs
        ),
        "passenger_ride_variable_count": sum(
            len(option.rides) for option in exhaustive.master_problem.options
        ),
        "lp": _result_payload(lp),
        "mip": _result_payload(mip),
        "root_gap_absolute": absolute_gap,
        "root_gap_relative": relative_gap,
        "runtime_seconds": {
            "trajectory_generation": exhaustive.generation_seconds,
            "passenger_option_build": exhaustive.option_build_seconds,
            "incompatibility_build": exhaustive.incompatibility_build_seconds,
            "complete_master_build": exhaustive.total_seconds,
            "lp_total": lp.total_seconds,
            "mip_total": mip.total_seconds,
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / (
        f"{THREE_STATION_EXHAUSTIVE_BOUND_CASE_ID}"
        f"__k{args.cabins}__h{args.horizon:g}__{objective.value}.json"
    )
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    gap_text = "-" if relative_gap is None else f"{100.0 * relative_gap:.4f}%"
    print(
        f"{THREE_STATION_EXHAUSTIVE_BOUND_CASE_ID}: "
        f"K={args.cabins} H={args.horizon:g}s "
        f"columns={exhaustive.trajectory_count} "
        f"rows={len(exhaustive.master_problem.incompatibility_pairs)} "
        f"LB={lp.objective_value} OPT={mip.objective_value} gap={gap_text} "
        f"output={output_path}"
    )


def _result_payload(result: object) -> dict[str, object]:
    values = asdict(result)
    return {
        key: (value.value if hasattr(value, "value") else value)
        for key, value in values.items()
        if key not in {"option_values_by_id", "ride_values_by_id", "duals"}
    }


if __name__ == "__main__":
    main()
