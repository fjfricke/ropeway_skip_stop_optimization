from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    THREE_STATION_TWO_CABIN_MERGE_CASE_ID,
    build_three_station_two_cabin_merge_artifact,
    build_three_station_two_cabin_merge_probe_objective,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddDelayedConflictSolver,
    DddIterativeStatus,
    DddReferenceToEanMovementPlanAdapter,
    EanArtifactToDddMovementProblemAdapter,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    validate_ean_movement_plan_against_artifact,
)


def main() -> None:
    output_dir = Path("benchmarks/output/ddd_phase0_conflict_loop")
    started = perf_counter()
    artifact = build_three_station_two_cabin_merge_artifact()
    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)
    result = DddDelayedConflictSolver().solve(
        problem,
        objective=build_three_station_two_cabin_merge_probe_objective(problem),
    )
    if result.status is not DddIterativeStatus.FEASIBLE or result.solution is None:
        raise RuntimeError(f"DDD conflict-loop proof fixture failed: {result.status}")
    plan = DddReferenceToEanMovementPlanAdapter().build(
        problem=problem,
        solution=result.solution,
        artifact=artifact,
    )
    validate_ean_movement_plan_against_artifact(artifact, plan).raise_for_errors()
    elapsed_seconds = perf_counter() - started

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "instance_id": THREE_STATION_TWO_CABIN_MERGE_CASE_ID,
        "status": result.status.value,
        "candidate_support_count": result.candidate_support_count,
        "round_count": len(result.iterations),
        "cut_count": len(result.cuts),
        "final_lift_complete": result.final_lift_complete,
        "objective_value": result.objective_value,
        "solution_support_fingerprint": result.solution.support_fingerprint,
        "iterations": [asdict(item) for item in result.iterations],
        "cuts": [
            {
                **asdict(cut),
                "right_hand_side": cut.right_hand_side,
            }
            for cut in result.cuts
        ],
        "elapsed_seconds": elapsed_seconds,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{THREE_STATION_TWO_CABIN_MERGE_CASE_ID}.json"
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for iteration in result.iterations:
        print(
            f"round={iteration.round_index} "
            f"objective={iteration.master_objective_value} "
            f"conflicts={iteration.conflict_count} "
            f"cuts_added={len(iteration.added_cut_ids)}"
        )
    print(
        f"{result.status.value}: supports={result.candidate_support_count}; "
        f"cuts={len(result.cuts)}; elapsed={elapsed_seconds:.3f}s; "
        f"output={output_path}"
    )


if __name__ == "__main__":
    main()
