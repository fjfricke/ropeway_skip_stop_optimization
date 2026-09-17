"""Aggregate integer passenger master over exact service classes."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
import math
from time import perf_counter

from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..reservoir_cp_sat_certificate import DddReservoirCpPlan
from .certificate import representable_line_plan
from .preparation import PreparedLineProblem
from .service_classes import PreparedLineServiceClasses


@dataclass(frozen=True, slots=True)
class ServiceClassRideCount:
    class_id: str
    demand_group_id: str
    board_visit_index: int
    alight_visit_index: int
    count: int


@dataclass(frozen=True, slots=True)
class ReservoirPatternCandidate:
    rank: int
    served: int
    class_counts: tuple[tuple[str, int], ...]
    ride_counts: tuple[ServiceClassRideCount, ...]

    @property
    def used_fleet(self) -> int:
        return sum(value for _, value in self.class_counts)


@dataclass(frozen=True, slots=True)
class ReservoirPatternMasterConfig:
    time_limit_seconds: float = 60.0
    threads: int = 12
    memory_limit_gib: float = 32.0
    candidate_limit: int = 4
    seed: int = 0
    output_flag: bool = False
    maximum_ride_variables: int = 500_000

    def validate(self) -> None:
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("service-class master time limit must be positive")
        if type(self.threads) is not int or self.threads <= 0:
            raise ValueError("service-class master threads must be positive")
        if not math.isfinite(self.memory_limit_gib) or self.memory_limit_gib <= 0:
            raise ValueError("service-class master memory limit must be positive")
        if type(self.candidate_limit) is not int or not 1 <= self.candidate_limit <= 20:
            raise ValueError("service-class candidate limit must lie between 1 and 20")
        if type(self.seed) is not int:
            raise ValueError("service-class master seed must be an integer")
        if type(self.maximum_ride_variables) is not int or self.maximum_ride_variables <= 0:
            raise ValueError("service-class ride-variable limit must be positive")


@dataclass(frozen=True, slots=True)
class ReservoirPatternMasterResult:
    status: str
    objective_bound: float | None
    candidates: tuple[ReservoirPatternCandidate, ...]
    stats: dict
    solve_seconds: float

    @property
    def payload(self) -> dict:
        return {
            "status": self.status,
            "objective_bound": self.objective_bound,
            "candidates": [
                {**asdict(item), "used_fleet": item.used_fleet}
                for item in self.candidates
            ],
            "stats": self.stats,
            "solve_seconds": self.solve_seconds,
        }


def project_line_plan_to_service_classes(
    problem: DddReservoirCpSatProblem,
    prepared_line: PreparedLineProblem,
    prepared_classes: PreparedLineServiceClasses,
    plan: DddReservoirCpPlan,
) -> ReservoirPatternCandidate:
    """Project an independently valid no-wait line plan into aggregate classes."""
    represented = representable_line_plan(problem, prepared_line, plan)
    trips = {item.cabin_id: item for item in plan.trips}
    by_template: dict[str, list] = defaultdict(list)
    for item in prepared_classes.classes:
        by_template[item.template_id].append(item)
    class_id_by_cabin = {}
    for cabin_id, template_id in represented.template_id_by_cabin.items():
        dispatch = trips[cabin_id].switch_ticks[0]
        matches = [
            item
            for item in by_template[template_id]
            if item.minimum_dispatch_tick <= dispatch <= item.maximum_dispatch_tick
        ]
        if len(matches) != 1:
            raise ValueError("reference dispatch has no unique service class")
        class_id_by_cabin[cabin_id] = matches[0].id

    domain_rides = {item.id: item for item in problem.passenger_build.ride_candidates}
    counts: dict[tuple[str, str, int, int], int] = defaultdict(int)
    for ride_id, value in plan.ride_counts.items():
        if value <= 0:
            continue
        ride = domain_rides[ride_id]
        class_id = class_id_by_cabin[ride.cabin_id]
        service_class = prepared_classes.classes_by_id[class_id]
        key = (ride.demand_group_id, ride.board_visit_index, ride.alight_visit_index)
        if key not in service_class.ride_keys:
            raise ValueError("positive reference ride is absent from its service class")
        counts[class_id, *key] += value
    class_counts: dict[str, int] = defaultdict(int)
    for class_id in class_id_by_cabin.values():
        class_counts[class_id] += 1
    rides = tuple(
        ServiceClassRideCount(class_id, group_id, board, alight, value)
        for (class_id, group_id, board, alight), value in sorted(counts.items())
    )
    return ReservoirPatternCandidate(
        -1,
        sum(item.count for item in rides),
        tuple(sorted(class_counts.items())),
        rides,
    )


def _port_window_rows(classes, headway: int):
    """Necessary Hall rows for jobs with release/deadline on one port."""
    if headway <= 0:
        return ()
    windows = sorted(
        {(item.minimum_dispatch_tick, item.maximum_dispatch_tick) for item in classes}
    )
    rows = []
    for start, end in windows:
        contained = tuple(
            item.id
            for item in classes
            if start <= item.minimum_dispatch_tick
            and item.maximum_dispatch_tick <= end
        )
        if contained:
            rows.append((start, end, contained, (end - start) // headway + 1))
    return tuple(rows)


def solve_service_class_master(
    problem: DddReservoirCpSatProblem,
    prepared: PreparedLineServiceClasses,
    maximum_cabins: int,
    config: ReservoirPatternMasterConfig = ReservoirPatternMasterConfig(),
    *,
    build_only: bool = False,
) -> ReservoirPatternMasterResult:
    import gurobipy as gp
    from gurobipy import GRB

    config.validate()
    problem.validate()
    if prepared.problem_fingerprint != problem.fingerprint:
        raise ValueError("service classes belong to a different physical problem")
    if type(maximum_cabins) is not int or not 1 <= maximum_cabins <= problem.available_fleet_count:
        raise ValueError("service-class fleet limit is outside the available fleet")

    ride_variable_count = sum(len(item.rides) for item in prepared.classes)
    if ride_variable_count > config.maximum_ride_variables:
        return ReservoirPatternMasterResult(
            "MODEL_SIZE_LIMIT",
            None,
            (),
            {
                **prepared.stats,
                "variables": None,
                "integer_variables": None,
                "constraints": None,
                "nonzeros": None,
                "port_window_constraints": None,
                "master_bound_scope": "aggregate_no_wait_service_class_relaxation",
                "maximum_ride_variables": config.maximum_ride_variables,
                "size_limit_reason": (
                    f"{ride_variable_count} service-class ride variables exceed "
                    f"the configured limit {config.maximum_ride_variables}"
                ),
            },
            0.0,
        )

    started = perf_counter()
    model = gp.Model("reservoir_service_class_master")
    model.Params.OutputFlag = int(config.output_flag)
    model.Params.TimeLimit = config.time_limit_seconds
    model.Params.Threads = config.threads
    model.Params.SoftMemLimit = config.memory_limit_gib
    model.Params.Seed = config.seed
    model.Params.PoolSearchMode = 2
    model.Params.PoolSolutions = config.candidate_limit

    groups = {item.id: item for item in problem.demand_groups}
    class_count = {
        item.id: model.addVar(
            vtype=GRB.INTEGER, lb=0, ub=maximum_cabins, name=f"n::{item.id}"
        )
        for item in prepared.classes
    }
    ride_count = {}
    for item in prepared.classes:
        for ride in item.rides:
            key = (item.id, *ride.key)
            ride_count[key] = model.addVar(
                vtype=GRB.INTEGER,
                lb=0,
                ub=min(problem.cabin_capacity * maximum_cabins, groups[ride.demand_group_id].count),
                name="q::" + "::".join(map(str, key)),
            )
    model.update()
    model.addConstr(gp.quicksum(class_count.values()) <= maximum_cabins, "fleet")

    demand_terms = defaultdict(list)
    capacity_terms = defaultdict(list)
    for item in prepared.classes:
        for ride in item.rides:
            variable = ride_count[(item.id, *ride.key)]
            demand_terms[ride.demand_group_id].append(variable)
            for segment in range(ride.board_visit_index, ride.alight_visit_index):
                capacity_terms[item.id, segment].append(variable)
    for group_id, group in groups.items():
        model.addConstr(
            gp.quicksum(demand_terms[group_id]) <= group.count,
            f"demand::{group_id}",
        )
    for (class_id, segment), values in capacity_terms.items():
        model.addConstr(
            gp.quicksum(values)
            <= problem.cabin_capacity * class_count[class_id],
            f"capacity::{class_id}::{segment}",
        )

    headway = (
        None if problem.boundary_policy is None else problem.boundary_policy.headway_tick
    )
    port_rows = _port_window_rows(prepared.classes, headway or 0)
    for index, (_, _, class_ids, limit) in enumerate(port_rows):
        model.addConstr(
            gp.quicksum(class_count[class_id] for class_id in class_ids) <= limit,
            f"port_window::{index}",
        )

    model.setObjective(gp.quicksum(ride_count.values()), GRB.MAXIMIZE)
    if build_only:
        model.update()
        return ReservoirPatternMasterResult(
            "NOT_RUN",
            None,
            (),
            {
                **prepared.stats,
                "variables": model.NumVars,
                "integer_variables": model.NumIntVars,
                "constraints": model.NumConstrs,
                "nonzeros": model.NumNZs,
                "port_window_constraints": len(port_rows),
                "master_bound_scope": "aggregate_no_wait_service_class_relaxation",
            },
            0.0,
        )
    model.optimize()
    statuses = {
        GRB.OPTIMAL: "OPTIMAL",
        GRB.TIME_LIMIT: "TIME_LIMIT",
        GRB.INFEASIBLE: "INFEASIBLE",
        GRB.MEM_LIMIT: "MEMORY_LIMIT",
        GRB.INTERRUPTED: "INTERRUPTED",
    }
    status = statuses.get(model.Status, f"GUROBI_{model.Status}")
    candidates = []
    seen = set()
    for solution_number in range(min(model.SolCount, config.candidate_limit)):
        model.Params.SolutionNumber = solution_number
        counts = tuple(
            (item.id, int(round(class_count[item.id].Xn)))
            for item in prepared.classes
            if class_count[item.id].Xn > 0.5
        )
        if counts in seen:
            continue
        seen.add(counts)
        rides = tuple(
            ServiceClassRideCount(class_id, group_id, board, alight, int(round(var.Xn)))
            for (class_id, group_id, board, alight), var in ride_count.items()
            if var.Xn > 0.5
        )
        candidates.append(
            ReservoirPatternCandidate(
                len(candidates), sum(item.count for item in rides), counts, rides
            )
        )
    bound = None
    if model.Status not in (GRB.INFEASIBLE,) and math.isfinite(model.ObjBound):
        bound = float(model.ObjBound)
    return ReservoirPatternMasterResult(
        status,
        bound,
        tuple(candidates),
        {
            **prepared.stats,
            "variables": model.NumVars,
            "integer_variables": model.NumIntVars,
            "constraints": model.NumConstrs,
            "nonzeros": model.NumNZs,
            "port_window_constraints": len(port_rows),
            "master_bound_scope": "aggregate_no_wait_service_class_relaxation",
        },
        perf_counter() - started,
    )
