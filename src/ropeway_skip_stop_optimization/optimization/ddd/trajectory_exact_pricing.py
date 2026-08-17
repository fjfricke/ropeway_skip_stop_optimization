from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from time import perf_counter

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddFixedStart,
    DddMovementProblem,
    DddRouteOption,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceConflictError,
    DddReferenceTrajectory,
    build_ddd_reference_visit,
    validate_ddd_reference_trajectory,
)
from ropeway_skip_stop_optimization.optimization.ddd.route_topology import (
    deterministic_route_state_ids,
    unique_stop_route_option,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    DDD_TIME_TICK_SECONDS,
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryWaitingDomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_exhaustive_reference import (
    DddExhaustiveTrajectoryMasterBuildResult,
    ddd_trajectory_instance_fingerprint,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryPassengerDuals,
    DddTrajectoryPassengerOption,
    ddd_trajectory_passenger_segment_ids,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_resource_windows import (
    DddTrajectoryResourceWindowPricingTerm,
    DddTrajectoryResourceWindowRow,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_slot import (
    ddd_trajectory_column,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
    EanPassengerObjectiveEvent,
    ean_passenger_objective_definition,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanFleetMode,
    StationWaitingMode,
)


class DddTrajectoryExactPricingStatus(StrEnum):
    OPTIMAL = "optimal"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class DddTrajectoryPricingFormulation(StrEnum):
    LEGACY_INDICATORS = "legacy_indicators"
    TIGHT_CONVEX_HULL = "tight_convex_hull"
    TIME_EXPANDED_PATH = "time_expanded_path"


@dataclass(frozen=True)
class DddTrajectoryExactPricingResult:
    cabin_id: int
    status: DddTrajectoryExactPricingStatus
    minimum_reduced_cost: float
    exact: bool
    option_id: str | None
    reference_trajectory: DddReferenceTrajectory | None
    ride_counts_by_candidate_id: dict[str, int]
    solve_seconds: float
    certified_reduced_cost_lower_bound: float | None = None
    self_conflict_round_count: int = 0
    detail: str | None = None
    model_variable_count: int = 0
    model_linear_constraint_count: int = 0
    model_general_constraint_count: int = 0
    solver_node_count: float = 0.0

    def __post_init__(self) -> None:
        if self.cabin_id < 0:
            raise ValueError("exact trajectory pricing cabin ID must be nonnegative")
        if not math.isfinite(self.minimum_reduced_cost):
            raise ValueError("exact trajectory pricing reduced cost must be finite")
        if self.certified_reduced_cost_lower_bound is not None and not math.isfinite(
            self.certified_reduced_cost_lower_bound
        ):
            raise ValueError("exact trajectory pricing bound must be finite")
        if self.exact and (
            self.certified_reduced_cost_lower_bound is not None
            and self.certified_reduced_cost_lower_bound
            > self.minimum_reduced_cost + 1e-9
        ):
            raise ValueError("exact trajectory pricing bound exceeds its optimum")
        if self.solve_seconds < 0 or not math.isfinite(self.solve_seconds):
            raise ValueError("exact trajectory pricing time must be nonnegative")
        if self.self_conflict_round_count < 0:
            raise ValueError("exact trajectory pricing conflict rounds are invalid")
        if (
            min(
                self.model_variable_count,
                self.model_linear_constraint_count,
                self.model_general_constraint_count,
            )
            < 0
        ):
            raise ValueError("exact trajectory pricing model size is invalid")
        if self.solver_node_count < 0 or not math.isfinite(self.solver_node_count):
            raise ValueError("exact trajectory pricing node count is invalid")
        if any(value <= 0 for value in self.ride_counts_by_candidate_id.values()):
            raise ValueError("exact trajectory pricing ride counts must be positive")
        has_column = self.option_id is not None
        if has_column != (self.reference_trajectory is not None):
            raise ValueError("exact trajectory pricing column payload is incomplete")


@dataclass(frozen=True)
class DddTrajectoryExhaustivePricingOracle:
    """Exact reduced-cost oracle over an explicitly complete tiny trajectory set."""

    output_flag: bool = False

    def solve(
        self,
        *,
        exhaustive: DddExhaustiveTrajectoryMasterBuildResult,
        cabin_id: int,
        duals: DddTrajectoryPassengerDuals,
        excluded_option_ids: frozenset[str] = frozenset(),
    ) -> DddTrajectoryExactPricingResult:
        started = perf_counter()
        options = tuple(
            option
            for option in exhaustive.master_problem.options
            if option.cabin_id == cabin_id and option.id not in excluded_option_ids
        )
        if not options:
            return DddTrajectoryExactPricingResult(
                cabin_id=cabin_id,
                status=DddTrajectoryExactPricingStatus.EXHAUSTED,
                minimum_reduced_cost=0.0,
                exact=True,
                option_id=None,
                reference_trajectory=None,
                ride_counts_by_candidate_id={},
                solve_seconds=perf_counter() - started,
                certified_reduced_cost_lower_bound=0.0,
            )
        alpha = duals.cabin_choice_raw_by_cabin_id[cabin_id]
        best_value = math.inf
        best_option: DddTrajectoryPassengerOption | None = None
        best_counts: dict[str, int] = {}
        for option in options:
            model = gp.Model("ddd_trajectory_exhaustive_pricing_reference")
            model.Params.OutputFlag = int(self.output_flag)
            model.ModelSense = GRB.MINIMIZE
            window_penalty = sum(
                -duals.resource_window_raw_by_row_id.get(row.id, 0.0)
                * row.coefficient_by_option_id.get(option.id, 0)
                for row in exhaustive.master_problem.resource_window_rows
            )
            model.ObjCon = -alpha + window_penalty
            ride = {
                item.id: model.addVar(
                    lb=0.0,
                    ub=item.upper_bound,
                    obj=(
                        item.objective_delta
                        - duals.demand_raw_by_group_id.get(
                            item.demand_group_id,
                            0.0,
                        )
                    ),
                    name=f"ride[{index}]",
                )
                for index, item in enumerate(option.rides)
            }
            for segment_id in ddd_trajectory_passenger_segment_ids(option):
                model.addConstr(
                    gp.quicksum(
                        ride[item.id]
                        for item in option.rides
                        if segment_id in item.onboard_segment_ids
                    )
                    <= exhaustive.master_problem.cabin_capacity
                )
            model.optimize()
            if model.Status != GRB.OPTIMAL:
                raise RuntimeError("exhaustive trajectory pricing LP did not optimize")
            if model.ObjVal < best_value - 1e-9:
                best_value = float(model.ObjVal)
                best_option = option
                best_counts = {
                    item.id.removeprefix(f"{option.id}::"): int(round(ride[item.id].X))
                    for item in option.rides
                    if ride[item.id].X > 1e-7
                }
        if best_option is None:
            raise RuntimeError("exhaustive trajectory pricing found no option")
        return DddTrajectoryExactPricingResult(
            cabin_id=cabin_id,
            status=DddTrajectoryExactPricingStatus.OPTIMAL,
            minimum_reduced_cost=best_value,
            exact=True,
            option_id=best_option.id,
            reference_trajectory=(
                exhaustive.reference_trajectory_by_option_id[best_option.id]
            ),
            ride_counts_by_candidate_id=best_counts,
            solve_seconds=perf_counter() - started,
            certified_reduced_cost_lower_bound=best_value,
        )


@dataclass(frozen=True)
class DddTrajectoryExactNoWaitPricingOracle:
    """Exact single-cabin route-and-load MILP for the no-wait pricing domain."""

    time_limit_seconds: float = 30.0
    threads: int = 1
    output_flag: bool = False
    mip_focus: int = 2
    formulation: DddTrajectoryPricingFormulation = (
        DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH
    )
    max_self_conflict_rounds: int = 1_000
    tolerance_seconds: float = 1e-9

    def solve(
        self,
        *,
        movement_problem: DddMovementProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        cabin_id: int,
        duals: DddTrajectoryPassengerDuals,
        excluded_route_option_sequences: frozenset[tuple[str, ...]] = frozenset(),
        resource_window_rows: tuple[DddTrajectoryResourceWindowRow, ...] = (),
    ) -> DddTrajectoryExactPricingResult:
        started = perf_counter()
        self._validate(
            movement_problem,
            artifact,
            passenger_build,
            cabin_id,
            duals,
            resource_window_rows,
        )
        start = next(
            item for item in movement_problem.starts if item.cabin_id == cabin_id
        )
        model_data = _build_exact_pricing_model(
            movement_problem=movement_problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=objective,
            start=start,
            duals=duals,
            output_flag=self.output_flag,
            threads=self.threads,
            mip_focus=self.mip_focus,
            formulation=self.formulation,
            excluded_route_option_sequences=excluded_route_option_sequences,
            resource_window_rows=resource_window_rows,
        )
        self_conflict_round_count = 0
        certified_lower_bound: float | None = None
        while True:
            remaining = self.time_limit_seconds - (perf_counter() - started)
            if remaining <= 0:
                return _unknown_result(
                    cabin_id,
                    started,
                    self_conflict_round_count,
                    "exact trajectory pricing time budget exhausted",
                    certified_lower_bound=certified_lower_bound,
                    model_data=model_data,
                )
            model_data.model.Params.TimeLimit = remaining
            model_data.model.optimize()
            solver_bound = _finite_model_objective_bound(model_data.model)
            if solver_bound is not None:
                certified_lower_bound = (
                    solver_bound
                    if certified_lower_bound is None
                    else max(certified_lower_bound, solver_bound)
                )
            if model_data.model.Status == GRB.INFEASIBLE:
                return DddTrajectoryExactPricingResult(
                    cabin_id=cabin_id,
                    status=DddTrajectoryExactPricingStatus.EXHAUSTED,
                    minimum_reduced_cost=0.0,
                    exact=True,
                    option_id=None,
                    reference_trajectory=None,
                    ride_counts_by_candidate_id={},
                    solve_seconds=perf_counter() - started,
                    certified_reduced_cost_lower_bound=0.0,
                    self_conflict_round_count=self_conflict_round_count,
                    **_pricing_model_metrics(model_data),
                )
            if model_data.model.Status != GRB.OPTIMAL:
                incumbent = _extract_valid_incumbent_result(
                    movement_problem=movement_problem,
                    artifact=artifact,
                    cabin_id=cabin_id,
                    start=start,
                    model_data=model_data,
                    started=started,
                    self_conflict_round_count=self_conflict_round_count,
                    certified_lower_bound=certified_lower_bound,
                    tolerance_seconds=self.tolerance_seconds,
                    detail=(
                        "exact trajectory pricing solver status "
                        f"{model_data.model.Status} with an uncertified incumbent"
                    ),
                )
                if incumbent is not None:
                    return incumbent
                return _unknown_result(
                    cabin_id,
                    started,
                    self_conflict_round_count,
                    f"exact trajectory pricing solver status {model_data.model.Status}",
                    certified_lower_bound=certified_lower_bound,
                    model_data=model_data,
                )
            trajectory = _extract_reference_trajectory(
                movement_problem,
                start,
                model_data,
                tolerance_seconds=self.tolerance_seconds,
            )
            try:
                validate_ddd_reference_trajectory(
                    movement_problem,
                    trajectory,
                    tolerance_seconds=self.tolerance_seconds,
                )
            except DddReferenceResourceConflictError:
                if self_conflict_round_count >= self.max_self_conflict_rounds:
                    return _unknown_result(
                        cabin_id,
                        started,
                        self_conflict_round_count,
                        "exact trajectory pricing self-conflict budget exhausted",
                        certified_lower_bound=certified_lower_bound,
                        model_data=model_data,
                    )
                _exclude_route_sequence(
                    model_data.model,
                    model_data.route_selection,
                    trajectory.support_signature,
                    name=f"self_conflict[{self_conflict_round_count}]",
                )
                self_conflict_round_count += 1
                model_data.model.update()
                continue
            column = ddd_trajectory_column(
                trajectory,
                instance_fingerprint=ddd_trajectory_instance_fingerprint(artifact),
            )
            return DddTrajectoryExactPricingResult(
                cabin_id=cabin_id,
                status=DddTrajectoryExactPricingStatus.OPTIMAL,
                minimum_reduced_cost=float(model_data.model.ObjVal),
                exact=True,
                option_id=column.id,
                reference_trajectory=trajectory,
                ride_counts_by_candidate_id=_extract_ride_counts(model_data),
                solve_seconds=perf_counter() - started,
                certified_reduced_cost_lower_bound=float(model_data.model.ObjVal),
                self_conflict_round_count=self_conflict_round_count,
                **_pricing_model_metrics(model_data),
            )

    def _validate(
        self,
        movement_problem: DddMovementProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        cabin_id: int,
        duals: DddTrajectoryPassengerDuals,
        resource_window_rows: tuple[DddTrajectoryResourceWindowRow, ...],
    ) -> None:
        movement_problem.validate()
        artifact.validate()
        passenger_build.validate()
        if movement_problem.scenario_id != artifact.scenario_id:
            raise ValueError("exact trajectory pricing instance differs")
        if artifact.fleet_mode is not EanFleetMode.FIXED_STARTS:
            raise ValueError("exact trajectory pricing supports fixed starts only")
        if any(
            item.waiting_mode is not StationWaitingMode.NO_WAITING
            for item in artifact.config.station_configs
        ):
            raise ValueError("exact trajectory pricing supports no-wait only")
        if cabin_id not in {start.cabin_id for start in movement_problem.starts}:
            raise ValueError("exact trajectory pricing cabin is unknown")
        if cabin_id not in duals.cabin_choice_raw_by_cabin_id:
            raise ValueError("exact trajectory pricing cabin dual is missing")
        if self.time_limit_seconds <= 0:
            raise ValueError("exact trajectory pricing time limit must be positive")
        if self.threads <= 0:
            raise ValueError("exact trajectory pricing threads must be positive")
        if self.mip_focus not in range(4):
            raise ValueError("exact trajectory pricing MIP focus is invalid")
        if not isinstance(self.formulation, DddTrajectoryPricingFormulation):
            raise ValueError("exact trajectory pricing formulation is invalid")
        if self.max_self_conflict_rounds < 0:
            raise ValueError("exact trajectory pricing conflict budget is invalid")
        row_ids = tuple(row.id for row in resource_window_rows)
        if tuple(sorted(set(row_ids))) != row_ids:
            raise ValueError("exact pricing resource-window rows are not normalized")
        if set(duals.resource_window_raw_by_row_id) != set(row_ids):
            raise ValueError("exact pricing resource-window duals and rows differ")
        for row in resource_window_rows:
            row.validate()
            if row.window.waiting_domain is not DddTrajectoryWaitingDomain.NO_WAIT:
                raise ValueError("exact no-wait pricing received a Waiting window")
            if row.window.resource_id not in movement_problem.resources_by_id:
                raise ValueError("exact pricing window references an unknown resource")
            DddTrajectoryResourceWindowPricingTerm(
                window=row.window,
                raw_dual=duals.resource_window_raw_by_row_id[row.id],
            ).validate()


@dataclass
class _ExactPricingModel:
    model: gp.Model
    start: DddFixedStart
    states: tuple[str, ...]
    event_time: tuple[gp.Var, ...]
    active: tuple[gp.Var, ...]
    route_selection: dict[tuple[int, str], gp.Var]
    ride_count_bits: dict[str, tuple[tuple[int, gp.Var], ...]]
    ride_count_expressions: dict[str, gp.LinExpr]
    resource_window_membership: dict[tuple[str, int, str, int], gp.Var]


def _build_exact_pricing_model(
    *,
    movement_problem: DddMovementProblem,
    artifact: EanBuildArtifact,
    passenger_build: EanPassengerCandidateBuildResult,
    objective: EanPassengerObjective,
    start: DddFixedStart,
    duals: DddTrajectoryPassengerDuals,
    output_flag: bool,
    threads: int,
    mip_focus: int,
    formulation: DddTrajectoryPricingFormulation,
    excluded_route_option_sequences: frozenset[tuple[str, ...]],
    resource_window_rows: tuple[DddTrajectoryResourceWindowRow, ...],
) -> _ExactPricingModel:
    model = gp.Model(f"ddd_exact_pricing_cabin_{start.cabin_id}")
    model.Params.OutputFlag = int(output_flag)
    model.Params.MIPGap = 0.0
    model.Params.Threads = threads
    model.Params.MIPFocus = mip_focus
    model.ModelSense = GRB.MINIMIZE
    model.ObjCon = -duals.cabin_choice_raw_by_cabin_id[start.cabin_id]
    states = deterministic_route_state_ids(
        movement_problem,
        start_state_id=start.state_id,
        max_visit_count=start.max_visit_count,
        error_context="exact trajectory pricing",
    )
    event_time_bounds = _event_time_bounds(
        movement_problem=movement_problem,
        start=start,
        states=states,
        formulation=formulation,
    )
    active_event_time_bounds = _active_event_time_bounds(
        movement_problem=movement_problem,
        start=start,
        states=states,
    )
    if formulation is DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH:
        (
            event_time,
            active,
            route_selection,
            active_time_membership,
            route_time_membership,
            time_expanded_arcs,
        ) = _add_time_expanded_route_core(
            model=model,
            movement_problem=movement_problem,
            start=start,
            states=states,
            event_time_bounds=event_time_bounds,
        )
    else:
        event_time, active, route_selection = _add_compact_route_core(
            model=model,
            movement_problem=movement_problem,
            start=start,
            states=states,
            event_time_bounds=event_time_bounds,
        )
        active_time_membership = {}
        route_time_membership = {}
        time_expanded_arcs = ()
    for index, sequence in enumerate(sorted(excluded_route_option_sequences)):
        _exclude_route_sequence(
            model,
            route_selection,
            sequence,
            name=f"excluded[{index}]",
        )

    resource_window_membership = _add_resource_window_pricing_terms(
        model=model,
        movement_problem=movement_problem,
        states=states,
        event_time=event_time,
        route_selection=route_selection,
        rows=resource_window_rows,
        duals=duals,
    )

    definition = ean_passenger_objective_definition(objective)
    group_by_id = {group.id: group for group in passenger_build.demand_groups}
    earliest_event_time = [start.time_tick]
    for state_id in states[:-1]:
        earliest_event_time.append(
            earliest_event_time[-1]
            + min(
                option.duration_tick
                for option in movement_problem.route_options_by_state_id[state_id]
            )
        )
    ride_count_bits: dict[str, tuple[tuple[int, gp.Var], ...]] = {}
    ride_count_expressions: dict[str, gp.LinExpr] = {}
    passenger_flow_by_candidate_arc: dict[tuple[str, int, int, str], gp.Var] = {}
    for candidate in sorted(passenger_build.ride_candidates, key=lambda item: item.id):
        if candidate.cabin_id != start.cabin_id:
            continue
        if candidate.alight_visit_index >= start.max_visit_count:
            continue
        if any(
            active_event_time_bounds[visit_index][0]
            > active_event_time_bounds[visit_index][1]
            for visit_index in (
                candidate.board_visit_index,
                candidate.alight_visit_index,
            )
        ):
            continue
        board_stop = unique_stop_route_option(
            movement_problem,
            states[candidate.board_visit_index],
            error_context="exact trajectory pricing",
        )
        alight_stop = unique_stop_route_option(
            movement_problem,
            states[candidate.alight_visit_index],
            error_context="exact trajectory pricing",
        )
        if (
            board_stop.platform_exit_offset_seconds is None
            or alight_stop.platform_entry_offset_seconds is None
        ):
            raise RuntimeError("exact trajectory pricing STOP offsets are missing")
        board_offset = ddd_seconds_to_tick(board_stop.platform_exit_offset_seconds)
        alight_offset = ddd_seconds_to_tick(alight_stop.platform_entry_offset_seconds)
        event_index, event_offset = (
            (candidate.board_visit_index, board_offset)
            if definition.event is EanPassengerObjectiveEvent.BOARDING
            else (candidate.alight_visit_index, alight_offset)
        )
        group = group_by_id[candidate.demand_group_id]
        upper_value = min(group.count, artifact.config.cabin_capacity)
        upper = int(round(upper_value))
        if upper <= 0 or not math.isclose(upper_value, upper, abs_tol=1e-9):
            raise ValueError(
                "exact trajectory pricing requires integral passenger counts "
                "and cabin capacity"
            )
        raw_demand_dual = duals.demand_raw_by_group_id.get(group.id, 0.0)
        earliest_alight = (
            earliest_event_time[candidate.alight_visit_index] + alight_offset
        )
        earliest_priced_event = earliest_event_time[event_index] + event_offset
        optimistic_unit_reduced_cost = (
            ddd_tick_to_seconds(earliest_priced_event)
            - artifact.config.horizon_seconds
            - raw_demand_dual
        )
        if (
            earliest_alight > movement_problem.passenger_service_end_tick
            or optimistic_unit_reduced_cost >= 0.0
        ):
            continue
        if formulation is DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH:
            flow_by_arc = _add_time_expanded_ride_flow(
                model=model,
                candidate_id=candidate.id,
                board_visit_index=candidate.board_visit_index,
                alight_visit_index=candidate.alight_visit_index,
                board_option_id=board_stop.id,
                alight_option_id=alight_stop.id,
                board_offset=board_offset,
                alight_offset=alight_offset,
                release_tick=ddd_seconds_to_tick(group.release_time_seconds),
                service_end_tick=movement_problem.passenger_service_end_tick,
                objective_event=definition.event,
                constant_unit_cost=(-artifact.config.horizon_seconds - raw_demand_dual),
                upper=upper,
                arcs=time_expanded_arcs,
            )
            if not flow_by_arc:
                continue
            passenger_flow_by_candidate_arc.update(
                {
                    (candidate.id, visit_index, source_tick, option_id): variable
                    for (
                        visit_index,
                        source_tick,
                        option_id,
                    ), variable in flow_by_arc.items()
                }
            )
            ride_count_expressions[candidate.id] = gp.quicksum(
                variable
                for (visit_index, _, _), variable in flow_by_arc.items()
                if visit_index == candidate.board_visit_index
            )
            continue
        used = model.addVar(
            vtype=GRB.BINARY,
            name=f"ride_used[{candidate.id}]",
        )
        bits = []
        for bit_index in range(upper.bit_length()):
            weight = 1 << bit_index
            bit = model.addVar(
                vtype=GRB.BINARY,
                obj=(-weight * (artifact.config.horizon_seconds + raw_demand_dual)),
                name=f"ride_bit[{candidate.id},{bit_index}]",
            )
            if formulation is DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH:
                timed_bit = {
                    tick: model.addVar(
                        lb=0.0,
                        ub=1.0,
                        obj=weight * DDD_TIME_TICK_SECONDS * (tick + event_offset),
                        name=(f"ride_event_time[{candidate.id},{bit_index},{index}]"),
                    )
                    for index, ((visit_index, tick), _) in enumerate(
                        sorted(active_time_membership.items())
                    )
                    if visit_index == event_index
                }
                model.addConstr(
                    gp.quicksum(timed_bit.values()) == bit,
                    name=f"ride_event_time_sum[{candidate.id},{bit_index}]",
                )
                for tick, variable in timed_bit.items():
                    model.addConstr(
                        variable <= active_time_membership[event_index, tick],
                        name=(
                            f"ride_event_time_link[{candidate.id},{bit_index},{tick}]"
                        ),
                    )
            else:
                product_upper = min(
                    movement_problem.passenger_service_end_tick,
                    active_event_time_bounds[event_index][1] + event_offset,
                )
                event_product = model.addVar(
                    lb=0.0,
                    ub=float(product_upper),
                    obj=weight * DDD_TIME_TICK_SECONDS,
                    name=f"ride_event_bit[{candidate.id},{bit_index}]",
                )
            if formulation is DddTrajectoryPricingFormulation.LEGACY_INDICATORS:
                model.addGenConstrIndicator(
                    bit,
                    True,
                    event_product == event_time[event_index] + event_offset,
                    name=f"ride_event_on[{candidate.id},{bit_index}]",
                )
                model.addGenConstrIndicator(
                    bit,
                    False,
                    event_product == 0,
                    name=f"ride_event_off[{candidate.id},{bit_index}]",
                )
            elif formulation is DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL:
                _add_binary_event_product_convex_hull(
                    model=model,
                    product=event_product,
                    binary=bit,
                    event_time=event_time[event_index],
                    event_offset=event_offset,
                    global_event_lower=event_time_bounds[event_index][0],
                    global_event_upper=event_time_bounds[event_index][1],
                    active_event_lower=active_event_time_bounds[event_index][0],
                    active_event_upper=active_event_time_bounds[event_index][1],
                    name=f"ride_event_product[{candidate.id},{bit_index}]",
                )
            bits.append((weight, bit))
        ride_count = gp.quicksum(weight * bit for weight, bit in bits)
        model.addConstr(
            ride_count <= upper * used,
            name=f"ride_count_used_upper[{candidate.id}]",
        )
        model.addConstr(
            ride_count >= used,
            name=f"ride_count_used_lower[{candidate.id}]",
        )
        model.addConstr(
            ride_count <= upper,
            name=f"ride_count_upper[{candidate.id}]",
        )
        model.addConstr(
            used <= route_selection[candidate.board_visit_index, board_stop.id],
            name=f"ride_board_stop[{candidate.id}]",
        )
        model.addConstr(
            used <= route_selection[candidate.alight_visit_index, alight_stop.id],
            name=f"ride_alight_stop[{candidate.id}]",
        )
        if formulation is DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH:
            release_tick = ddd_seconds_to_tick(group.release_time_seconds)
            board_path_mass = gp.quicksum(
                variable
                for (
                    visit_index,
                    option_id,
                    tick,
                ), variable in route_time_membership.items()
                if visit_index == candidate.board_visit_index
                and option_id == board_stop.id
                and tick + board_offset >= release_tick
            )
            alight_path_mass = gp.quicksum(
                variable
                for (
                    visit_index,
                    option_id,
                    tick,
                ), variable in route_time_membership.items()
                if visit_index == candidate.alight_visit_index
                and option_id == alight_stop.id
                and tick + alight_offset <= movement_problem.passenger_service_end_tick
            )
            model.addConstr(
                ride_count <= upper * board_path_mass,
                name=f"ride_board_time_path[{candidate.id}]",
            )
            model.addConstr(
                ride_count <= upper * alight_path_mass,
                name=f"ride_alight_time_path[{candidate.id}]",
            )
        model.addGenConstrIndicator(
            used,
            True,
            event_time[candidate.board_visit_index] + board_offset
            >= ddd_seconds_to_tick(group.release_time_seconds),
            name=f"ride_release[{candidate.id}]",
        )
        model.addGenConstrIndicator(
            used,
            True,
            event_time[candidate.alight_visit_index] + alight_offset
            <= movement_problem.passenger_service_end_tick,
            name=f"ride_horizon[{candidate.id}]",
        )
        ride_count_bits[candidate.id] = tuple(bits)
    if formulation is DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH:
        _add_time_expanded_passenger_capacity(
            model=model,
            passenger_build=passenger_build,
            cabin_id=start.cabin_id,
            cabin_capacity=artifact.config.cabin_capacity,
            passenger_flow_by_candidate_arc=passenger_flow_by_candidate_arc,
            route_time_membership=route_time_membership,
        )
    else:
        for visit_index in range(start.max_visit_count):
            onboard = tuple(
                unit
                for candidate in passenger_build.ride_candidates
                if candidate.cabin_id == start.cabin_id
                and candidate.id in ride_count_bits
                and candidate.board_visit_index
                <= visit_index
                < candidate.alight_visit_index
                for weight, bit in ride_count_bits[candidate.id]
                for unit in (weight * bit,)
            )
            if onboard:
                model.addConstr(
                    gp.quicksum(onboard) <= artifact.config.cabin_capacity,
                    name=f"capacity[{visit_index}]",
                )
    model.update()
    return _ExactPricingModel(
        model=model,
        start=start,
        states=states,
        event_time=event_time,
        active=active,
        route_selection=route_selection,
        ride_count_bits=ride_count_bits,
        ride_count_expressions=ride_count_expressions,
        resource_window_membership=resource_window_membership,
    )


def _event_time_bounds(
    *,
    movement_problem: DddMovementProblem,
    start: DddFixedStart,
    states: tuple[str, ...],
    formulation: DddTrajectoryPricingFormulation,
) -> tuple[tuple[int, int], ...]:
    maximum_duration = max(
        option.duration_tick for option in movement_problem.route_options
    )
    global_upper = movement_problem.operational_end_tick + maximum_duration
    if formulation is DddTrajectoryPricingFormulation.LEGACY_INDICATORS:
        return tuple((0, global_upper) for _ in states)

    lower_if_active = start.time_tick
    upper_if_active = start.time_tick
    bounds = [(start.time_tick, start.time_tick)]
    for state_id in states[:-1]:
        durations = tuple(
            option.duration_tick
            for option in movement_problem.route_options_by_state_id[state_id]
        )
        lower_if_active += min(durations)
        upper_if_active += max(durations)
        bounds.append(
            (
                min(lower_if_active, movement_problem.operational_end_tick + 1),
                min(upper_if_active, global_upper),
            )
        )
    return tuple(bounds)


def _active_event_time_bounds(
    *,
    movement_problem: DddMovementProblem,
    start: DddFixedStart,
    states: tuple[str, ...],
) -> tuple[tuple[int, int], ...]:
    earliest = start.time_tick
    latest = start.time_tick
    bounds = [(earliest, latest)]
    for state_id in states[:-1]:
        durations = tuple(
            option.duration_tick
            for option in movement_problem.route_options_by_state_id[state_id]
        )
        earliest += min(durations)
        latest += max(durations)
        bounds.append(
            (
                earliest,
                min(latest, movement_problem.operational_end_tick),
            )
        )
    return tuple(bounds)


def _add_compact_route_core(
    *,
    model: gp.Model,
    movement_problem: DddMovementProblem,
    start: DddFixedStart,
    states: tuple[str, ...],
    event_time_bounds: tuple[tuple[int, int], ...],
) -> tuple[
    tuple[gp.Var, ...],
    tuple[gp.Var, ...],
    dict[tuple[int, str], gp.Var],
]:
    event_time = tuple(
        model.addVar(
            lb=float(lower),
            ub=float(upper),
            vtype=GRB.INTEGER,
            name=f"time[{index}]",
        )
        for index, (lower, upper) in enumerate(event_time_bounds)
    )
    active = tuple(
        model.addVar(vtype=GRB.BINARY, name=f"active[{index}]")
        for index in range(start.max_visit_count)
    )
    route_selection = {
        (visit_index, option.id): model.addVar(
            vtype=GRB.BINARY,
            name=f"route[{visit_index},{option_index}]",
        )
        for visit_index, state_id in enumerate(states[:-1])
        for option_index, option in enumerate(
            movement_problem.route_options_by_state_id[state_id]
        )
    }
    model.addConstr(event_time[0] == start.time_tick, name="fixed_start_time")
    model.addConstr(active[0] == 1, name="fixed_start_active")
    for visit_index, state_id in enumerate(states[:-1]):
        options = movement_problem.route_options_by_state_id[state_id]
        model.addConstr(
            gp.quicksum(route_selection[visit_index, option.id] for option in options)
            == active[visit_index],
            name=f"choose_route[{visit_index}]",
        )
        model.addConstr(
            event_time[visit_index + 1]
            == event_time[visit_index]
            + gp.quicksum(
                option.duration_tick * route_selection[visit_index, option.id]
                for option in options
            ),
            name=f"propagate_time[{visit_index}]",
        )
        if visit_index + 1 < start.max_visit_count:
            model.addConstr(
                active[visit_index + 1] <= active[visit_index],
                name=f"active_prefix[{visit_index}]",
            )
            model.addGenConstrIndicator(
                active[visit_index + 1],
                True,
                event_time[visit_index + 1] <= movement_problem.operational_end_tick,
                name=f"active_before_horizon[{visit_index + 1}]",
            )
            model.addGenConstrIndicator(
                active[visit_index + 1],
                False,
                event_time[visit_index + 1]
                >= movement_problem.operational_end_tick + 1,
                name=f"inactive_after_horizon[{visit_index + 1}]",
            )
    model.addConstr(
        event_time[-1] >= movement_problem.operational_end_tick + 1,
        name="complete_horizon_coverage",
    )
    return event_time, active, route_selection


def _add_time_expanded_route_core(
    *,
    model: gp.Model,
    movement_problem: DddMovementProblem,
    start: DddFixedStart,
    states: tuple[str, ...],
    event_time_bounds: tuple[tuple[int, int], ...],
) -> tuple[
    tuple[gp.Var, ...],
    tuple[gp.Var, ...],
    dict[tuple[int, str], gp.Var],
    dict[tuple[int, int], gp.LinExpr],
    dict[tuple[int, str, int], gp.Var],
    tuple[tuple[int, int, bool, str | None, int, bool, gp.Var], ...],
]:
    event_time = tuple(
        model.addVar(
            lb=float(lower),
            ub=float(upper),
            vtype=GRB.INTEGER,
            name=f"time[{index}]",
        )
        for index, (lower, upper) in enumerate(event_time_bounds)
    )
    active = tuple(
        model.addVar(vtype=GRB.BINARY, name=f"active[{index}]")
        for index in range(start.max_visit_count)
    )
    route_selection = {
        (visit_index, option.id): model.addVar(
            vtype=GRB.BINARY,
            name=f"route[{visit_index},{option_index}]",
        )
        for visit_index, state_id in enumerate(states[:-1])
        for option_index, option in enumerate(
            movement_problem.route_options_by_state_id[state_id]
        )
    }

    nodes_by_layer: list[set[tuple[int, bool]]] = [{(start.time_tick, True)}]
    arcs_by_layer: list[
        tuple[tuple[int, bool, str | None, int, bool, gp.Var], ...]
    ] = []
    for visit_index, state_id in enumerate(states[:-1]):
        arcs = []
        next_nodes: set[tuple[int, bool]] = set()
        for source_index, (source_tick, source_active) in enumerate(
            sorted(nodes_by_layer[-1])
        ):
            if source_active:
                options: tuple[DddRouteOption | None, ...] = tuple(
                    movement_problem.route_options_by_state_id[state_id]
                )
            else:
                options = (None,)
            for option_index, option in enumerate(options):
                target_tick = (
                    source_tick
                    if option is None
                    else source_tick + option.duration_tick
                )
                target_active = (
                    option is not None
                    and target_tick <= movement_problem.operational_end_tick
                )
                target = (target_tick, target_active)
                next_nodes.add(target)
                variable = model.addVar(
                    vtype=GRB.BINARY,
                    name=(f"time_arc[{visit_index},{source_index},{option_index}]"),
                )
                arcs.append(
                    (
                        source_tick,
                        source_active,
                        option.id if option is not None else None,
                        target_tick,
                        target_active,
                        variable,
                    )
                )
        arcs_by_layer.append(tuple(arcs))
        nodes_by_layer.append(next_nodes)

    active_time_membership = {
        (visit_index, tick): gp.quicksum(
            variable
            for source_tick, source_active, _, _, _, variable in arcs
            if source_active and source_tick == tick
        )
        for visit_index, arcs in enumerate(arcs_by_layer)
        for tick, node_active in nodes_by_layer[visit_index]
        if node_active
    }
    route_time_membership = {
        (visit_index, option_id, source_tick): variable
        for visit_index, arcs in enumerate(arcs_by_layer)
        for source_tick, source_active, option_id, _, _, variable in arcs
        if source_active and option_id is not None
    }

    for visit_index, arcs in enumerate(arcs_by_layer):
        for node_index, (node_tick, node_active) in enumerate(
            sorted(nodes_by_layer[visit_index])
        ):
            outgoing = gp.quicksum(
                variable
                for (
                    source_tick,
                    source_active,
                    _,
                    _,
                    _,
                    variable,
                ) in arcs
                if (source_tick, source_active) == (node_tick, node_active)
            )
            incoming = (
                1.0
                if visit_index == 0
                else gp.quicksum(
                    variable
                    for (
                        _,
                        _,
                        _,
                        target_tick,
                        target_active,
                        variable,
                    ) in arcs_by_layer[visit_index - 1]
                    if (target_tick, target_active) == (node_tick, node_active)
                )
            )
            model.addConstr(
                outgoing == incoming,
                name=f"time_flow[{visit_index},{node_index}]",
            )
        model.addConstr(
            event_time[visit_index]
            == gp.quicksum(
                source_tick * variable for source_tick, _, _, _, _, variable in arcs
            ),
            name=f"time_from_flow[{visit_index}]",
        )
        model.addConstr(
            active[visit_index]
            == gp.quicksum(
                variable
                for _, source_active, _, _, _, variable in arcs
                if source_active
            ),
            name=f"active_from_flow[{visit_index}]",
        )
        for option in movement_problem.route_options_by_state_id[states[visit_index]]:
            model.addConstr(
                route_selection[visit_index, option.id]
                == gp.quicksum(
                    variable
                    for _, _, option_id, _, _, variable in arcs
                    if option_id == option.id
                ),
                name=f"route_from_flow[{visit_index},{option.id}]",
            )

    final_arcs = arcs_by_layer[-1]
    model.addConstr(
        event_time[-1]
        == gp.quicksum(
            target_tick * variable for _, _, _, target_tick, _, variable in final_arcs
        ),
        name="final_time_from_flow",
    )
    model.addConstr(
        gp.quicksum(
            variable
            for _, _, _, _, target_active, variable in final_arcs
            if not target_active
        )
        == 1.0,
        name="complete_horizon_coverage",
    )
    return (
        event_time,
        active,
        route_selection,
        active_time_membership,
        route_time_membership,
        tuple(
            (
                visit_index,
                source_tick,
                source_active,
                option_id,
                target_tick,
                target_active,
                variable,
            )
            for visit_index, arcs in enumerate(arcs_by_layer)
            for (
                source_tick,
                source_active,
                option_id,
                target_tick,
                target_active,
                variable,
            ) in arcs
        ),
    )


def _add_binary_event_product_convex_hull(
    *,
    model: gp.Model,
    product: gp.Var,
    binary: gp.Var,
    event_time: gp.Var,
    event_offset: int,
    global_event_lower: int,
    global_event_upper: int,
    active_event_lower: int,
    active_event_upper: int,
    name: str,
) -> None:
    global_lower = global_event_lower + event_offset
    global_upper = global_event_upper + event_offset
    active_lower = active_event_lower + event_offset
    active_upper = active_event_upper + event_offset
    event_expression = event_time + event_offset
    model.addConstr(product >= active_lower * binary, name=f"{name}_lower_on")
    model.addConstr(product <= active_upper * binary, name=f"{name}_upper_on")
    model.addConstr(
        product >= event_expression - global_upper * (1 - binary),
        name=f"{name}_lower_off",
    )
    model.addConstr(
        product <= event_expression - global_lower * (1 - binary),
        name=f"{name}_upper_off",
    )


def _add_time_expanded_ride_flow(
    *,
    model: gp.Model,
    candidate_id: str,
    board_visit_index: int,
    alight_visit_index: int,
    board_option_id: str,
    alight_option_id: str,
    board_offset: int,
    alight_offset: int,
    release_tick: int,
    service_end_tick: int,
    objective_event: EanPassengerObjectiveEvent,
    constant_unit_cost: float,
    upper: int,
    arcs: tuple[tuple[int, int, bool, str | None, int, bool, gp.Var], ...],
) -> dict[tuple[int, int, str], gp.Var]:
    flow_by_arc: dict[tuple[int, int, str], gp.Var] = {}
    arc_target_by_key: dict[tuple[int, int, str], int] = {}
    for arc_index, (
        visit_index,
        source_tick,
        source_active,
        option_id,
        target_tick,
        _,
        route_arc,
    ) in enumerate(arcs):
        if (
            not source_active
            or option_id is None
            or not board_visit_index <= visit_index <= alight_visit_index
        ):
            continue
        if visit_index == board_visit_index and (
            option_id != board_option_id or source_tick + board_offset < release_tick
        ):
            continue
        if visit_index == alight_visit_index and (
            option_id != alight_option_id
            or source_tick + alight_offset > service_end_tick
        ):
            continue
        objective_coefficient = 0.0
        if visit_index == board_visit_index:
            objective_coefficient += constant_unit_cost
            if objective_event is EanPassengerObjectiveEvent.BOARDING:
                objective_coefficient += ddd_tick_to_seconds(source_tick + board_offset)
        if (
            visit_index == alight_visit_index
            and objective_event is EanPassengerObjectiveEvent.ALIGHTING
        ):
            objective_coefficient += ddd_tick_to_seconds(source_tick + alight_offset)
        variable = model.addVar(
            lb=0.0,
            ub=float(upper),
            obj=objective_coefficient,
            name=f"ride_flow[{candidate_id},{arc_index}]",
        )
        model.addConstr(
            variable <= upper * route_arc,
            name=f"ride_flow_route[{candidate_id},{arc_index}]",
        )
        key = (visit_index, source_tick, option_id)
        flow_by_arc[key] = variable
        arc_target_by_key[key] = target_tick

    if not any(key[0] == board_visit_index for key in flow_by_arc) or not any(
        key[0] == alight_visit_index for key in flow_by_arc
    ):
        return {}
    for visit_index in range(board_visit_index + 1, alight_visit_index + 1):
        ticks = {
            target_tick
            for key, target_tick in arc_target_by_key.items()
            if key[0] == visit_index - 1
        } | {
            source_tick for layer, source_tick, _ in flow_by_arc if layer == visit_index
        }
        for tick in sorted(ticks):
            incoming = gp.quicksum(
                variable
                for key, variable in flow_by_arc.items()
                if key[0] == visit_index - 1 and arc_target_by_key[key] == tick
            )
            outgoing = gp.quicksum(
                variable
                for (layer, source_tick, _), variable in flow_by_arc.items()
                if layer == visit_index and source_tick == tick
            )
            model.addConstr(
                incoming == outgoing,
                name=f"ride_flow_balance[{candidate_id},{visit_index},{tick}]",
            )
    return flow_by_arc


def _add_time_expanded_passenger_capacity(
    *,
    model: gp.Model,
    passenger_build: EanPassengerCandidateBuildResult,
    cabin_id: int,
    cabin_capacity: float,
    passenger_flow_by_candidate_arc: dict[tuple[str, int, int, str], gp.Var],
    route_time_membership: dict[tuple[int, str, int], gp.Var],
) -> None:
    candidate_by_id = {
        candidate.id: candidate
        for candidate in passenger_build.ride_candidates
        if candidate.cabin_id == cabin_id
    }
    for (visit_index, option_id, source_tick), route_arc in sorted(
        route_time_membership.items()
    ):
        onboard = tuple(
            variable
            for (
                candidate_id,
                layer,
                tick,
                flow_option_id,
            ), variable in passenger_flow_by_candidate_arc.items()
            if layer == visit_index
            and tick == source_tick
            and flow_option_id == option_id
            and candidate_by_id[candidate_id].board_visit_index
            <= visit_index
            < candidate_by_id[candidate_id].alight_visit_index
        )
        if onboard:
            model.addConstr(
                gp.quicksum(onboard) <= cabin_capacity * route_arc,
                name=f"time_capacity[{visit_index},{option_id},{source_tick}]",
            )


def _add_resource_window_pricing_terms(
    *,
    model: gp.Model,
    movement_problem: DddMovementProblem,
    states: tuple[str, ...],
    event_time: tuple[gp.Var, ...],
    route_selection: dict[tuple[int, str], gp.Var],
    rows: tuple[DddTrajectoryResourceWindowRow, ...],
    duals: DddTrajectoryPassengerDuals,
) -> dict[tuple[str, int, str, int], gp.Var]:
    membership: dict[tuple[str, int, str, int], gp.Var] = {}
    for row_index, row in enumerate(rows):
        term = DddTrajectoryResourceWindowPricingTerm(
            window=row.window,
            raw_dual=duals.resource_window_raw_by_row_id[row.id],
        )
        resource = movement_problem.resources_by_id[row.window.resource_id]
        for visit_index, state_id in enumerate(states[:-1]):
            for option in movement_problem.route_options_by_state_id[state_id]:
                for usage_index, usage in enumerate(option.resource_usages):
                    if usage.resource_id != row.window.resource_id:
                        continue
                    key = (row.id, visit_index, option.id, usage_index)
                    entered = model.addVar(
                        vtype=GRB.BINARY,
                        name=(
                            f"window_entered[{row_index},{visit_index},{usage_index}]"
                        ),
                    )
                    uncleared = model.addVar(
                        vtype=GRB.BINARY,
                        name=(
                            f"window_uncleared[{row_index},{visit_index},{usage_index}]"
                        ),
                    )
                    contains = model.addVar(
                        vtype=GRB.BINARY,
                        obj=term.congestion_penalty,
                        name=(
                            f"window_contains[{row_index},{visit_index},{usage_index}]"
                        ),
                    )
                    enter_limit = (
                        row.window.anchor_tick - usage.follower_enter_offset_tick
                    )
                    clear_limit = (
                        row.window.anchor_tick
                        - usage.leader_clear_offset_tick
                        - usage.separation_after_tick(resource.minimum_headway_tick)
                    )
                    model.addGenConstrIndicator(
                        entered,
                        True,
                        event_time[visit_index] <= enter_limit,
                        name=(
                            f"window_entered_on[{row_index},{visit_index},"
                            f"{usage_index}]"
                        ),
                    )
                    model.addGenConstrIndicator(
                        entered,
                        False,
                        event_time[visit_index] >= enter_limit + 1,
                        name=(
                            f"window_entered_off[{row_index},{visit_index},"
                            f"{usage_index}]"
                        ),
                    )
                    model.addGenConstrIndicator(
                        uncleared,
                        True,
                        event_time[visit_index] >= clear_limit + 1,
                        name=(
                            f"window_uncleared_on[{row_index},{visit_index},"
                            f"{usage_index}]"
                        ),
                    )
                    model.addGenConstrIndicator(
                        uncleared,
                        False,
                        event_time[visit_index] <= clear_limit,
                        name=(
                            f"window_uncleared_off[{row_index},{visit_index},"
                            f"{usage_index}]"
                        ),
                    )
                    selected = route_selection[visit_index, option.id]
                    model.addConstr(contains <= selected)
                    model.addConstr(contains <= entered)
                    model.addConstr(contains <= uncleared)
                    model.addConstr(contains >= selected + entered + uncleared - 2)
                    membership[key] = contains
    return membership


def _extract_reference_trajectory(
    movement_problem: DddMovementProblem,
    start: DddFixedStart,
    model_data: _ExactPricingModel,
    *,
    tolerance_seconds: float,
) -> DddReferenceTrajectory:
    visits = []
    for visit_index, state_id in enumerate(model_data.states[:-1]):
        if model_data.active[visit_index].X < 0.5:
            break
        options = movement_problem.route_options_by_state_id[state_id]
        selected = tuple(
            option
            for option in options
            if model_data.route_selection[visit_index, option.id].X >= 0.5
        )
        if len(selected) != 1:
            raise RuntimeError("exact trajectory pricing route is not unique")
        visits.append(
            build_ddd_reference_visit(
                start=start,
                visit_index=visit_index,
                switch_time_seconds=ddd_tick_to_seconds(
                    int(round(model_data.event_time[visit_index].X))
                ),
                option=selected[0],
                operational_end_seconds=movement_problem.operational_end_seconds,
                tolerance_seconds=tolerance_seconds,
            )
        )
    return DddReferenceTrajectory(cabin_id=start.cabin_id, visits=tuple(visits))


def _exclude_route_sequence(
    model: gp.Model,
    route_selection: dict[tuple[int, str], gp.Var],
    sequence: tuple[str, ...],
    *,
    name: str,
) -> None:
    matching = []
    for visit_index, option_id in enumerate(sequence):
        variable = route_selection.get((visit_index, option_id))
        if variable is None:
            raise ValueError("excluded trajectory sequence is incompatible")
        matching.append(variable)
    if not matching:
        raise ValueError("excluded trajectory sequence must not be empty")
    model.addConstr(gp.quicksum(matching) <= len(matching) - 1, name=name)


def _unknown_result(
    cabin_id: int,
    started: float,
    self_conflict_round_count: int,
    detail: str,
    *,
    certified_lower_bound: float | None = None,
    model_data: _ExactPricingModel | None = None,
) -> DddTrajectoryExactPricingResult:
    return DddTrajectoryExactPricingResult(
        cabin_id=cabin_id,
        status=DddTrajectoryExactPricingStatus.UNKNOWN,
        minimum_reduced_cost=0.0,
        exact=False,
        option_id=None,
        reference_trajectory=None,
        ride_counts_by_candidate_id={},
        solve_seconds=perf_counter() - started,
        certified_reduced_cost_lower_bound=certified_lower_bound,
        self_conflict_round_count=self_conflict_round_count,
        detail=detail,
        **(_pricing_model_metrics(model_data) if model_data is not None else {}),
    )


def _extract_valid_incumbent_result(
    *,
    movement_problem: DddMovementProblem,
    artifact: EanBuildArtifact,
    cabin_id: int,
    start: DddFixedStart,
    model_data: _ExactPricingModel,
    started: float,
    self_conflict_round_count: int,
    certified_lower_bound: float | None,
    tolerance_seconds: float,
    detail: str,
) -> DddTrajectoryExactPricingResult | None:
    if model_data.model.SolCount <= 0:
        return None
    trajectory = _extract_reference_trajectory(
        movement_problem,
        start,
        model_data,
        tolerance_seconds=tolerance_seconds,
    )
    try:
        validate_ddd_reference_trajectory(
            movement_problem,
            trajectory,
            tolerance_seconds=tolerance_seconds,
        )
    except DddReferenceResourceConflictError:
        return None
    column = ddd_trajectory_column(
        trajectory,
        instance_fingerprint=ddd_trajectory_instance_fingerprint(artifact),
    )
    return DddTrajectoryExactPricingResult(
        cabin_id=cabin_id,
        status=DddTrajectoryExactPricingStatus.UNKNOWN,
        minimum_reduced_cost=float(model_data.model.ObjVal),
        exact=False,
        option_id=column.id,
        reference_trajectory=trajectory,
        ride_counts_by_candidate_id=_extract_ride_counts(model_data),
        solve_seconds=perf_counter() - started,
        certified_reduced_cost_lower_bound=certified_lower_bound,
        self_conflict_round_count=self_conflict_round_count,
        detail=detail,
        **_pricing_model_metrics(model_data),
    )


def _pricing_model_metrics(model_data: _ExactPricingModel) -> dict[str, int | float]:
    model = model_data.model
    try:
        node_count = float(model.NodeCount)
    except (AttributeError, gp.GurobiError):
        node_count = 0.0
    return {
        "model_variable_count": int(model.NumVars),
        "model_linear_constraint_count": int(model.NumConstrs),
        "model_general_constraint_count": int(model.NumGenConstrs),
        "solver_node_count": node_count,
    }


def _extract_ride_counts(model_data: _ExactPricingModel) -> dict[str, int]:
    bit_counts = {
        candidate_id: count
        for candidate_id, bits in model_data.ride_count_bits.items()
        if (count := sum(weight * int(round(variable.X)) for weight, variable in bits))
        > 0
    }
    flow_counts = {
        candidate_id: count
        for candidate_id, expression in model_data.ride_count_expressions.items()
        if (count := int(round(expression.getValue()))) > 0
    }
    if set(bit_counts) & set(flow_counts):
        raise RuntimeError("exact pricing ride count representations overlap")
    return {**bit_counts, **flow_counts}


def _finite_model_objective_bound(model: gp.Model) -> float | None:
    try:
        value = float(model.ObjBound)
    except (AttributeError, gp.GurobiError):
        return None
    return value if math.isfinite(value) else None
