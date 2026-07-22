from __future__ import annotations

import argparse
import json

from ropeway_skip_stop_optimization.examples.circular_skip_stop import (
    FiveStationCircleCwHalfSkipWaitExample,
)
from ropeway_skip_stop_optimization.examples.three_station import ThreeStationExample
from ropeway_skip_stop_optimization.optimization.ean import (
    EanInitialPlacementCapacityProblem,
    EanInitialPlacementCapacitySolveConfig,
    EanInitialPlacementDelayedHeadwayConfig,
    EanInitialPlacementFeasibilityOptimizer,
    EanInitialPlacementFeasibilityProblem,
    EanInitialPlacementHeadwayGenerationMode,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=("three", "five_circle_skip_wait"))
    parser.add_argument("k", type=int)
    parser.add_argument("--time-limit", type=float, default=300.0)
    args = parser.parse_args()

    example = (
        ThreeStationExample()
        if args.case == "three"
        else FiveStationCircleCwHalfSkipWaitExample()
    )
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    artifact_builder = example.build_ean_artifact_builder(scenario, config)
    capacity_problem = EanInitialPlacementCapacityProblem(
        scenario=scenario,
        config=config,
        artifact_builder=artifact_builder,
    )
    solve_config = EanInitialPlacementCapacitySolveConfig(
        headway_generation_mode=(
            EanInitialPlacementHeadwayGenerationMode.DELAYED_VIOLATIONS
        ),
        delayed_headway=EanInitialPlacementDelayedHeadwayConfig(
            total_time_limit_seconds=args.time_limit
        ),
    )
    # Reuse the search progress renderer for an individual experimental probe.
    from ropeway_skip_stop_optimization.optimization.ean.optimizers.initial_placement_capacity import (
        _CapacitySearchProgress,
    )

    progress = _CapacitySearchProgress(True, args.k, args.k + 1)
    with progress:
        progress.probe_started(args.k, args.k, args.k)
        result = EanInitialPlacementFeasibilityOptimizer(solve_config).solve(
            EanInitialPlacementFeasibilityProblem(capacity_problem, args.k),
            on_headway_round=progress.headway_round,
        )
        progress.probe_finished(result, args.k, args.k)
    print(
        json.dumps(
            {
                "case": args.case,
                "k": args.k,
                "status": result.status.value,
                "solver_status": result.solver_status,
                "setup_seconds": result.setup_runtime_seconds,
                "solve_seconds": result.solve_runtime_seconds,
                "separation_seconds": result.separation_runtime_seconds,
                "augmentation_seconds": result.augmentation_runtime_seconds,
                "resolves": result.resolve_count,
                "separation_rounds": result.separation_round_count,
                "violations_per_round": result.violations_found_per_round,
                "materialized_pairs": result.headway_pair_count,
                "variables": result.variable_count,
                "constraints": result.constraint_count,
                "final_separation": result.final_headway_separation_complete,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
