"""Multistage line construction using exact passenger service classes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from time import perf_counter

from ..cp_sat_integrated import DddIntegratedCpSatConfig
from ..reservoir_cp_sat import DddReservoirCpObjective, DddReservoirCpSatOptimizer
from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from .config import ReservoirLineConfig
from .preparation import prepare_line_problem
from .service_class_master import (
    ReservoirPatternMasterConfig,
    project_line_plan_to_service_classes,
    solve_service_class_master,
)
from .service_class_timing import solve_service_class_timing
from .service_classes import prepare_line_service_classes


@dataclass(frozen=True, slots=True)
class ReservoirServiceClassPipelineConfig:
    line: ReservoirLineConfig
    master: ReservoirPatternMasterConfig = ReservoirPatternMasterConfig()
    timing_time_limit_seconds: float = 90.0
    waiting_time_limit_seconds: float = 20.0

    def validate(self, problem: DddReservoirCpSatProblem) -> None:
        self.line.validate(problem.available_fleet_count)
        self.master.validate()
        for value in (self.timing_time_limit_seconds, self.waiting_time_limit_seconds):
            if not math.isfinite(value) or value < 0:
                raise ValueError("service-class stage budgets must be nonnegative")


def _plan_from_payload(payload: dict) -> DddReservoirCpPlan:
    return DddReservoirCpPlan(
        tuple(
            DddReservoirCpTrip(
                item["cabin_id"],
                tuple(item["route_option_ids"]),
                tuple(item["switch_ticks"]),
                tuple(item["wait_ticks"]),
                item["return_tick"],
            )
            for item in payload["trips"]
        ),
        dict(payload["ride_counts"]),
    )


def solve_service_class_pipeline(
    problem: DddReservoirCpSatProblem,
    config: ReservoirServiceClassPipelineConfig,
    *,
    build_only: bool = False,
    event_callback=None,
    reference_plan: DddReservoirCpPlan | None = None,
) -> tuple[dict, DddReservoirCpPlan | None]:
    started = perf_counter()
    problem.validate()
    config.validate(problem)
    before = perf_counter()
    prepared_line = prepare_line_problem(problem, config.line)
    prepared_classes = prepare_line_service_classes(problem, prepared_line)
    preparation_seconds = perf_counter() - before
    reference_projection = None
    if reference_plan is not None:
        reference_metrics = validate_reservoir_cp_plan(problem, reference_plan)
        try:
            projected = project_line_plan_to_service_classes(
                problem, prepared_line, prepared_classes, reference_plan
            )
            reference_projection = {
                "status": "represented",
                "served": projected.served,
                "used_fleet": projected.used_fleet,
                "class_count": len(projected.class_counts),
                "validated_metrics": asdict(reference_metrics),
            }
        except ValueError as error:
            reference_projection = {
                "status": "not_representable",
                "reason": str(error),
                "validated_metrics": asdict(reference_metrics),
            }
    maximum_cabins = prepared_line.maximum_cabins
    master = solve_service_class_master(
        problem,
        prepared_classes,
        maximum_cabins,
        config.master,
        build_only=build_only,
    )
    if event_callback is not None:
        event_callback(
            {
                "stage": "master",
                "status": master.status,
                "candidates": len(master.candidates),
                "best_served": (
                    None if not master.candidates else master.candidates[0].served
                ),
            }
        )
    if build_only:
        return (
            {
                "schema": "reservoir_service_class_pipeline_v1",
                "preparation_seconds": preparation_seconds,
                "prepared_class_stats": prepared_classes.stats,
                "service_class_model_fingerprint": prepared_classes.model_fingerprint,
                "reference_projection": reference_projection,
                "master": master.payload,
                "timing": [],
                "waiting": None,
                "selected_stage": None,
                "total_wall_seconds": perf_counter() - started,
            },
            None,
        )

    timing_results = []
    best_plan = None
    best_metrics = None
    per_candidate = (
        config.timing_time_limit_seconds / len(master.candidates)
        if master.candidates
        else 0
    )
    for candidate in master.candidates:
        timing = solve_service_class_timing(
            problem,
            prepared_line,
            prepared_classes,
            candidate,
            config.line,
            time_limit_seconds=per_candidate,
        )
        timing_results.append(timing)
        if event_callback is not None:
            event_callback(
                {
                    "stage": "timing",
                    "candidate_rank": candidate.rank,
                    "status": timing.status,
                    "master_served": candidate.served,
                    "validated_served": timing.validated_served,
                }
            )
        if timing.plan is None:
            continue
        metrics = validate_reservoir_cp_plan(problem, timing.plan)
        if best_metrics is None or (
            metrics.unserved,
            metrics.used_fleet,
            metrics.journey_time_tick,
        ) < (
            best_metrics.unserved,
            best_metrics.used_fleet,
            best_metrics.journey_time_tick,
        ):
            best_plan, best_metrics = timing.plan, metrics

    waiting_result = None
    selected_stage = "timing" if best_plan is not None else None
    if best_plan is not None and config.waiting_time_limit_seconds > 0:
        timing_config = DddIntegratedCpSatConfig(
            total_time_limit_seconds=config.waiting_time_limit_seconds,
            num_workers=config.line.workers,
            seed=config.line.seed,
            checkpoint_interval_seconds=1.0,
            log_search_progress=config.line.log_search_progress,
        )
        waiting_result = DddReservoirCpSatOptimizer(
            timing_config, DddReservoirCpObjective.UNSERVED
        ).solve(problem, primal_seed=best_plan, fixed_route_plan=best_plan)
        if waiting_result.get("plan") is not None:
            waited = _plan_from_payload(waiting_result["plan"])
            waited_metrics = validate_reservoir_cp_plan(problem, waited)
            if waited_metrics.unserved < best_metrics.unserved:
                best_plan, best_metrics = waited, waited_metrics
                selected_stage = "waiting"

    return (
        {
            "schema": "reservoir_service_class_pipeline_v1",
            "problem_fingerprint": problem.fingerprint,
            "preparation_seconds": preparation_seconds,
            "prepared_class_stats": prepared_classes.stats,
            "reference_projection": reference_projection,
            "service_class_model_fingerprint": prepared_classes.model_fingerprint,
            "master": master.payload,
            "timing": [item.payload for item in timing_results],
            "waiting": waiting_result,
            "selected_stage": selected_stage,
            "validated_metrics": None if best_metrics is None else asdict(best_metrics),
            "total_wall_seconds": perf_counter() - started,
        },
        best_plan,
    )
