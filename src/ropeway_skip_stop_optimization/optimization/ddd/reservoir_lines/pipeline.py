"""Two-stage fixed-line construction followed by native exact timing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from time import perf_counter

from ..cp_sat_integrated import DddIntegratedCpSatConfig
from ..reservoir_cp_sat import DddReservoirCpObjective, DddReservoirCpSatOptimizer
from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from .config import ReservoirLineConfig
from .optimizer import ReservoirLineOptimizer


@dataclass(frozen=True, slots=True)
class ReservoirLinePipelineConfig:
    line: ReservoirLineConfig
    total_time_limit_seconds: float
    construction_share: float = 0.7
    checkpoint_path: Path | None = None
    construction_checkpoint_path: Path | None = None

    def validate(self, problem: DddReservoirCpSatProblem) -> None:
        self.line.validate(problem.available_fleet_count)
        if self.total_time_limit_seconds <= 0:
            raise ValueError("line pipeline time limit must be positive")
        if not 0 < self.construction_share < 1:
            raise ValueError("construction share must lie strictly between zero and one")


def solve_reservoir_line_pipeline(
    problem: DddReservoirCpSatProblem,
    config: ReservoirLinePipelineConfig,
    *,
    reference_plan: DddReservoirCpPlan | None = None,
    event_callback=None,
    build_only: bool = False,
) -> tuple[dict, DddReservoirCpPlan | None]:
    """Optimize patterns first, then dispatch/waits on the selected routes."""
    started = perf_counter()
    problem.validate()
    config.validate(problem)
    deadline = started + config.total_time_limit_seconds
    construction_seconds = config.total_time_limit_seconds * config.construction_share
    construction_deadline = started + construction_seconds
    line_config = replace(
        config.line,
        time_limit_seconds=construction_seconds,
        passenger_service_start_seconds=(
            config.line.passenger_service_start_seconds
            if config.line.passenger_service_start_seconds is not None
            else problem.dispatch_end_seconds
        ),
    )
    stage1, no_wait_plan = ReservoirLineOptimizer(line_config).solve(
        problem,
        reference_plan=reference_plan,
        event_callback=(
            None
            if event_callback is None
            else lambda event: event_callback({**event, "stage": "construction"})
        ),
        build_only=build_only,
        hard_deadline=construction_deadline,
    )
    if build_only or no_wait_plan is None:
        return (
            {
                "schema": "reservoir_line_timing_pipeline_v1",
                "construction_share": config.construction_share,
                "construction": stage1,
                "timing": None,
                "selected_stage": "construction",
                "total_wall_seconds": perf_counter() - started,
            },
            no_wait_plan,
        )

    no_wait_metrics = validate_reservoir_cp_plan(problem, no_wait_plan)
    if config.construction_checkpoint_path is not None:
        write_reservoir_cp_checkpoint(
            config.construction_checkpoint_path, problem, no_wait_plan
        )
    # CP-SAT's reservoir optimizer already treats this as an end-to-end model
    # budget. Reserve a small tail for the pipeline's final validation/export.
    timing_seconds = max(0.001, deadline - perf_counter() - 2.0)
    timing_config = DddIntegratedCpSatConfig(
        total_time_limit_seconds=timing_seconds,
        num_workers=line_config.workers,
        seed=line_config.seed,
        checkpoint_path=config.checkpoint_path,
        checkpoint_interval_seconds=1.0,
        log_search_progress=line_config.log_search_progress,
    )
    timing = DddReservoirCpSatOptimizer(
        timing_config, DddReservoirCpObjective.UNSERVED
    ).solve(
        problem,
        primal_seed=no_wait_plan,
        fixed_route_plan=no_wait_plan,
        event_callback=(
            None
            if event_callback is None
            else lambda event: event_callback({**event, "stage": "timing"})
        ),
    )
    raw = timing["plan"]
    timed_plan = DddReservoirCpPlan(
        tuple(
            DddReservoirCpTrip(
                trip["cabin_id"],
                tuple(trip["route_option_ids"]),
                tuple(trip["switch_ticks"]),
                tuple(trip["wait_ticks"]),
                trip["return_tick"],
            )
            for trip in raw["trips"]
        ),
        dict(raw["ride_counts"]),
    )
    timed_metrics = validate_reservoir_cp_plan(problem, timed_plan)
    if timed_metrics.unserved > no_wait_metrics.unserved:
        raise RuntimeError("timing stage degraded its validated no-wait seed")
    improved = timed_metrics.unserved < no_wait_metrics.unserved
    selected = timed_plan if improved else no_wait_plan
    return (
        {
            "schema": "reservoir_line_timing_pipeline_v1",
            "construction_share": config.construction_share,
            "construction_budget_seconds": construction_seconds,
            "timing_budget_seconds": timing_seconds,
            "construction": stage1,
            "timing": timing,
            "no_wait_metrics": asdict(no_wait_metrics),
            "timed_metrics": asdict(timed_metrics),
            "selected_stage": "timing" if improved else "construction",
            "total_wall_seconds": perf_counter() - started,
        },
        selected,
    )
