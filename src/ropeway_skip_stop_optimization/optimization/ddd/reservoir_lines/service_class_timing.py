"""Exact CP-SAT timing and certificate expansion for service-class candidates."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import heapq
from time import perf_counter

from ortools.sat.python import cp_model

from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
)
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from .certificate import extract_line_plan
from .config import ReservoirLineConfig, ReservoirLineMode
from .cp_model import build_reservoir_line_model
from .preparation import PreparedLineProblem
from .service_class_master import ReservoirPatternCandidate
from .service_classes import PreparedLineServiceClasses


@dataclass(frozen=True, slots=True)
class ServiceClassTimingResult:
    status: str
    termination_reason: str
    plan: DddReservoirCpPlan | None
    validated_served: int | None
    class_id_by_cabin: tuple[tuple[int, str], ...]
    stats: dict
    solve_seconds: float

    @property
    def payload(self) -> dict:
        value = asdict(self)
        value["plan"] = None if self.plan is None else asdict(self.plan)
        return value


def _expand_passengers(
    problem: DddReservoirCpSatProblem,
    movement: DddReservoirCpPlan,
    candidate: ReservoirPatternCandidate,
    class_id_by_cabin: dict[int, str],
) -> DddReservoirCpPlan:
    cabins_by_class: dict[str, list[int]] = defaultdict(list)
    for cabin_id, class_id in class_id_by_cabin.items():
        cabins_by_class[class_id].append(cabin_id)
    candidate_ids = {
        (item.cabin_id, item.demand_group_id, item.board_visit_index, item.alight_visit_index): item.id
        for item in problem.passenger_build.ride_candidates
    }
    by_class: dict[str, list] = defaultdict(list)
    for item in candidate.ride_counts:
        by_class[item.class_id].append(item)

    result: dict[str, int] = defaultdict(int)
    for class_id, items in by_class.items():
        cabins = sorted(cabins_by_class.get(class_id, ()))
        if not cabins:
            raise ValueError("positive service-class flow has no timed cabin")
        track_count = len(cabins) * problem.cabin_capacity
        available = list(range(track_count))
        heapq.heapify(available)
        occupied: list[tuple[int, int]] = []
        units = []
        for item in sorted(
            items,
            key=lambda value: (
                value.board_visit_index,
                value.alight_visit_index,
                value.demand_group_id,
            ),
        ):
            units.extend([item] * item.count)
        for item in units:
            while occupied and occupied[0][0] <= item.board_visit_index:
                _, track = heapq.heappop(occupied)
                heapq.heappush(available, track)
            if not available:
                raise ValueError(
                    "aggregate service-class flow cannot be colored onto cabins"
                )
            track = heapq.heappop(available)
            cabin_id = cabins[track // problem.cabin_capacity]
            key = (
                cabin_id,
                item.demand_group_id,
                item.board_visit_index,
                item.alight_visit_index,
            )
            ride_id = candidate_ids.get(key)
            if ride_id is None:
                raise ValueError("expanded service-class ride is absent from the domain")
            result[ride_id] += 1
            heapq.heappush(occupied, (item.alight_visit_index, track))

    plan = DddReservoirCpPlan(movement.trips, dict(result))
    metrics = validate_reservoir_cp_plan(problem, plan)
    if metrics.served != candidate.served:
        raise RuntimeError("service-class expansion changed the master objective")
    return plan


def solve_service_class_timing(
    problem: DddReservoirCpSatProblem,
    prepared_line: PreparedLineProblem,
    prepared_classes: PreparedLineServiceClasses,
    candidate: ReservoirPatternCandidate,
    base_config: ReservoirLineConfig,
    *,
    time_limit_seconds: float,
) -> ServiceClassTimingResult:
    started = perf_counter()
    counts = candidate.class_counts
    total = candidate.used_fleet
    timing_config = ReservoirLineConfig(
        dispatch_window_end_seconds=base_config.dispatch_window_end_seconds,
        passenger_service_start_seconds=base_config.passenger_service_start_seconds,
        variant=base_config.variant,
        preparation=base_config.preparation,
        formulation=base_config.formulation,
        mode=ReservoirLineMode.FEASIBILITY,
        catalog_profile=base_config.catalog_profile,
        maximum_cabins=base_config.maximum_cabins,
        fixed_cabins=total,
        fixed_service_class_counts=counts,
        time_limit_seconds=time_limit_seconds,
        workers=base_config.workers,
        memory_limit_gib=base_config.memory_limit_gib,
        seed=base_config.seed,
        log_search_progress=base_config.log_search_progress,
        presolve=base_config.presolve,
    )
    built = build_reservoir_line_model(
        problem,
        prepared_line,
        timing_config,
        service_classes=prepared_classes,
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = timing_config.workers
    solver.parameters.random_seed = timing_config.seed
    solver.parameters.max_memory_in_mb = int(timing_config.memory_limit_gib * 1024)
    solver.parameters.cp_model_presolve = timing_config.presolve
    solver.parameters.log_search_progress = timing_config.log_search_progress
    before = perf_counter()
    code = solver.solve(built.model)
    solve_seconds = perf_counter() - before
    status = solver.status_name(code)
    if code not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return ServiceClassTimingResult(
            status,
            "INFEASIBLE" if code == cp_model.INFEASIBLE else "TIME_LIMIT",
            None,
            None,
            (),
            {**built.stats, "response_stats": solver.response_stats()},
            solve_seconds,
        )
    movement = extract_line_plan(
        problem, prepared_line, built, solver.value, include_rides=False
    )
    selected = {
        cabin_id: class_id
        for (cabin_id, class_id), variable in built.service_class_selection.items()
        if solver.value(variable)
    }
    plan = _expand_passengers(problem, movement, candidate, selected)
    metrics = validate_reservoir_cp_plan(problem, plan)
    return ServiceClassTimingResult(
        status,
        "OPTIMAL" if code == cp_model.OPTIMAL else "FEASIBLE",
        plan,
        metrics.served,
        tuple(sorted(selected.items())),
        {
            **built.stats,
            "response_stats": solver.response_stats(),
            "total_wall_seconds": perf_counter() - started,
        },
        solve_seconds,
    )
