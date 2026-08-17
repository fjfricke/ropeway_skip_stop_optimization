from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from hashlib import sha256
from itertools import combinations
import json
import math
from time import perf_counter

import gurobipy as gp
from gurobipy import GRB
import numpy as np

from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryBoundStatus,
    DddTrajectoryWaitingDomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_resource_windows import (
    DddTrajectoryResourceWindowRow,
)


class DddTrajectoryPassengerLpStatus(StrEnum):
    OPTIMAL = "optimal"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"


class DddTrajectoryPassengerLpFormulation(StrEnum):
    FACTORIZED = "factorized"
    INTEGRATED_LOAD_PATTERN = "integrated_load_pattern"


class DddTrajectoryMasterDualMode(StrEnum):
    DEFAULT = "default"
    BARRIER_NO_CROSSOVER = "barrier_no_crossover"


@dataclass(frozen=True)
class DddTrajectoryPassengerRide:
    id: str
    demand_group_id: str
    upper_bound: float
    objective_delta: float
    onboard_segment_ids: tuple[str, ...]

    def validate(self) -> None:
        if not self.id or not self.demand_group_id:
            raise ValueError("trajectory Passenger ride IDs must not be empty")
        if not math.isfinite(self.upper_bound) or self.upper_bound <= 0:
            raise ValueError("trajectory Passenger ride upper bound must be positive")
        if not math.isfinite(self.objective_delta):
            raise ValueError("trajectory Passenger ride objective must be finite")
        if tuple(sorted(set(self.onboard_segment_ids))) != self.onboard_segment_ids:
            raise ValueError("trajectory Passenger onboard segments must be sorted")


@dataclass(frozen=True)
class DddTrajectoryPassengerOption:
    id: str
    cabin_id: int
    rides: tuple[DddTrajectoryPassengerRide, ...]

    def validate(self) -> None:
        if not self.id:
            raise ValueError("trajectory Passenger option ID must not be empty")
        if self.cabin_id < 0:
            raise ValueError("trajectory Passenger cabin ID must be nonnegative")
        ride_ids = tuple(ride.id for ride in self.rides)
        if tuple(sorted(set(ride_ids))) != ride_ids:
            raise ValueError("trajectory Passenger rides must have sorted unique IDs")
        for ride in self.rides:
            ride.validate()


@dataclass(frozen=True)
class DddTrajectoryPassengerMasterProblem:
    cabin_ids: tuple[int, ...]
    demand_by_group_id: dict[str, float]
    options: tuple[DddTrajectoryPassengerOption, ...]
    cabin_capacity: float
    objective_constant: float
    incompatibility_pairs: tuple[tuple[str, str], ...] = ()
    resource_window_rows: tuple[DddTrajectoryResourceWindowRow, ...] = ()
    incompatibility_rows_complete: bool = False
    trajectory_columns_complete: bool = False
    waiting_domain: DddTrajectoryWaitingDomain = DddTrajectoryWaitingDomain.NO_WAIT

    def validate(self) -> None:
        if not isinstance(self.waiting_domain, DddTrajectoryWaitingDomain):
            raise ValueError("trajectory Passenger master waiting domain is invalid")
        if tuple(sorted(set(self.cabin_ids))) != self.cabin_ids or not self.cabin_ids:
            raise ValueError("trajectory Passenger cabin IDs must be sorted and unique")
        if self.cabin_ids[0] < 0:
            raise ValueError("trajectory Passenger cabin IDs must be nonnegative")
        if not math.isfinite(self.cabin_capacity) or self.cabin_capacity <= 0:
            raise ValueError("trajectory Passenger capacity must be positive")
        if not math.isfinite(self.objective_constant):
            raise ValueError("trajectory Passenger objective constant must be finite")
        if not self.demand_by_group_id or any(
            not group_id or not math.isfinite(count) or count < 0
            for group_id, count in self.demand_by_group_id.items()
        ):
            raise ValueError(
                "trajectory Passenger demand must be finite and nonnegative"
            )
        option_ids = tuple(option.id for option in self.options)
        if tuple(sorted(set(option_ids))) != option_ids:
            raise ValueError("trajectory Passenger options must have sorted unique IDs")
        options_by_cabin_id = {cabin_id: 0 for cabin_id in self.cabin_ids}
        ride_ids: set[str] = set()
        for option in self.options:
            option.validate()
            if option.cabin_id not in options_by_cabin_id:
                raise ValueError("trajectory Passenger option has unknown cabin ID")
            options_by_cabin_id[option.cabin_id] += 1
            for ride in option.rides:
                if ride.id in ride_ids:
                    raise ValueError(
                        "trajectory Passenger ride IDs must be globally unique"
                    )
                ride_ids.add(ride.id)
                if ride.demand_group_id not in self.demand_by_group_id:
                    raise ValueError(
                        "trajectory Passenger ride has unknown demand group"
                    )
        if any(count == 0 for count in options_by_cabin_id.values()):
            raise ValueError("every cabin needs at least one trajectory option")
        normalized_pairs = tuple(
            sorted(tuple(sorted(pair)) for pair in self.incompatibility_pairs)
        )
        if normalized_pairs != self.incompatibility_pairs or len(
            set(normalized_pairs)
        ) != len(normalized_pairs):
            raise ValueError("trajectory incompatibility pairs must be normalized")
        known_options = set(option_ids)
        if any(
            len(pair) != 2 or pair[0] == pair[1] or not set(pair) <= known_options
            for pair in normalized_pairs
        ):
            raise ValueError("trajectory incompatibility pair is invalid")
        row_ids = tuple(row.id for row in self.resource_window_rows)
        if tuple(sorted(set(row_ids))) != row_ids:
            raise ValueError(
                "trajectory resource-window rows must have sorted unique IDs"
            )
        for row in self.resource_window_rows:
            row.validate()
            if not set(row.coefficient_by_option_id) <= known_options:
                raise ValueError(
                    "trajectory resource-window row references an unknown option"
                )

    @property
    def fingerprint(self) -> str:
        self.validate()
        payload = {
            "cabin_ids": self.cabin_ids,
            "demand": sorted(self.demand_by_group_id.items()),
            "capacity": self.cabin_capacity,
            "objective_constant": self.objective_constant,
            "incompatibilities": self.incompatibility_pairs,
            "resource_windows": [
                {
                    "id": row.id,
                    "capacity": row.window.capacity,
                    "coefficients": row.coefficients,
                }
                for row in self.resource_window_rows
            ],
            "incompatibility_rows_complete": self.incompatibility_rows_complete,
            "trajectory_columns_complete": self.trajectory_columns_complete,
            "waiting_domain": self.waiting_domain.value,
            "options": [
                {
                    "id": option.id,
                    "cabin_id": option.cabin_id,
                    "rides": [
                        {
                            "id": ride.id,
                            "group": ride.demand_group_id,
                            "upper": ride.upper_bound,
                            "cost": ride.objective_delta,
                            "segments": ride.onboard_segment_ids,
                        }
                        for ride in option.rides
                    ],
                }
                for option in self.options
            ],
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def with_demand_rhs(
        self, group_id: str, value: float
    ) -> DddTrajectoryPassengerMasterProblem:
        if group_id not in self.demand_by_group_id:
            raise ValueError("unknown trajectory Passenger demand group")
        demand = dict(self.demand_by_group_id)
        demand[group_id] = value
        return replace(self, demand_by_group_id=demand)


@dataclass(frozen=True)
class DddTrajectoryPassengerDuals:
    cabin_choice_raw_by_cabin_id: dict[int, float]
    demand_raw_by_group_id: dict[str, float]
    demand_marginal_value_by_group_id: dict[str, float]
    incompatibility_raw_by_pair: dict[tuple[str, str], float]
    ride_activation_raw_by_ride_id: dict[str, float]
    capacity_raw_by_option_segment: dict[tuple[str, str], float]
    fingerprint: str
    resource_window_raw_by_row_id: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class DddTrajectoryPassengerLpResult:
    status: DddTrajectoryPassengerLpStatus
    formulation: DddTrajectoryPassengerLpFormulation
    objective_value: float | None
    option_values_by_id: dict[str, float]
    ride_values_by_id: dict[str, float]
    pattern_values_by_id: dict[str, float]
    pattern_count: int
    incompatibility_constraint_count: int
    resource_window_constraint_count: int
    row_separation_complete: bool
    duals: DddTrajectoryPassengerDuals | None
    master_fingerprint: str
    build_seconds: float
    optimize_seconds: float
    total_seconds: float
    bound_status: DddTrajectoryBoundStatus = DddTrajectoryBoundStatus.PRIMAL_POOL_ONLY
    certified_lower_bound: float | None = None
    waiting_domain: DddTrajectoryWaitingDomain = DddTrajectoryWaitingDomain.NO_WAIT


@dataclass(frozen=True)
class DddTrajectoryPassengerMipResult:
    status: DddTrajectoryPassengerLpStatus
    objective_value: float | None
    option_values_by_id: dict[str, float]
    ride_values_by_id: dict[str, float]
    build_seconds: float
    optimize_seconds: float
    total_seconds: float


@dataclass(frozen=True)
class DddTrajectoryLoadPattern:
    id: str
    option_id: str
    ride_counts: tuple[tuple[str, float], ...]
    objective_delta: float


@dataclass(frozen=True)
class DddTrajectoryFactorizedLpOptimizer:
    output_flag: bool = False
    dual_mode: DddTrajectoryMasterDualMode = DddTrajectoryMasterDualMode.DEFAULT

    def solve(
        self,
        problem: DddTrajectoryPassengerMasterProblem,
    ) -> DddTrajectoryPassengerLpResult:
        problem.validate()
        if not isinstance(self.dual_mode, DddTrajectoryMasterDualMode):
            raise ValueError("trajectory master dual mode is invalid")
        started = perf_counter()
        model = gp.Model("ddd_trajectory_factorized_lp")
        model.Params.OutputFlag = int(self.output_flag)
        if self.dual_mode is DddTrajectoryMasterDualMode.BARRIER_NO_CROSSOVER:
            model.Params.Method = 2
            model.Params.Crossover = 0
        model.ModelSense = GRB.MINIMIZE
        model.ObjCon = problem.objective_constant

        select = {
            option.id: model.addVar(lb=0.0, ub=1.0, name=f"select[{index}]")
            for index, option in enumerate(problem.options)
        }
        ride = {
            item.id: model.addVar(
                lb=0.0,
                ub=item.upper_bound,
                obj=item.objective_delta,
                name=f"ride[{index}]",
            )
            for index, item in enumerate(_rides(problem))
        }
        choose = {
            cabin_id: model.addConstr(
                gp.quicksum(
                    select[option.id]
                    for option in problem.options
                    if option.cabin_id == cabin_id
                )
                == 1.0,
                name=f"choose_cabin[{cabin_id}]",
            )
            for cabin_id in problem.cabin_ids
        }
        demand = {
            group_id: model.addConstr(
                gp.quicksum(
                    ride[item.id]
                    for item in _rides(problem)
                    if item.demand_group_id == group_id
                )
                <= count,
                name=f"demand[{index}]",
            )
            for index, (group_id, count) in enumerate(
                sorted(problem.demand_by_group_id.items())
            )
        }
        activation = {}
        capacity = {}
        for option in problem.options:
            for item in option.rides:
                activation[item.id] = model.addConstr(
                    ride[item.id] <= item.upper_bound * select[option.id],
                    name=f"activate[{len(activation)}]",
                )
            for segment_id in _segment_ids(option):
                capacity[option.id, segment_id] = model.addConstr(
                    gp.quicksum(
                        ride[item.id]
                        for item in option.rides
                        if segment_id in item.onboard_segment_ids
                    )
                    <= problem.cabin_capacity * select[option.id],
                    name=f"capacity[{len(capacity)}]",
                )
        incompatible = {
            pair: model.addConstr(
                select[pair[0]] + select[pair[1]] <= 1.0,
                name=f"incompatible[{index}]",
            )
            for index, pair in enumerate(problem.incompatibility_pairs)
        }
        resource_windows = {
            row.id: model.addConstr(
                gp.quicksum(
                    coefficient * select[option_id]
                    for option_id, coefficient in row.coefficients
                )
                <= row.window.capacity,
                name=f"resource_window[{index}]",
            )
            for index, row in enumerate(problem.resource_window_rows)
        }
        build_seconds = perf_counter() - started
        optimize_started = perf_counter()
        model.optimize()
        optimize_seconds = perf_counter() - optimize_started
        return _lp_result(
            model=model,
            problem=problem,
            formulation=DddTrajectoryPassengerLpFormulation.FACTORIZED,
            select=select,
            ride=ride,
            pattern={},
            choose=choose,
            demand=demand,
            incompatible=incompatible,
            resource_windows=resource_windows,
            activation=activation,
            capacity=capacity,
            pattern_count=0,
            build_seconds=build_seconds,
            optimize_seconds=optimize_seconds,
            total_seconds=perf_counter() - started,
        )


@dataclass(frozen=True)
class DddTrajectoryFactorizedMipReferenceOptimizer:
    """Solve a finite complete trajectory master integrally for tiny references."""

    output_flag: bool = False

    def solve(
        self,
        problem: DddTrajectoryPassengerMasterProblem,
    ) -> DddTrajectoryPassengerMipResult:
        problem.validate()
        started = perf_counter()
        model = gp.Model("ddd_trajectory_factorized_mip_reference")
        model.Params.OutputFlag = int(self.output_flag)
        model.ModelSense = GRB.MINIMIZE
        model.ObjCon = problem.objective_constant

        select = {
            option.id: model.addVar(
                lb=0.0,
                ub=1.0,
                vtype=GRB.BINARY,
                name=f"select[{index}]",
            )
            for index, option in enumerate(problem.options)
        }
        ride = {
            item.id: model.addVar(
                lb=0.0,
                ub=item.upper_bound,
                obj=item.objective_delta,
                vtype=GRB.INTEGER,
                name=f"ride[{index}]",
            )
            for index, item in enumerate(_rides(problem))
        }
        for cabin_id in problem.cabin_ids:
            model.addConstr(
                gp.quicksum(
                    select[option.id]
                    for option in problem.options
                    if option.cabin_id == cabin_id
                )
                == 1.0,
                name=f"choose_cabin[{cabin_id}]",
            )
        for index, (group_id, count) in enumerate(
            sorted(problem.demand_by_group_id.items())
        ):
            model.addConstr(
                gp.quicksum(
                    ride[item.id]
                    for item in _rides(problem)
                    if item.demand_group_id == group_id
                )
                <= count,
                name=f"demand[{index}]",
            )
        for option in problem.options:
            for item in option.rides:
                model.addConstr(
                    ride[item.id] <= item.upper_bound * select[option.id],
                    name=f"activate[{item.id}]",
                )
            for segment_id in _segment_ids(option):
                model.addConstr(
                    gp.quicksum(
                        ride[item.id]
                        for item in option.rides
                        if segment_id in item.onboard_segment_ids
                    )
                    <= problem.cabin_capacity * select[option.id],
                    name=f"capacity[{option.id},{segment_id}]",
                )
        for index, pair in enumerate(problem.incompatibility_pairs):
            model.addConstr(
                select[pair[0]] + select[pair[1]] <= 1.0,
                name=f"incompatible[{index}]",
            )
        for index, row in enumerate(problem.resource_window_rows):
            model.addConstr(
                gp.quicksum(
                    coefficient * select[option_id]
                    for option_id, coefficient in row.coefficients
                )
                <= row.window.capacity,
                name=f"resource_window[{index}]",
            )
        build_seconds = perf_counter() - started
        optimize_started = perf_counter()
        model.optimize()
        optimize_seconds = perf_counter() - optimize_started
        status = _status(model.Status)
        objective_value = (
            float(model.ObjVal)
            if status is DddTrajectoryPassengerLpStatus.OPTIMAL
            else None
        )
        return DddTrajectoryPassengerMipResult(
            status=status,
            objective_value=objective_value,
            option_values_by_id=(
                {key: float(value.X) for key, value in select.items()}
                if objective_value is not None
                else {}
            ),
            ride_values_by_id=(
                {key: float(value.X) for key, value in ride.items()}
                if objective_value is not None
                else {}
            ),
            build_seconds=build_seconds,
            optimize_seconds=optimize_seconds,
            total_seconds=perf_counter() - started,
        )


@dataclass(frozen=True)
class DddTrajectoryIntegratedLpReferenceOptimizer:
    output_flag: bool = False
    tolerance: float = 1e-8
    max_ride_variables_per_option: int = 8
    max_active_sets_per_option: int = 250_000

    def solve(
        self,
        problem: DddTrajectoryPassengerMasterProblem,
    ) -> DddTrajectoryPassengerLpResult:
        problem.validate()
        started = perf_counter()
        patterns = tuple(
            pattern
            for option in problem.options
            for pattern in enumerate_ddd_trajectory_load_patterns(
                option,
                cabin_capacity=problem.cabin_capacity,
                tolerance=self.tolerance,
                max_ride_variables=self.max_ride_variables_per_option,
                max_active_sets=self.max_active_sets_per_option,
            )
        )
        patterns_by_option_id = {
            option.id: tuple(
                pattern for pattern in patterns if pattern.option_id == option.id
            )
            for option in problem.options
        }
        ride_by_id = _ride_by_id(problem)
        model = gp.Model("ddd_trajectory_integrated_lp_reference")
        model.Params.OutputFlag = int(self.output_flag)
        model.ModelSense = GRB.MINIMIZE
        model.ObjCon = problem.objective_constant
        theta = {
            pattern.id: model.addVar(
                lb=0.0,
                obj=pattern.objective_delta,
                name=f"pattern[{index}]",
            )
            for index, pattern in enumerate(patterns)
        }
        choose = {
            cabin_id: model.addConstr(
                gp.quicksum(
                    theta[pattern.id]
                    for option in problem.options
                    if option.cabin_id == cabin_id
                    for pattern in patterns_by_option_id[option.id]
                )
                == 1.0,
                name=f"choose_cabin[{cabin_id}]",
            )
            for cabin_id in problem.cabin_ids
        }
        demand = {
            group_id: model.addConstr(
                gp.quicksum(
                    count * theta[pattern.id]
                    for pattern in patterns
                    for ride_id, count in pattern.ride_counts
                    if ride_by_id[ride_id].demand_group_id == group_id
                )
                <= group_count,
                name=f"demand[{index}]",
            )
            for index, (group_id, group_count) in enumerate(
                sorted(problem.demand_by_group_id.items())
            )
        }
        incompatible = {
            pair: model.addConstr(
                gp.quicksum(
                    theta[pattern.id]
                    for option_id in pair
                    for pattern in patterns_by_option_id[option_id]
                )
                <= 1.0,
                name=f"incompatible[{index}]",
            )
            for index, pair in enumerate(problem.incompatibility_pairs)
        }
        resource_windows = {
            row.id: model.addConstr(
                gp.quicksum(
                    coefficient * theta[pattern.id]
                    for option_id, coefficient in row.coefficients
                    for pattern in patterns_by_option_id[option_id]
                )
                <= row.window.capacity,
                name=f"resource_window[{index}]",
            )
            for index, row in enumerate(problem.resource_window_rows)
        }
        build_seconds = perf_counter() - started
        optimize_started = perf_counter()
        model.optimize()
        optimize_seconds = perf_counter() - optimize_started
        option_values = (
            {
                option.id: sum(
                    theta[pattern.id].X for pattern in patterns_by_option_id[option.id]
                )
                for option in problem.options
            }
            if model.Status == GRB.OPTIMAL
            else {}
        )
        ride_values = (
            {
                ride_id: sum(
                    dict(pattern.ride_counts).get(ride_id, 0.0) * theta[pattern.id].X
                    for pattern in patterns
                )
                for ride_id in ride_by_id
            }
            if model.Status == GRB.OPTIMAL
            else {}
        )
        return _lp_result(
            model=model,
            problem=problem,
            formulation=DddTrajectoryPassengerLpFormulation.INTEGRATED_LOAD_PATTERN,
            select=option_values,
            ride=ride_values,
            pattern=theta,
            choose=choose,
            demand=demand,
            incompatible=incompatible,
            resource_windows=resource_windows,
            activation={},
            capacity={},
            pattern_count=len(patterns),
            build_seconds=build_seconds,
            optimize_seconds=optimize_seconds,
            total_seconds=perf_counter() - started,
        )


def enumerate_ddd_trajectory_load_patterns(
    option: DddTrajectoryPassengerOption,
    *,
    cabin_capacity: float,
    tolerance: float = 1e-8,
    max_ride_variables: int = 8,
    max_active_sets: int = 250_000,
) -> tuple[DddTrajectoryLoadPattern, ...]:
    option.validate()
    if cabin_capacity <= 0 or not math.isfinite(cabin_capacity):
        raise ValueError("trajectory load-pattern capacity must be positive")
    if tolerance < 0 or not math.isfinite(tolerance):
        raise ValueError("trajectory load-pattern tolerance must be nonnegative")
    dimension = len(option.rides)
    if dimension == 0:
        return (_load_pattern(option, np.zeros(0)),)
    if dimension > max_ride_variables:
        raise ValueError(
            "trajectory load-pattern reference exceeds ride-variable limit"
        )

    rows: list[np.ndarray] = []
    right_hand_sides: list[float] = []
    identity = np.eye(dimension)
    for index, ride in enumerate(option.rides):
        rows.append(-identity[index])
        right_hand_sides.append(0.0)
        rows.append(identity[index])
        right_hand_sides.append(ride.upper_bound)
    for segment_id in _segment_ids(option):
        row = np.array(
            [
                1.0 if segment_id in ride.onboard_segment_ids else 0.0
                for ride in option.rides
            ]
        )
        if any(np.array_equal(row, existing) for existing in rows):
            continue
        rows.append(row)
        right_hand_sides.append(cabin_capacity)
    matrix = np.array(rows, dtype=float)
    rhs = np.array(right_hand_sides, dtype=float)
    active_set_count = math.comb(len(rows), dimension)
    if active_set_count > max_active_sets:
        raise ValueError("trajectory load-pattern reference exceeds active-set limit")

    vertices: dict[tuple[float, ...], np.ndarray] = {}
    for active_indices in combinations(range(len(rows)), dimension):
        active = matrix[list(active_indices)]
        if np.linalg.matrix_rank(active, tol=tolerance) != dimension:
            continue
        point = np.linalg.solve(active, rhs[list(active_indices)])
        if np.any(matrix @ point - rhs > tolerance):
            continue
        point[np.abs(point) <= tolerance] = 0.0
        key = tuple(round(float(value), 10) for value in point)
        vertices.setdefault(key, point)
    if not vertices:
        raise RuntimeError("trajectory load-pattern reference found no vertices")
    return tuple(_load_pattern(option, vertices[key]) for key in sorted(vertices))


def _load_pattern(
    option: DddTrajectoryPassengerOption,
    values: np.ndarray,
) -> DddTrajectoryLoadPattern:
    ride_counts = tuple(
        (ride.id, float(value))
        for ride, value in zip(option.rides, values, strict=True)
        if value > 0.0
    )
    payload = json.dumps(
        {"option_id": option.id, "ride_counts": ride_counts},
        sort_keys=True,
        separators=(",", ":"),
    )
    return DddTrajectoryLoadPattern(
        id=f"ddd_load_pattern::{sha256(payload.encode()).hexdigest()}",
        option_id=option.id,
        ride_counts=ride_counts,
        objective_delta=sum(
            _ride_lookup(option, ride_id).objective_delta * count
            for ride_id, count in ride_counts
        ),
    )


def _lp_result(
    *,
    model: gp.Model,
    problem: DddTrajectoryPassengerMasterProblem,
    formulation: DddTrajectoryPassengerLpFormulation,
    select: dict[str, object],
    ride: dict[str, object],
    pattern: dict[str, gp.Var],
    choose: dict[int, gp.Constr],
    demand: dict[str, gp.Constr],
    incompatible: dict[tuple[str, str], gp.Constr],
    resource_windows: dict[str, gp.Constr],
    activation: dict[str, gp.Constr],
    capacity: dict[tuple[str, str], gp.Constr],
    pattern_count: int,
    build_seconds: float,
    optimize_seconds: float,
    total_seconds: float,
) -> DddTrajectoryPassengerLpResult:
    status = _status(model.Status)
    objective_value = (
        float(model.ObjVal)
        if status is DddTrajectoryPassengerLpStatus.OPTIMAL
        else None
    )
    option_values = (
        {
            option_id: float(value.X) if hasattr(value, "X") else float(value)
            for option_id, value in select.items()
        }
        if objective_value is not None
        else {}
    )
    ride_values = (
        {
            ride_id: float(value.X) if hasattr(value, "X") else float(value)
            for ride_id, value in ride.items()
        }
        if objective_value is not None
        else {}
    )
    pattern_values = (
        {pattern_id: float(variable.X) for pattern_id, variable in pattern.items()}
        if objective_value is not None
        else {}
    )
    duals = None
    if objective_value is not None:
        raw_demand = {key: float(row.Pi) for key, row in demand.items()}
        dual_payload = {
            "choice": sorted((key, float(row.Pi)) for key, row in choose.items()),
            "demand": sorted(raw_demand.items()),
            "incompatible": sorted(
                (pair, float(row.Pi)) for pair, row in incompatible.items()
            ),
            "resource_windows": sorted(
                (row_id, float(row.Pi)) for row_id, row in resource_windows.items()
            ),
            "activation": sorted(
                (key, float(row.Pi)) for key, row in activation.items()
            ),
            "capacity": sorted((key, float(row.Pi)) for key, row in capacity.items()),
        }
        duals = DddTrajectoryPassengerDuals(
            cabin_choice_raw_by_cabin_id={
                key: float(row.Pi) for key, row in choose.items()
            },
            demand_raw_by_group_id=raw_demand,
            demand_marginal_value_by_group_id={
                key: -value for key, value in raw_demand.items()
            },
            incompatibility_raw_by_pair={
                key: float(row.Pi) for key, row in incompatible.items()
            },
            ride_activation_raw_by_ride_id={
                key: float(row.Pi) for key, row in activation.items()
            },
            capacity_raw_by_option_segment={
                key: float(row.Pi) for key, row in capacity.items()
            },
            fingerprint=sha256(
                json.dumps(
                    dual_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            resource_window_raw_by_row_id={
                key: float(row.Pi) for key, row in resource_windows.items()
            },
        )
    if objective_value is None or not problem.trajectory_columns_complete:
        bound_status = DddTrajectoryBoundStatus.PRIMAL_POOL_ONLY
        certified_lower_bound = None
    elif problem.incompatibility_rows_complete:
        bound_status = DddTrajectoryBoundStatus.FULL_ROOT_LP_CERTIFIED
        certified_lower_bound = objective_value
    else:
        bound_status = DddTrajectoryBoundStatus.TRAJECTORY_RELAXATION_BOUND
        certified_lower_bound = objective_value
    return DddTrajectoryPassengerLpResult(
        status=status,
        formulation=formulation,
        objective_value=objective_value,
        option_values_by_id=option_values,
        ride_values_by_id=ride_values,
        pattern_values_by_id=pattern_values,
        pattern_count=pattern_count,
        incompatibility_constraint_count=len(problem.incompatibility_pairs),
        resource_window_constraint_count=len(problem.resource_window_rows),
        row_separation_complete=problem.incompatibility_rows_complete,
        duals=duals,
        master_fingerprint=sha256(
            f"{problem.fingerprint}:{formulation.value}".encode()
        ).hexdigest(),
        build_seconds=build_seconds,
        optimize_seconds=optimize_seconds,
        total_seconds=total_seconds,
        bound_status=bound_status,
        certified_lower_bound=certified_lower_bound,
        waiting_domain=problem.waiting_domain,
    )


def _status(status: int) -> DddTrajectoryPassengerLpStatus:
    if status == GRB.OPTIMAL:
        return DddTrajectoryPassengerLpStatus.OPTIMAL
    if status == GRB.INFEASIBLE:
        return DddTrajectoryPassengerLpStatus.INFEASIBLE
    return DddTrajectoryPassengerLpStatus.UNKNOWN


def _rides(
    problem: DddTrajectoryPassengerMasterProblem,
) -> tuple[DddTrajectoryPassengerRide, ...]:
    return tuple(ride for option in problem.options for ride in option.rides)


def _ride_by_id(
    problem: DddTrajectoryPassengerMasterProblem,
) -> dict[str, DddTrajectoryPassengerRide]:
    return {ride.id: ride for ride in _rides(problem)}


def _ride_lookup(
    option: DddTrajectoryPassengerOption,
    ride_id: str,
) -> DddTrajectoryPassengerRide:
    return next(ride for ride in option.rides if ride.id == ride_id)


def _segment_ids(option: DddTrajectoryPassengerOption) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                segment_id
                for ride in option.rides
                for segment_id in ride.onboard_segment_ids
            }
        )
    )
