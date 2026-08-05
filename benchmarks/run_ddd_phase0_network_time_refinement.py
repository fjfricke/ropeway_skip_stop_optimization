from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    THREE_STATION_TIME_REFINEMENT_CASE_ID,
    build_three_station_network_time_refinement_probe,
    build_three_station_time_refinement_artifact,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddNetworkTimeRefinementSolver,
    DddNetworkTimeRefinementStatus,
    DddReferenceToEanMovementPlanAdapter,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    validate_ean_movement_plan_against_artifact,
)


def main() -> None:
    output_dir = Path("benchmarks/output/ddd_phase0_network_time_refinement")
    started = perf_counter()
    problem = build_three_station_network_time_refinement_probe()
    result = DddNetworkTimeRefinementSolver().solve(problem)
    if (
        result.status is not DddNetworkTimeRefinementStatus.OPTIMAL
        or result.reference_solution is None
    ):
        raise RuntimeError(
            f"DDD physical network refinement failed: {result.status}"
        )
    artifact = build_three_station_time_refinement_artifact()
    plan = DddReferenceToEanMovementPlanAdapter().build(
        problem=problem.movement_problem,
        solution=result.reference_solution,
        artifact=artifact,
    )
    validate_ean_movement_plan_against_artifact(artifact, plan).raise_for_errors()
    elapsed_seconds = perf_counter() - started

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "instance_id": THREE_STATION_TIME_REFINEMENT_CASE_ID,
        "status": result.status.value,
        "global_lower_bound": result.global_lower_bound,
        "global_upper_bound": result.global_upper_bound,
        "absolute_gap": result.absolute_gap,
        "round_count": len(result.iterations),
        "iterations": [asdict(item) for item in result.iterations],
        "support_fingerprint": result.reference_solution.support_fingerprint,
        "ean_validation_complete": True,
        "elapsed_seconds": elapsed_seconds,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{THREE_STATION_TIME_REFINEMENT_CASE_ID}.json"
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for iteration in result.iterations:
        cell_lifts = ",".join(
            status.value for status in iteration.cell_lift_statuses
        )
        print(
            f"round={iteration.round_index} "
            f"nodes={iteration.node_count} arcs={iteration.arc_count} "
            f"variables={iteration.variable_count} "
            f"constraints={iteration.constraint_count} "
            f"lb={iteration.global_lower_bound} "
            f"ub={iteration.global_upper_bound} "
            f"cell_lift={cell_lifts or 'not_run'} "
            f"cell_full_validation="
            f"{iteration.cell_lift_validation_status.value} "
            f"recovery_full_validation="
            f"{iteration.recovery_validation_status.value} "
            f"split={iteration.split_state_id}@{iteration.split_boundary_seconds}"
        )
    print(
        f"{result.status.value}: LB={result.global_lower_bound}; "
        f"UB={result.global_upper_bound}; elapsed={elapsed_seconds:.3f}s; "
        f"output={output_path}"
    )


if __name__ == "__main__":
    main()
