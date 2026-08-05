from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    EVENT_CELL_BOUND_PROBE_CASE_ID,
    build_event_cell_bound_probe,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddTimeRefinementSolver,
    DddTimeRefinementStatus,
    validate_ddd_recovered_schedule,
)


def main() -> None:
    output_dir = Path("benchmarks/output/ddd_phase0_time_refinement")
    problem = build_event_cell_bound_probe()
    started = perf_counter()
    result = DddTimeRefinementSolver().solve(problem)
    elapsed_seconds = perf_counter() - started
    if result.status is not DddTimeRefinementStatus.OPTIMAL:
        raise RuntimeError(f"DDD time-refinement proof failed: {result.status}")
    if result.solution is None:
        raise RuntimeError("optimal DDD time-refinement result has no solution")
    validate_ddd_recovered_schedule(problem, result.solution)

    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "instance_id": EVENT_CELL_BOUND_PROBE_CASE_ID,
        "status": result.status.value,
        "global_lower_bound": result.global_lower_bound,
        "global_upper_bound": result.global_upper_bound,
        "absolute_gap": result.absolute_gap,
        "round_count": len(result.iterations),
        "iterations": [asdict(item) for item in result.iterations],
        "solution": asdict(result.solution),
        "final_discretization": asdict(result.final_discretization),
        "elapsed_seconds": elapsed_seconds,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{EVENT_CELL_BOUND_PROBE_CASE_ID}.json"
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for iteration in result.iterations:
        split = (
            f"{iteration.split_state_id}@{iteration.split_boundary_seconds:g}"
            if iteration.split_boundary_seconds is not None
            else "none"
        )
        print(
            f"round={iteration.round_index} "
            f"paths={iteration.candidate_path_count} "
            f"LB={iteration.global_lower_bound:g} "
            f"UB={iteration.global_upper_bound:g} "
            f"strict={iteration.strict_lift_status.value} "
            f"split={split}"
        )
    print(
        f"{result.status.value}: LB={result.global_lower_bound:g}; "
        f"UB={result.global_upper_bound:g}; gap={result.absolute_gap:g}; "
        f"elapsed={elapsed_seconds:.3f}s; output={output_path}"
    )


if __name__ == "__main__":
    main()
