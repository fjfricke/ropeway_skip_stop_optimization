from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    THREE_STATION_TWO_CABIN_MERGE_CASE_ID,
    build_three_station_two_cabin_merge_artifact,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddReferenceSolver,
    DddReferenceToEanMovementPlanAdapter,
    EanArtifactToDddMovementProblemAdapter,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    NetworkEanBuildArtifactBuilder,
    SparseHeadwayPairBuilder,
    validate_ean_movement_plan_against_artifact,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the solver-free exhaustive reference oracle for DDD Phase 0."
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--case",
        choices=(THREE_STATION_TWO_CABIN_MERGE_CASE_ID,),
    )
    source.add_argument("--example")
    parser.add_argument("--enumerate-all", action="store_true")
    parser.add_argument("--max-trajectories-per-start", type=int, default=100_000)
    parser.add_argument("--max-retained-solutions", type=int, default=1_000)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/output/ddd_phase0_reference"),
    )
    args = parser.parse_args()

    artifact_started = perf_counter()
    if args.example is not None:
        instance_id = args.example
        example = get_example(args.example)
        scenario = example.build_scenario()
        config = example.build_ean_config(scenario)
        builder = example.build_ean_artifact_builder(scenario, config)
        if not isinstance(builder, NetworkEanBuildArtifactBuilder):
            raise ValueError("DDD reference runner requires a network artifact builder")
        artifact = replace(
            builder,
            headway_pair_builder=SparseHeadwayPairBuilder(),
        ).build(scenario, config)
    else:
        instance_id = args.case or THREE_STATION_TWO_CABIN_MERGE_CASE_ID
        artifact = build_three_station_two_cabin_merge_artifact()
    artifact_seconds = perf_counter() - artifact_started

    adapter_started = perf_counter()
    problem = EanArtifactToDddMovementProblemAdapter().build(artifact)
    adapter_seconds = perf_counter() - adapter_started

    solve_started = perf_counter()
    result = DddReferenceSolver(
        max_trajectories_per_start=args.max_trajectories_per_start,
        max_retained_feasible_solutions=args.max_retained_solutions,
        stop_after_first_feasible=not args.enumerate_all,
    ).solve(problem)
    solve_seconds = perf_counter() - solve_started

    plan_seconds = 0.0
    validation_seconds = 0.0
    support_fingerprint = None
    active_visit_count = None
    if result.solution is not None:
        plan_started = perf_counter()
        plan = DddReferenceToEanMovementPlanAdapter().build(
            problem=problem,
            solution=result.solution,
            artifact=artifact,
        )
        plan_seconds = perf_counter() - plan_started
        validation_started = perf_counter()
        validate_ean_movement_plan_against_artifact(
            artifact,
            plan,
        ).raise_for_errors()
        validation_seconds = perf_counter() - validation_started
        support_fingerprint = result.solution.support_fingerprint
        active_visit_count = sum(
            len(trajectory.visits) for trajectory in plan.trajectories
        )

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "instance_id": instance_id,
        "scope": "fixed_starts_no_waiting",
        "status": result.status.value,
        "search_metrics": asdict(result.metrics),
        "problem": {
            "cabin_count": len(problem.starts),
            "state_count": len(problem.states),
            "route_option_count": len(problem.route_options),
            "resource_count": len(problem.resources),
            "operational_end_seconds": problem.operational_end_seconds,
            "active_visit_count": active_visit_count,
        },
        "runtime_seconds": {
            "sparse_artifact": artifact_seconds,
            "adapter": adapter_seconds,
            "reference_solve": solve_seconds,
            "plan_conversion": plan_seconds,
            "complete_validation": validation_seconds,
        },
        "support_fingerprint": support_fingerprint,
        "feasible_support_fingerprints": result.feasible_support_fingerprints,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / f"{instance_id}.json"
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"{instance_id}: {result.status.value}; "
        f"trajectories={result.metrics.generated_trajectory_count}; "
        f"combinations={result.metrics.combination_attempt_count}; "
        f"solve={solve_seconds:.3f}s; output={output_path}"
    )


if __name__ == "__main__":
    main()
