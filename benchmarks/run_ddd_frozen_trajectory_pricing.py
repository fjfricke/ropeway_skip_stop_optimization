from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import UTC, datetime
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddTrajectoryExactNoWaitPricingOracle,
    DddTrajectoryFactorizedLpOptimizer,
    DddTrajectoryMasterDualMode,
    DddTrajectoryPricingFormulation,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_all_stop_seed_trajectories,
    build_ddd_trajectory_reference_master,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
    NetworkEanBuildArtifactBuilder,
    SparseHeadwayPairBuilder,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Price one cabin against the frozen all-stop trajectory RMP duals."
        )
    )
    parser.add_argument(
        "--example",
        default="five_station_circle_cw_half_skip_no_wait_v0",
    )
    parser.add_argument("--cabin-id", type=int, default=0)
    parser.add_argument(
        "--objective",
        choices=tuple(item.value for item in EanPassengerObjective),
        default=EanPassengerObjective.JOURNEY_TIME.value,
    )
    parser.add_argument(
        "--master-dual-mode",
        choices=tuple(item.value for item in DddTrajectoryMasterDualMode),
        default=DddTrajectoryMasterDualMode.DEFAULT.value,
    )
    parser.add_argument(
        "--pricing-formulation",
        choices=tuple(item.value for item in DddTrajectoryPricingFormulation),
        default=DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH.value,
    )
    parser.add_argument("--pricing-time-limit", type=float, default=10.0)
    parser.add_argument("--pricing-threads", type=int, default=1)
    parser.add_argument("--pricing-mip-focus", type=int, default=2)
    parser.add_argument("--solver-output", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/output/ddd_frozen_trajectory_pricing"),
    )
    args = parser.parse_args()

    example = get_example(args.example)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    builder = example.build_ean_artifact_builder(scenario, config)
    if not isinstance(builder, NetworkEanBuildArtifactBuilder):
        raise ValueError("frozen trajectory pricing requires the network builder")
    artifact = replace(
        builder,
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)
    movement = EanArtifactToDddMovementProblemAdapter().build(artifact)
    problem = build_initial_ddd_network_problem(movement)
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)
    objective = EanPassengerObjective(args.objective)
    seed = build_ddd_all_stop_seed_trajectories(movement)
    reference_master = build_ddd_trajectory_reference_master(
        problem=problem,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=objective,
        reference_trajectories=seed,
    )
    lp = DddTrajectoryFactorizedLpOptimizer(
        output_flag=args.solver_output,
        dual_mode=DddTrajectoryMasterDualMode(args.master_dual_mode),
    ).solve(reference_master.master_problem)
    if lp.objective_value is None or lp.duals is None:
        raise RuntimeError("frozen trajectory RMP did not solve to optimality")
    result = DddTrajectoryExactNoWaitPricingOracle(
        time_limit_seconds=args.pricing_time_limit,
        threads=args.pricing_threads,
        output_flag=args.solver_output,
        mip_focus=args.pricing_mip_focus,
        formulation=DddTrajectoryPricingFormulation(args.pricing_formulation),
    ).solve(
        movement_problem=movement,
        artifact=artifact,
        passenger_build=passenger_build,
        objective=objective,
        cabin_id=args.cabin_id,
        duals=lp.duals,
        excluded_route_option_sequences=frozenset(
            trajectory.support_signature
            for trajectory in seed
            if trajectory.cabin_id == args.cabin_id
        ),
    )

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "case_id": args.example,
        "cabin_id": args.cabin_id,
        "objective": objective.value,
        "master_dual_mode": args.master_dual_mode,
        "master_objective": lp.objective_value,
        "master_dual_fingerprint": lp.duals.fingerprint,
        "pricing_formulation": args.pricing_formulation,
        "pricing_time_limit_seconds": args.pricing_time_limit,
        "pricing_mip_focus": args.pricing_mip_focus,
        "status": result.status.value,
        "exact": result.exact,
        "incumbent_reduced_cost": result.minimum_reduced_cost,
        "certified_reduced_cost_lower_bound": (
            result.certified_reduced_cost_lower_bound
        ),
        "absolute_pricing_gap": (
            result.minimum_reduced_cost - result.certified_reduced_cost_lower_bound
            if result.certified_reduced_cost_lower_bound is not None
            else None
        ),
        "model_variable_count": result.model_variable_count,
        "model_linear_constraint_count": result.model_linear_constraint_count,
        "model_general_constraint_count": result.model_general_constraint_count,
        "solver_node_count": result.solver_node_count,
        "solve_seconds": result.solve_seconds,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / (
        f"{args.example}__c{args.cabin_id}__{args.pricing_formulation}"
        f"__focus{args.pricing_mip_focus}__{args.pricing_time_limit:g}s.json"
    )
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"cabin={args.cabin_id} formulation={args.pricing_formulation} "
        f"focus={args.pricing_mip_focus} status={result.status.value} "
        f"rc={result.minimum_reduced_cost:.3f} "
        f"rc_lb={result.certified_reduced_cost_lower_bound} "
        f"gap={payload['absolute_pricing_gap']} nodes={result.solver_node_count:g} "
        f"time={result.solve_seconds:.2f}s output={output_path}"
    )


if __name__ == "__main__":
    main()
