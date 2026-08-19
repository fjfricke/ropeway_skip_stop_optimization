from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
from time import perf_counter

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddFixedStart,
    DddMovementProblem,
    DddResourceUsage,
    DddRouteDecision,
    DddRouteOption,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceConflictError,
    DddReferenceTrajectory,
    build_ddd_reference_visit,
    find_ddd_reference_conflicts,
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
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddOptimizedInitialPlacementDomain,
    DddReservoirDispatchCardinalityMode,
    DddReservoirTrajectoryStartDomain,
    DddTrajectoryProblem,
    DddTrajectoryWaitingPolicy,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_oip import (
    DDD_OIP_HORIZON_TAIL_EPSILON_SECONDS,
    DddOipTrajectoryStart,
    build_ddd_oip_reference_trajectory,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_reservoir import (
    DDD_RESERVOIR_TIME_TOLERANCE_SECONDS,
    build_ddd_reservoir_reference_trajectory,
    build_ddd_stored_reservoir_trajectory,
    validate_ddd_reservoir_reference_trajectory,
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
    RELATIVE_TIME_EXPANDED_OIP = "relative_time_expanded_oip"
    RELATIVE_TIME_EXPANDED_OIP_FLOW = "relative_time_expanded_oip_flow"


def _waiting_policy_for_artifact(
    artifact: EanBuildArtifact,
) -> DddTrajectoryWaitingPolicy:
    waiting_limits = tuple(
        sorted(
            (
                station.station_id,
                station.max_wait_seconds,
            )
            for station in artifact.config.station_configs
            if station.waiting_mode is StationWaitingMode.END_OF_PLATFORM_WAIT
        )
    )
    unsupported = tuple(
        station.station_id
        for station in artifact.config.station_configs
        if station.waiting_mode is StationWaitingMode.STATION_FIFO_BUFFER
    )
    if unsupported:
        raise ValueError(f"DDD pricing does not support station FIFO waiting: {unsupported}")
    if not waiting_limits:
        return DddTrajectoryWaitingPolicy()
    missing = tuple(
        station_id for station_id, maximum in waiting_limits if maximum is None
    )
    if missing:
        raise ValueError(
            "DDD pricing requires explicit max_wait_seconds for waiting stations: "
            f"{missing}"
        )
    policy = DddTrajectoryWaitingPolicy(
        domain=DddTrajectoryWaitingDomain.BOUNDED_WAIT,
        step_seconds=1.0,
        maximum_wait_seconds_by_station_id=tuple(
            (station_id, float(maximum))
            for station_id, maximum in waiting_limits
            if maximum is not None
        ),
        earliest_wait_time_seconds=0.0,
    )
    return policy


def _is_relative_oip_formulation(
    formulation: DddTrajectoryPricingFormulation,
) -> bool:
    return formulation in {
        DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP,
        DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP_FLOW,
    }


@dataclass(frozen=True)
class DddTrajectoryExactPricingCandidate:
    start_class_index: int
    reduced_cost: float
    option_id: str
    reference_trajectory: DddReferenceTrajectory
    ride_counts_by_candidate_id: dict[str, int]

    def __post_init__(self) -> None:
        if self.start_class_index < 0:
            raise ValueError("pricing candidate start-class index is invalid")
        if not math.isfinite(self.reduced_cost):
            raise ValueError("pricing candidate reduced cost must be finite")
        if not self.option_id:
            raise ValueError("pricing candidate option ID is empty")
        if any(value <= 0 for value in self.ride_counts_by_candidate_id.values()):
            raise ValueError("pricing candidate ride counts must be positive")


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
    priced_start_class_count: int = 0
    required_start_class_count: int = 0
    bounded_start_class_count: int = 0
    start_class_candidates: tuple[DddTrajectoryExactPricingCandidate, ...] = ()
    relative_node_count: int = 0
    relative_arc_count: int = 0
    origin_product_count: int = 0
    model_build_seconds: float = 0.0

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
        if (
            min(
                self.relative_node_count,
                self.relative_arc_count,
                self.origin_product_count,
            )
            < 0
        ):
            raise ValueError("relative pricing model size is invalid")
        if self.model_build_seconds < 0 or not math.isfinite(self.model_build_seconds):
            raise ValueError("pricing model build time is invalid")
        if self.solver_node_count < 0 or not math.isfinite(self.solver_node_count):
            raise ValueError("exact trajectory pricing node count is invalid")
        if not (
            0
            <= self.bounded_start_class_count
            <= self.priced_start_class_count
            <= self.required_start_class_count
        ):
            raise ValueError("exact trajectory pricing start-class coverage is invalid")
        if any(value <= 0 for value in self.ride_counts_by_candidate_id.values()):
            raise ValueError("exact trajectory pricing ride counts must be positive")
        candidate_indices = tuple(
            candidate.start_class_index for candidate in self.start_class_candidates
        )
        if tuple(sorted(set(candidate_indices))) != candidate_indices:
            raise ValueError(
                "exact trajectory pricing class candidates are not normalized"
            )
        if any(
            candidate.start_class_index >= self.required_start_class_count
            or candidate.reference_trajectory.cabin_id != self.cabin_id
            for candidate in self.start_class_candidates
        ):
            raise ValueError("exact trajectory pricing class candidate is inconsistent")
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
    """Exact fixed-start route/load pricing for No-Wait or bounded Waiting."""

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
        excluded_timed_support_signatures: frozenset[
            tuple[tuple[str, float], ...]
        ] = frozenset(),
        resource_window_rows: tuple[DddTrajectoryResourceWindowRow, ...] = (),
        waiting_policy: DddTrajectoryWaitingPolicy | None = None,
        instance_fingerprint: str | None = None,
    ) -> DddTrajectoryExactPricingResult:
        started = perf_counter()
        waiting_policy = waiting_policy or _waiting_policy_for_artifact(artifact)
        self._validate(
            movement_problem,
            artifact,
            passenger_build,
            cabin_id,
            duals,
            resource_window_rows,
            waiting_policy,
        )
        start = next(
            item for item in movement_problem.starts if item.cabin_id == cabin_id
        )
        instance_fingerprint = (
            instance_fingerprint or ddd_trajectory_instance_fingerprint(artifact)
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
            excluded_timed_support_signatures=excluded_timed_support_signatures,
            resource_window_rows=resource_window_rows,
            waiting_policy=waiting_policy,
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
                    waiting_policy=waiting_policy,
                    instance_fingerprint=instance_fingerprint,
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
                waiting_policy=waiting_policy,
            )
            try:
                validate_ddd_reference_trajectory(
                    movement_problem,
                    trajectory,
                    tolerance_seconds=self.tolerance_seconds,
                    waiting_policy=waiting_policy,
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
                _add_reference_self_conflict_disjunction(
                    model_data=model_data,
                    movement_problem=movement_problem,
                    trajectory=trajectory,
                    waiting_policy=waiting_policy,
                    name=f"self_conflict[{self_conflict_round_count}]",
                )
                self_conflict_round_count += 1
                model_data.model.update()
                continue
            column = ddd_trajectory_column(
                trajectory,
                instance_fingerprint=instance_fingerprint,
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
        waiting_policy: DddTrajectoryWaitingPolicy,
    ) -> None:
        movement_problem.validate()
        artifact.validate()
        passenger_build.validate()
        if movement_problem.scenario_id != artifact.scenario_id:
            raise ValueError("exact trajectory pricing instance differs")
        if artifact.fleet_mode is not EanFleetMode.FIXED_STARTS:
            raise ValueError("exact trajectory pricing supports fixed starts only")
        artifact_waiting_policy = _waiting_policy_for_artifact(artifact)
        if (
            waiting_policy.domain is not artifact_waiting_policy.domain
            or waiting_policy.maximum_wait_seconds_by_station_id
            != artifact_waiting_policy.maximum_wait_seconds_by_station_id
        ):
            raise ValueError("pricing waiting policy differs from the EAN artifact")
        waiting_policy.validate(movement_problem.core)
        if (
            waiting_policy.domain is DddTrajectoryWaitingDomain.BOUNDED_WAIT
            and resource_window_rows
        ):
            raise ValueError("bounded-wait pricing supports pair-only rows")
        if (
            waiting_policy.domain is DddTrajectoryWaitingDomain.BOUNDED_WAIT
            and self.formulation
            is not DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH
        ):
            raise ValueError(
                "fixed-start bounded waiting requires time_expanded_path pricing"
            )
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


@dataclass(frozen=True)
class _DddOipPricingStartClass:
    index: int
    phase_index: int
    state_id: str
    maximum_visits: int
    station_start: bool
    start_bounds: tuple[float, float]
    previous_service: bool | None


@dataclass(frozen=True, order=True)
class _DddRelativeTimeNode:
    visit_index: int
    state_id: str
    elapsed_tick: int


@dataclass(frozen=True, order=True)
class _DddRelativeTimeArc:
    index: int
    visit_index: int
    source_state_id: str
    source_elapsed_tick: int
    option_id: str
    target_state_id: str
    target_elapsed_tick: int
    continues: bool


@dataclass(frozen=True)
class _DddRelativeTimeGraph:
    nodes: tuple[_DddRelativeTimeNode, ...]
    arcs: tuple[_DddRelativeTimeArc, ...]


@dataclass(frozen=True)
class _DddRelativeArcVariable:
    arc: _DddRelativeTimeArc
    variable: gp.Var


def _build_relative_time_graph(
    *,
    movement_problem: DddMovementProblem,
    start_class: _DddOipPricingStartClass,
) -> _DddRelativeTimeGraph:
    """Build the exact reachable no-wait duration DAG for one OIP start class."""

    states = deterministic_route_state_ids(
        movement_problem,
        start_state_id=start_class.state_id,
        max_visit_count=start_class.maximum_visits,
        error_context="relative OIP pricing",
    )
    horizon = float(movement_problem.operational_end_tick)
    tail_epsilon = DDD_OIP_HORIZON_TAIL_EPSILON_SECONDS / DDD_TIME_TICK_SECONDS
    theta_lower, theta_upper = start_class.start_bounds
    nodes_by_layer: list[set[_DddRelativeTimeNode]] = [
        {_DddRelativeTimeNode(0, states[0], 0)}
    ]
    arcs: list[_DddRelativeTimeArc] = []
    for visit_index, state_id in enumerate(states[:-1]):
        current_nodes = nodes_by_layer[visit_index]
        next_nodes: set[_DddRelativeTimeNode] = set()
        for node in sorted(current_nodes):
            if theta_lower + node.elapsed_tick > horizon:
                continue
            for option in movement_problem.route_options_by_state_id[state_id]:
                target_elapsed = node.elapsed_tick + option.duration_tick
                can_continue = theta_lower + target_elapsed <= horizon
                can_terminate = theta_upper + target_elapsed >= horizon + tail_epsilon
                if can_continue:
                    target = _DddRelativeTimeNode(
                        visit_index + 1,
                        option.to_state_id,
                        target_elapsed,
                    )
                    next_nodes.add(target)
                    arcs.append(
                        _DddRelativeTimeArc(
                            index=len(arcs),
                            visit_index=visit_index,
                            source_state_id=node.state_id,
                            source_elapsed_tick=node.elapsed_tick,
                            option_id=option.id,
                            target_state_id=option.to_state_id,
                            target_elapsed_tick=target_elapsed,
                            continues=True,
                        )
                    )
                if can_terminate:
                    arcs.append(
                        _DddRelativeTimeArc(
                            index=len(arcs),
                            visit_index=visit_index,
                            source_state_id=node.state_id,
                            source_elapsed_tick=node.elapsed_tick,
                            option_id=option.id,
                            target_state_id=option.to_state_id,
                            target_elapsed_tick=target_elapsed,
                            continues=False,
                        )
                    )
        nodes_by_layer.append(next_nodes)
    return _DddRelativeTimeGraph(
        nodes=tuple(node for layer in nodes_by_layer for node in sorted(layer)),
        arcs=tuple(arcs),
    )


@dataclass(frozen=True)
class DddTrajectoryExactOipNoWaitPricingOracle:
    """Exact phase-decomposed pricing over the continuous no-wait OIP domain."""

    time_limit_seconds: float = 30.0
    threads: int = 1
    output_flag: bool = False
    mip_focus: int = 2
    formulation: DddTrajectoryPricingFormulation = (
        DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL
    )
    tolerance_seconds: float = 1e-9
    _relative_graph_cache: dict[
        tuple[str, int, bool, bool | None], _DddRelativeTimeGraph
    ] = field(default_factory=dict, compare=False, repr=False)

    def solve(
        self,
        *,
        trajectory_problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        cabin_id: int,
        duals: DddTrajectoryPassengerDuals,
        resource_window_rows: tuple[DddTrajectoryResourceWindowRow, ...] = (),
        start_class_indices: tuple[int, ...] | None = None,
        certify_complete_domain: bool = True,
    ) -> DddTrajectoryExactPricingResult:
        started = perf_counter()
        trajectory_problem.validate()
        artifact.validate()
        passenger_build.validate()
        if not isinstance(
            trajectory_problem.start_domain, DddOptimizedInitialPlacementDomain
        ):
            raise ValueError("OIP pricing requires an optimized-placement domain")
        if artifact.fleet_mode is not EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
            raise ValueError("OIP pricing requires an optimized-placement artifact")
        if any(
            item.waiting_mode is not StationWaitingMode.NO_WAITING
            for item in artifact.config.station_configs
        ):
            raise ValueError("OIP pricing supports no-wait only")
        if self.time_limit_seconds <= 0 or self.threads <= 0:
            raise ValueError("OIP pricing limits must be positive")
        if self.formulation not in {
            DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
            DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP,
            DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP_FLOW,
        }:
            raise ValueError(
                "OIP pricing supports tight_convex_hull or a relative-time-expanded "
                "OIP formulation"
            )
        if cabin_id not in trajectory_problem.cabin_ids:
            raise ValueError("OIP pricing cabin is unknown")
        if cabin_id not in duals.cabin_choice_raw_by_cabin_id:
            raise ValueError("OIP pricing cabin dual is missing")
        if resource_window_rows:
            if _is_relative_oip_formulation(self.formulation):
                raise ValueError(
                    "relative continuous OIP pricing currently requires pair_only"
                )
            # The compact continuous membership formulation is supported, but
            # retained boundary-only resources do not define anonymous windows.
            if any(
                row.window.resource_id
                not in trajectory_problem.movement_core.resources_by_id
                for row in resource_window_rows
            ):
                raise ValueError("OIP pricing window references an unknown resource")

        movement_problem = trajectory_problem.structural_movement_problem
        start_classes = _oip_pricing_start_classes(
            trajectory_problem=trajectory_problem,
            artifact=artifact,
        )
        required_start_class_count = len(start_classes)
        if start_class_indices is None:
            selected_start_classes = start_classes
        else:
            if tuple(sorted(set(start_class_indices))) != start_class_indices:
                raise ValueError("OIP pricing start-class selection is not normalized")
            by_index = {item.index: item for item in start_classes}
            if any(index not in by_index for index in start_class_indices):
                raise ValueError(
                    "OIP pricing start-class selection is outside the domain"
                )
            selected_start_classes = tuple(
                by_index[index] for index in start_class_indices
            )
        complete_selection = len(selected_start_classes) == required_start_class_count
        if certify_complete_domain and not complete_selection:
            raise ValueError("OIP proof pricing must cover every start class")
        all_exact = complete_selection
        every_bound_available = complete_selection
        bounds: list[float] = []
        best: tuple[float, DddReferenceTrajectory, dict[str, int], str] | None = None
        variable_count = linear_count = general_count = 0
        node_count = 0.0
        solved_subdomains = 0
        bounded_start_class_count = 0
        start_class_candidates: list[DddTrajectoryExactPricingCandidate] = []
        relative_node_count = relative_arc_count = origin_product_count = 0
        total_model_build_seconds = 0.0

        for position, start_class in enumerate(selected_start_classes):
            remaining = self.time_limit_seconds - (perf_counter() - started)
            if remaining <= 0:
                all_exact = False
                every_bound_available = False
                break
            remaining_class_count = len(selected_start_classes) - position
            class_budget = remaining / remaining_class_count
            synthetic_start = DddFixedStart(
                cabin_id=cabin_id,
                state_id=start_class.state_id,
                time_seconds=0.0,
                max_visit_count=start_class.maximum_visits,
            )
            model_build_started = perf_counter()
            relative_graph = None
            if _is_relative_oip_formulation(self.formulation):
                cache_key = (
                    movement_problem.scenario_id,
                    start_class.index,
                    start_class.station_start,
                    start_class.previous_service,
                )
                relative_graph = self._relative_graph_cache.get(cache_key)
                if relative_graph is None:
                    relative_graph = _build_relative_time_graph(
                        movement_problem=movement_problem,
                        start_class=start_class,
                    )
                    self._relative_graph_cache[cache_key] = relative_graph
            model_data = _build_exact_pricing_model(
                movement_problem=movement_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=objective,
                start=synthetic_start,
                duals=duals,
                output_flag=self.output_flag,
                threads=self.threads,
                mip_focus=self.mip_focus,
                formulation=self.formulation,
                excluded_route_option_sequences=frozenset(),
                resource_window_rows=resource_window_rows,
                continuous_start_bounds_ticks=start_class.start_bounds,
                visit_index_offset=start_class.phase_index,
                station_boundary=start_class.station_start,
                relative_graph=relative_graph,
            )
            build_seconds = perf_counter() - model_build_started
            total_model_build_seconds += build_seconds
            solver_budget = max(class_budget - build_seconds, 1e-3)
            model_data.model.Params.TimeLimit = solver_budget
            model_data.model.optimize()
            solved_subdomains += 1
            metrics = _pricing_model_metrics(model_data)
            variable_count += metrics["model_variable_count"]
            linear_count += metrics["model_linear_constraint_count"]
            general_count += metrics["model_general_constraint_count"]
            node_count += metrics["solver_node_count"]
            relative_node_count += model_data.relative_node_count
            relative_arc_count += model_data.relative_arc_count
            origin_product_count += model_data.origin_product_count
            if model_data.model.Status == GRB.INFEASIBLE:
                bounded_start_class_count += 1
                continue
            bound = _finite_model_objective_bound(model_data.model)
            if bound is None:
                every_bound_available = False
            else:
                bounds.append(bound)
                bounded_start_class_count += 1
            if model_data.model.Status != GRB.OPTIMAL:
                all_exact = False
            if model_data.model.SolCount <= 0:
                continue
            trajectory = _extract_oip_reference_trajectory(
                trajectory_problem=trajectory_problem,
                artifact=artifact,
                cabin_id=cabin_id,
                phase_index=start_class.phase_index,
                station_start=start_class.station_start,
                previous_service=start_class.previous_service,
                model_data=model_data,
            )
            value = float(model_data.model.ObjVal)
            column = ddd_trajectory_column(
                trajectory,
                instance_fingerprint=ddd_trajectory_instance_fingerprint(artifact),
            )
            candidate = (
                value,
                trajectory,
                _extract_ride_counts(model_data),
                column.id,
            )
            start_class_candidates.append(
                DddTrajectoryExactPricingCandidate(
                    start_class_index=start_class.index,
                    reduced_cost=value,
                    option_id=column.id,
                    reference_trajectory=trajectory,
                    ride_counts_by_candidate_id=candidate[2],
                )
            )
            if best is None or value < best[0] - self.tolerance_seconds:
                best = candidate

        complete_bound_available = (
            certify_complete_domain
            and complete_selection
            and every_bound_available
            and bounded_start_class_count == required_start_class_count
        )
        exact_complete_domain = (
            certify_complete_domain
            and complete_selection
            and all_exact
            and solved_subdomains == required_start_class_count
        )

        if best is None:
            return DddTrajectoryExactPricingResult(
                cabin_id=cabin_id,
                status=(
                    DddTrajectoryExactPricingStatus.EXHAUSTED
                    if exact_complete_domain
                    else DddTrajectoryExactPricingStatus.UNKNOWN
                ),
                minimum_reduced_cost=0.0,
                exact=exact_complete_domain,
                option_id=None,
                reference_trajectory=None,
                ride_counts_by_candidate_id={},
                solve_seconds=perf_counter() - started,
                certified_reduced_cost_lower_bound=(
                    0.0
                    if exact_complete_domain
                    else (min(bounds) if complete_bound_available and bounds else None)
                ),
                detail=(
                    None
                    if exact_complete_domain
                    else (
                        "OIP primal start-class pricing"
                        if not certify_complete_domain
                        else "OIP pricing domain was not exhausted"
                    )
                ),
                model_variable_count=variable_count,
                model_linear_constraint_count=linear_count,
                model_general_constraint_count=general_count,
                solver_node_count=node_count,
                priced_start_class_count=solved_subdomains,
                required_start_class_count=required_start_class_count,
                bounded_start_class_count=bounded_start_class_count,
                start_class_candidates=tuple(start_class_candidates),
                relative_node_count=relative_node_count,
                relative_arc_count=relative_arc_count,
                origin_product_count=origin_product_count,
                model_build_seconds=total_model_build_seconds,
            )
        certified_bound = min(bounds) if complete_bound_available and bounds else None
        return DddTrajectoryExactPricingResult(
            cabin_id=cabin_id,
            status=(
                DddTrajectoryExactPricingStatus.OPTIMAL
                if exact_complete_domain
                else DddTrajectoryExactPricingStatus.UNKNOWN
            ),
            minimum_reduced_cost=best[0],
            exact=exact_complete_domain,
            option_id=best[3],
            reference_trajectory=best[1],
            ride_counts_by_candidate_id=best[2],
            solve_seconds=perf_counter() - started,
            certified_reduced_cost_lower_bound=certified_bound,
            detail=(
                None
                if exact_complete_domain
                else (
                    f"OIP pricing covered {solved_subdomains}/"
                    f"{required_start_class_count} start classes"
                )
            ),
            model_variable_count=variable_count,
            model_linear_constraint_count=linear_count,
            model_general_constraint_count=general_count,
            solver_node_count=node_count,
            priced_start_class_count=solved_subdomains,
            required_start_class_count=required_start_class_count,
            bounded_start_class_count=bounded_start_class_count,
            start_class_candidates=tuple(start_class_candidates),
            relative_node_count=relative_node_count,
            relative_arc_count=relative_arc_count,
            origin_product_count=origin_product_count,
            model_build_seconds=total_model_build_seconds,
        )


@dataclass(frozen=True)
class DddTrajectoryExactReservoirNoWaitPricingOracle:
    """Complete continuous reservoir pricing for the declared finite wait policy."""

    time_limit_seconds: float = 30.0
    threads: int = 1
    output_flag: bool = False
    mip_focus: int = 2
    tolerance_seconds: float = DDD_RESERVOIR_TIME_TOLERANCE_SECONDS
    max_self_conflict_rounds: int = 1_000

    def solve(
        self,
        *,
        trajectory_problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        cabin_id: int,
        duals: DddTrajectoryPassengerDuals,
        resource_window_rows: tuple[DddTrajectoryResourceWindowRow, ...] = (),
        instance_fingerprint: str | None = None,
        dispatch_time_bounds_seconds: tuple[float, float] | None = None,
        certify_complete_domain: bool = True,
        dispatch_only: bool = False,
    ) -> DddTrajectoryExactPricingResult:
        started = perf_counter()
        trajectory_problem.validate()
        artifact.validate()
        passenger_build.validate()
        domain = trajectory_problem.start_domain
        if not isinstance(domain, DddReservoirTrajectoryStartDomain):
            raise ValueError("reservoir pricing requires a reservoir start domain")
        if cabin_id not in domain.cabin_ids:
            raise ValueError("reservoir pricing cabin is unknown")
        if cabin_id not in duals.cabin_choice_raw_by_cabin_id:
            raise ValueError("reservoir pricing cabin dual is missing")
        if self.time_limit_seconds <= 0 or self.threads <= 0:
            raise ValueError("reservoir pricing limits must be positive")
        if self.mip_focus not in range(4):
            raise ValueError("reservoir pricing MIP focus is invalid")
        if dispatch_time_bounds_seconds is not None:
            if certify_complete_domain:
                raise ValueError(
                    "restricted reservoir dispatch-time pricing cannot certify the "
                    "complete continuous domain"
                )
            lower_seconds, upper_seconds = dispatch_time_bounds_seconds
            if (
                not math.isfinite(lower_seconds)
                or not math.isfinite(upper_seconds)
                or lower_seconds > upper_seconds
                or lower_seconds < -domain.warmup_seconds - self.tolerance_seconds
                or upper_seconds >= -self.tolerance_seconds
            ):
                raise ValueError("reservoir dispatch-time pricing bounds are invalid")
        else:
            lower_seconds = -domain.warmup_seconds
            upper_seconds = -max(self.tolerance_seconds, 1e-12)
        movement = trajectory_problem.structural_movement_problem
        start = DddFixedStart(
            cabin_id=cabin_id,
            state_id=domain.boundary.entry_state_id,
            time_seconds=0.0,
            max_visit_count=domain.maximum_visit_count,
        )
        epsilon_tick = max(
            self.tolerance_seconds / DDD_TIME_TICK_SECONDS,
            1e-6,
        )
        model_data = _build_exact_pricing_model(
            movement_problem=movement,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=objective,
            start=start,
            duals=duals,
            output_flag=self.output_flag,
            threads=self.threads,
            mip_focus=self.mip_focus,
            formulation=DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
            excluded_route_option_sequences=frozenset(),
            resource_window_rows=resource_window_rows,
            continuous_start_bounds_ticks=(
                lower_seconds / DDD_TIME_TICK_SECONDS,
                upper_seconds / DDD_TIME_TICK_SECONDS,
            ),
            waiting_policy=trajectory_problem.waiting_policy,
        )
        self._add_reservoir_domain_constraints(
            model_data=model_data,
            movement_problem=movement,
            domain=domain,
            epsilon_tick=epsilon_tick,
            waiting_policy=trajectory_problem.waiting_policy,
        )
        model_data.model.update()
        alpha = duals.cabin_choice_raw_by_cabin_id[cabin_id]
        stored_reduced_cost = (
            -alpha
            if not dispatch_only
            and domain.cardinality_mode
            is DddReservoirDispatchCardinalityMode.OPTIONAL
            else math.inf
        )
        stored_trajectory = (
            build_ddd_stored_reservoir_trajectory(cabin_id=cabin_id, domain=domain)
            if math.isfinite(stored_reduced_cost)
            else None
        )
        instance_fingerprint = (
            instance_fingerprint or ddd_trajectory_instance_fingerprint(artifact)
        )
        certified_dispatch_bound: float | None = None
        self_conflict_round_count = 0
        while True:
            remaining = self.time_limit_seconds - (perf_counter() - started)
            if remaining <= 0:
                return self._result(
                    cabin_id=cabin_id,
                    started=started,
                    model_data=model_data,
                    stored_reduced_cost=stored_reduced_cost,
                    stored_trajectory=stored_trajectory,
                    dispatch_candidate=None,
                    dispatch_counts={},
                    dispatch_value=None,
                    dispatch_bound=(
                        certified_dispatch_bound if certify_complete_domain else None
                    ),
                    exact_dispatch=False,
                    self_conflict_round_count=self_conflict_round_count,
                    detail="continuous reservoir pricing time budget exhausted",
                    instance_fingerprint=instance_fingerprint,
                )
            model_data.model.Params.TimeLimit = remaining
            model_data.model.optimize()
            bound = _finite_model_objective_bound(model_data.model)
            if bound is not None:
                certified_dispatch_bound = (
                    bound
                    if certified_dispatch_bound is None
                    else max(certified_dispatch_bound, bound)
                )
            if model_data.model.Status == GRB.INFEASIBLE:
                detail = (
                    None
                    if dispatch_time_bounds_seconds is None
                    else "restricted reservoir dispatch interval is infeasible: "
                    f"[{lower_seconds}, {upper_seconds}]"
                )
                return self._result(
                    cabin_id=cabin_id,
                    started=started,
                    model_data=model_data,
                    stored_reduced_cost=stored_reduced_cost,
                    stored_trajectory=stored_trajectory,
                    dispatch_candidate=None,
                    dispatch_counts={},
                    dispatch_value=None,
                    dispatch_bound=(math.inf if certify_complete_domain else None),
                    exact_dispatch=certify_complete_domain,
                    self_conflict_round_count=self_conflict_round_count,
                    detail=detail,
                    instance_fingerprint=instance_fingerprint,
                )
            dispatch_candidate = None
            dispatch_counts: dict[str, int] = {}
            dispatch_value = None
            if model_data.model.SolCount > 0:
                dispatch_candidate = self._extract_trajectory(
                    trajectory_problem=trajectory_problem,
                    cabin_id=cabin_id,
                    model_data=model_data,
                )
                try:
                    from ropeway_skip_stop_optimization.optimization.ddd.trajectory_reservoir import (
                        validate_ddd_reservoir_reference_trajectory,
                    )

                    validate_ddd_reservoir_reference_trajectory(
                        trajectory_problem,
                        dispatch_candidate,
                        tolerance_seconds=self.tolerance_seconds,
                    )
                except DddReferenceResourceConflictError:
                    if self_conflict_round_count >= self.max_self_conflict_rounds:
                        return self._result(
                            cabin_id=cabin_id,
                            started=started,
                            model_data=model_data,
                            stored_reduced_cost=stored_reduced_cost,
                            stored_trajectory=stored_trajectory,
                            dispatch_candidate=None,
                            dispatch_counts={},
                            dispatch_value=None,
                            dispatch_bound=(
                                certified_dispatch_bound
                                if certify_complete_domain
                                else None
                            ),
                            exact_dispatch=False,
                            self_conflict_round_count=self_conflict_round_count,
                            detail="reservoir pricing self-conflict budget exhausted",
                            instance_fingerprint=instance_fingerprint,
                        )
                    _add_reference_self_conflict_disjunction(
                        model_data=model_data,
                        movement_problem=movement,
                        trajectory=dispatch_candidate,
                        waiting_policy=trajectory_problem.waiting_policy,
                        name=f"reservoir_self_conflict[{self_conflict_round_count}]",
                    )
                    self_conflict_round_count += 1
                    model_data.model.update()
                    continue
                dispatch_counts = _extract_ride_counts(model_data)
                dispatch_value = float(model_data.model.ObjVal)
            return self._result(
                cabin_id=cabin_id,
                started=started,
                model_data=model_data,
                stored_reduced_cost=stored_reduced_cost,
                stored_trajectory=stored_trajectory,
                dispatch_candidate=dispatch_candidate,
                dispatch_counts=dispatch_counts,
                dispatch_value=dispatch_value,
                dispatch_bound=(
                    certified_dispatch_bound if certify_complete_domain else None
                ),
                exact_dispatch=(
                    certify_complete_domain and model_data.model.Status == GRB.OPTIMAL
                ),
                self_conflict_round_count=self_conflict_round_count,
                detail=(
                    None
                    if model_data.model.Status == GRB.OPTIMAL
                    else "continuous reservoir pricing terminated with a valid bound"
                ),
                instance_fingerprint=instance_fingerprint,
            )

    @staticmethod
    def _add_reservoir_domain_constraints(
        *,
        model_data: _ExactPricingModel,
        movement_problem: DddMovementProblem,
        domain: DddReservoirTrajectoryStartDomain,
        epsilon_tick: float,
        waiting_policy: DddTrajectoryWaitingPolicy | None = None,
    ) -> None:
        waiting_policy = waiting_policy or DddTrajectoryWaitingPolicy()
        first_options = movement_problem.route_options_by_state_id[
            domain.boundary.entry_state_id
        ]
        if domain.boundary.allowed_first_route_option_ids:
            model_data.model.addConstr(
                gp.quicksum(
                    model_data.route_selection[0, option.id]
                    for option in first_options
                    if option.id in domain.boundary.allowed_first_route_option_ids
                )
                == model_data.active[0],
                name="reservoir_first_route",
            )
        global_lower = -domain.warmup_seconds / DDD_TIME_TICK_SECONDS
        big_m = max(1.0, -global_lower)
        for visit_index, state_id in enumerate(model_data.states[:-1]):
            pre_service = model_data.model.addVar(
                vtype=GRB.BINARY,
                name=f"reservoir_pre_service[{visit_index}]",
            )
            model_data.model.addConstr(
                pre_service <= model_data.active[visit_index],
                name=f"reservoir_pre_active[{visit_index}]",
            )
            model_data.model.addGenConstrIndicator(
                pre_service,
                True,
                model_data.event_time[visit_index] <= -epsilon_tick,
                name=f"reservoir_pre_time[{visit_index}]",
            )
            model_data.model.addConstr(
                model_data.event_time[visit_index]
                >= -big_m
                * (pre_service + 1 - model_data.active[visit_index]),
                name=f"reservoir_service_time[{visit_index}]",
            )
            for option in movement_problem.route_options_by_state_id[state_id]:
                if option.decision is DddRouteDecision.SKIP:
                    model_data.model.addConstr(
                        model_data.route_selection[visit_index, option.id]
                        <= 1 - pre_service,
                        name=f"reservoir_warmup_stop[{visit_index},{option.id}]",
                    )
            wait_steps = model_data.wait_steps[visit_index]
            if wait_steps.UB > 0:
                wait_positive = model_data.model.addVar(
                    vtype=GRB.BINARY,
                    name=f"reservoir_wait_positive[{visit_index}]",
                )
                model_data.model.addConstr(
                    wait_steps <= wait_steps.UB * wait_positive,
                    name=f"reservoir_wait_positive_ub[{visit_index}]",
                )
                model_data.model.addConstr(
                    wait_steps >= wait_positive,
                    name=f"reservoir_wait_positive_lb[{visit_index}]",
                )
                stop_options = tuple(
                    option
                    for option in movement_problem.route_options_by_state_id[state_id]
                    if option.decision is DddRouteDecision.STOP
                )
                minimum_exit = model_data.event_time[visit_index] + gp.quicksum(
                    ddd_seconds_to_tick(option.platform_exit_offset_seconds)
                    * model_data.route_selection[visit_index, option.id]
                    for option in stop_options
                    if option.platform_exit_offset_seconds is not None
                )
                model_data.model.addGenConstrIndicator(
                    wait_positive,
                    True,
                    minimum_exit
                    >= ddd_seconds_to_tick(
                        waiting_policy.earliest_wait_time_seconds
                    ),
                    name=f"reservoir_wait_after_boundary[{visit_index}]",
                )

    @staticmethod
    def _extract_trajectory(
        *,
        trajectory_problem: DddTrajectoryProblem,
        cabin_id: int,
        model_data: _ExactPricingModel,
    ) -> DddReferenceTrajectory:
        movement = trajectory_problem.structural_movement_problem
        route_ids = []
        for visit_index, state_id in enumerate(model_data.states[:-1]):
            if model_data.active[visit_index].X < 0.5:
                break
            selected = tuple(
                option.id
                for option in movement.route_options_by_state_id[state_id]
                if model_data.route_selection[visit_index, option.id].X >= 0.5
            )
            if len(selected) != 1:
                raise RuntimeError("reservoir pricing route is not unique")
            route_ids.append(selected[0])
        return build_ddd_reservoir_reference_trajectory(
            problem=trajectory_problem,
            cabin_id=cabin_id,
            dispatch_time_seconds=(
                float(model_data.event_time[0].X) * DDD_TIME_TICK_SECONDS
            ),
            route_option_ids=tuple(route_ids),
            wait_seconds_by_visit=tuple(
                float(model_data.wait_steps[index].X)
                * float(trajectory_problem.waiting_policy.step_seconds or 0.0)
                for index in range(len(route_ids))
            ),
        )

    def _result(
        self,
        *,
        cabin_id: int,
        started: float,
        model_data: _ExactPricingModel,
        stored_reduced_cost: float,
        stored_trajectory: DddReferenceTrajectory | None,
        dispatch_candidate: DddReferenceTrajectory | None,
        dispatch_counts: dict[str, int],
        dispatch_value: float | None,
        dispatch_bound: float | None,
        exact_dispatch: bool,
        self_conflict_round_count: int,
        detail: str | None,
        instance_fingerprint: str,
    ) -> DddTrajectoryExactPricingResult:
        candidates: list[tuple[float, DddReferenceTrajectory, dict[str, int]]] = []
        if stored_trajectory is not None:
            candidates.append((stored_reduced_cost, stored_trajectory, {}))
        if dispatch_candidate is not None and dispatch_value is not None:
            candidates.append((dispatch_value, dispatch_candidate, dispatch_counts))
        best = min(candidates, key=lambda item: item[0]) if candidates else None
        complete_bound = None
        if dispatch_bound is not None:
            complete_bound = min(stored_reduced_cost, dispatch_bound)
            if not math.isfinite(complete_bound):
                complete_bound = 0.0 if exact_dispatch else None
        exact = exact_dispatch
        if best is None:
            return DddTrajectoryExactPricingResult(
                cabin_id=cabin_id,
                status=(
                    DddTrajectoryExactPricingStatus.EXHAUSTED
                    if exact
                    else DddTrajectoryExactPricingStatus.UNKNOWN
                ),
                minimum_reduced_cost=0.0,
                exact=exact,
                option_id=None,
                reference_trajectory=None,
                ride_counts_by_candidate_id={},
                solve_seconds=perf_counter() - started,
                certified_reduced_cost_lower_bound=complete_bound,
                self_conflict_round_count=self_conflict_round_count,
                detail=detail,
                **_pricing_model_metrics(model_data),
            )
        column = ddd_trajectory_column(
            best[1],
            instance_fingerprint=instance_fingerprint,
        )
        return DddTrajectoryExactPricingResult(
            cabin_id=cabin_id,
            status=(
                DddTrajectoryExactPricingStatus.OPTIMAL
                if exact
                else DddTrajectoryExactPricingStatus.UNKNOWN
            ),
            minimum_reduced_cost=best[0],
            exact=exact,
            option_id=column.id,
            reference_trajectory=best[1],
            ride_counts_by_candidate_id=best[2],
            solve_seconds=perf_counter() - started,
            certified_reduced_cost_lower_bound=complete_bound,
            self_conflict_round_count=self_conflict_round_count,
            detail=detail,
            priced_start_class_count=1,
            required_start_class_count=1,
            bounded_start_class_count=int(complete_bound is not None),
            **_pricing_model_metrics(model_data),
        )


@dataclass(frozen=True)
class DddTrajectoryReservoirAnchorPricingOracle:
    """Fast primal pricing on one fixed reservoir dispatch anchor.

    Its solver bound applies only to the selected finite anchor. It is never
    exposed as a lower bound for the continuous reservoir domain.
    """

    time_limit_seconds: float = 5.0
    threads: int = 1
    output_flag: bool = False
    mip_focus: int = 1
    tolerance_seconds: float = DDD_RESERVOIR_TIME_TOLERANCE_SECONDS
    max_self_conflict_rounds: int = 100
    maximum_time_expanded_arc_count: int = 25_000
    maximum_passenger_arc_product: int = 250_000

    def solve(
        self,
        *,
        trajectory_problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        cabin_id: int,
        dispatch_time_seconds: float,
        duals: DddTrajectoryPassengerDuals,
        instance_fingerprint: str | None = None,
    ) -> DddTrajectoryExactPricingResult:
        started = perf_counter()
        trajectory_problem.validate()
        artifact.validate()
        passenger_build.validate()
        domain = trajectory_problem.start_domain
        if not isinstance(domain, DddReservoirTrajectoryStartDomain):
            raise ValueError("reservoir anchor pricing requires a reservoir domain")
        if cabin_id not in domain.cabin_ids:
            raise ValueError("reservoir anchor pricing cabin is unknown")
        if not (
            -domain.warmup_seconds - self.tolerance_seconds
            <= dispatch_time_seconds
            < -self.tolerance_seconds
        ):
            raise ValueError("reservoir dispatch anchor lies outside [-W, 0)")
        if self.time_limit_seconds <= 0 or self.threads <= 0:
            raise ValueError("reservoir anchor pricing limits must be positive")
        if self.maximum_time_expanded_arc_count <= 0:
            raise ValueError("reservoir anchor pricing arc cap must be positive")
        if self.maximum_passenger_arc_product <= 0:
            raise ValueError("reservoir anchor passenger-product cap must be positive")

        movement = trajectory_problem.structural_movement_problem
        start = DddFixedStart(
            cabin_id=cabin_id,
            state_id=domain.boundary.entry_state_id,
            time_seconds=dispatch_time_seconds,
            max_visit_count=domain.maximum_visit_count,
        )
        estimated_arc_count = _reservoir_anchor_time_expanded_arc_count(
            movement_problem=movement,
            start=start,
            cutoff=self.maximum_time_expanded_arc_count,
        )
        cabin_candidate_count = sum(
            candidate.cabin_id == cabin_id
            for candidate in passenger_build.ride_candidates
        )
        passenger_arc_product = estimated_arc_count * max(1, cabin_candidate_count)
        if (
            estimated_arc_count > self.maximum_time_expanded_arc_count
            or passenger_arc_product > self.maximum_passenger_arc_product
        ):
            return DddTrajectoryExactPricingResult(
                cabin_id=cabin_id,
                status=DddTrajectoryExactPricingStatus.UNKNOWN,
                minimum_reduced_cost=0.0,
                exact=False,
                option_id=None,
                reference_trajectory=None,
                ride_counts_by_candidate_id={},
                solve_seconds=perf_counter() - started,
                certified_reduced_cost_lower_bound=None,
                detail=(
                    "finite dispatch anchor skipped before model build: "
                    f"{estimated_arc_count} arcs, {cabin_candidate_count} rides, "
                    f"product {passenger_arc_product}"
                ),
                relative_arc_count=estimated_arc_count,
            )
        model_data = _build_exact_pricing_model(
            movement_problem=movement,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=objective,
            start=start,
            duals=duals,
            output_flag=self.output_flag,
            threads=self.threads,
            mip_focus=self.mip_focus,
            formulation=DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH,
            excluded_route_option_sequences=frozenset(),
            resource_window_rows=(),
            waiting_policy=trajectory_problem.waiting_policy,
        )
        DddTrajectoryExactReservoirNoWaitPricingOracle._add_reservoir_domain_constraints(
            model_data=model_data,
            movement_problem=movement,
            domain=domain,
            epsilon_tick=max(
                self.tolerance_seconds / DDD_TIME_TICK_SECONDS,
                1e-6,
            ),
            waiting_policy=trajectory_problem.waiting_policy,
        )
        model_data.model.update()
        conflict_round = 0
        while True:
            remaining = self.time_limit_seconds - (perf_counter() - started)
            if remaining <= 0:
                return _unknown_result(
                    cabin_id,
                    started,
                    conflict_round,
                    "reservoir anchor pricing time budget exhausted",
                    certified_lower_bound=None,
                    model_data=model_data,
                )
            model_data.model.Params.TimeLimit = remaining
            model_data.model.optimize()
            if model_data.model.SolCount <= 0:
                return _unknown_result(
                    cabin_id,
                    started,
                    conflict_round,
                    "reservoir anchor pricing produced no incumbent",
                    certified_lower_bound=None,
                    model_data=model_data,
                )
            route_ids = []
            for visit_index, state_id in enumerate(model_data.states[:-1]):
                if model_data.active[visit_index].X < 0.5:
                    break
                selected = tuple(
                    option.id
                    for option in movement.route_options_by_state_id[state_id]
                    if model_data.route_selection[visit_index, option.id].X >= 0.5
                )
                if len(selected) != 1:
                    raise RuntimeError("reservoir anchor route is not unique")
                route_ids.append(selected[0])
            trajectory = build_ddd_reservoir_reference_trajectory(
                problem=trajectory_problem,
                cabin_id=cabin_id,
                dispatch_time_seconds=dispatch_time_seconds,
                route_option_ids=tuple(route_ids),
            )
            try:
                validate_ddd_reservoir_reference_trajectory(
                    trajectory_problem,
                    trajectory,
                    tolerance_seconds=self.tolerance_seconds,
                )
            except DddReferenceResourceConflictError:
                if conflict_round >= self.max_self_conflict_rounds:
                    return _unknown_result(
                        cabin_id,
                        started,
                        conflict_round,
                        "reservoir anchor self-conflict budget exhausted",
                        certified_lower_bound=None,
                        model_data=model_data,
                    )
                _add_reference_self_conflict_disjunction(
                    model_data=model_data,
                    movement_problem=movement,
                    trajectory=trajectory,
                    waiting_policy=trajectory_problem.waiting_policy,
                    name=f"reservoir_anchor_conflict[{conflict_round}]",
                )
                conflict_round += 1
                model_data.model.update()
                continue
            column = ddd_trajectory_column(
                trajectory,
                instance_fingerprint=(
                    instance_fingerprint
                    or ddd_trajectory_instance_fingerprint(artifact)
                ),
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
                certified_reduced_cost_lower_bound=None,
                detail="finite dispatch anchor; primal column only",
                self_conflict_round_count=conflict_round,
                **_pricing_model_metrics(model_data),
            )


def _reservoir_anchor_time_expanded_arc_count(
    *,
    movement_problem: DddMovementProblem,
    start: DddFixedStart,
    cutoff: int,
) -> int:
    """Count a fixed-anchor DAG cheaply and stop once its configured cap is passed."""

    states = deterministic_route_state_ids(
        movement_problem,
        start_state_id=start.state_id,
        max_visit_count=start.max_visit_count,
        error_context="reservoir anchor preflight",
    )
    nodes = {(start.time_tick, True)}
    arc_count = 0
    for state_id in states[:-1]:
        next_nodes: set[tuple[int, bool]] = set()
        for source_tick, source_active in nodes:
            options: tuple[DddRouteOption | None, ...] = (
                tuple(movement_problem.route_options_by_state_id[state_id])
                if source_active
                else (None,)
            )
            arc_count += len(options)
            if arc_count > cutoff:
                return arc_count
            for option in options:
                target_tick = (
                    source_tick
                    if option is None
                    else source_tick + option.duration_tick
                )
                target_active = (
                    option is not None
                    and target_tick <= movement_problem.operational_end_tick
                )
                next_nodes.add((target_tick, target_active))
        nodes = next_nodes
    return arc_count


def _oip_pricing_start_classes(
    *,
    trajectory_problem: DddTrajectoryProblem,
    artifact: EanBuildArtifact,
) -> tuple[_DddOipPricingStartClass, ...]:
    domain = trajectory_problem.start_domain
    if not isinstance(domain, DddOptimizedInitialPlacementDomain):
        raise ValueError("OIP start classes require an optimized-placement domain")
    movement_problem = trajectory_problem.structural_movement_problem
    timing_by_state = {item.switch_id: item for item in artifact.timings}
    epsilon_ticks = 10.0
    start_classes: list[_DddOipPricingStartClass] = []
    for phase_index, state_id in enumerate(domain.phase_state_ids):
        maximum_visits = domain.maximum_visit_count - phase_index
        if maximum_visits <= 0:
            continue
        first_options = movement_problem.route_options_by_state_id[state_id]
        station_lower = -float(
            max(option.exit_switch_offset_tick for option in first_options)
        )
        start_classes.append(
            _DddOipPricingStartClass(
                index=len(start_classes),
                phase_index=phase_index,
                state_id=state_id,
                maximum_visits=maximum_visits,
                station_start=True,
                start_bounds=(station_lower, 0.0),
                previous_service=None,
            )
        )
        previous_state = domain.phase_state_ids[
            (phase_index - 1) % len(domain.phase_state_ids)
        ]
        rope_ticks = float(
            ddd_seconds_to_tick(
                timing_by_state[previous_state].rope_to_next_switch_seconds
            )
        )
        if rope_ticks <= 2 * epsilon_ticks:
            continue
        exit_checkpoint = next(
            checkpoint
            for checkpoint in artifact.headway_checkpoints
            if checkpoint.switch_id == previous_state
            and checkpoint.kind.value == "exit_switch"
        )
        exit_rule = artifact.headway_rule_for_checkpoint(exit_checkpoint)
        needs_previous_behavior = (
            exit_rule.minimum_seconds != exit_rule.maximum_seconds
            or artifact.initial_boundary_service_resource(previous_state) is not None
        )
        previous_decisions = {
            option.decision
            for option in movement_problem.route_options_by_state_id[previous_state]
        }
        if needs_previous_behavior:
            previous_behaviors = tuple(
                behavior
                for behavior, decision in (
                    (False, DddRouteDecision.SKIP),
                    (True, DddRouteDecision.STOP),
                )
                if decision in previous_decisions
            )
        else:
            previous_behaviors = (None,)
        for previous_service in previous_behaviors:
            start_classes.append(
                _DddOipPricingStartClass(
                    index=len(start_classes),
                    phase_index=phase_index,
                    state_id=state_id,
                    maximum_visits=maximum_visits,
                    station_start=False,
                    start_bounds=(epsilon_ticks, rope_ticks - epsilon_ticks),
                    previous_service=previous_service,
                )
            )
    if not start_classes:
        raise ValueError("OIP pricing domain has no start classes")
    return tuple(start_classes)


@dataclass
class _ExactPricingModel:
    model: gp.Model
    start: DddFixedStart
    states: tuple[str, ...]
    event_time: tuple[gp.Var, ...]
    active: tuple[gp.Var, ...]
    route_selection: dict[tuple[int, str], gp.Var]
    wait_steps: tuple[gp.Var, ...]
    ride_count_bits: dict[str, tuple[tuple[int, gp.Var], ...]]
    ride_count_expressions: dict[str, gp.LinExpr]
    resource_window_membership: dict[tuple[str, int, str, int], gp.Var]
    relative_arc_variables: tuple[_DddRelativeArcVariable, ...] = ()
    origin: gp.Var | None = None
    relative_node_count: int = 0
    relative_arc_count: int = 0
    origin_product_count: int = 0
    model_build_seconds: float = 0.0


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
    excluded_timed_support_signatures: frozenset[
        tuple[tuple[str, float], ...]
    ] = frozenset(),
    resource_window_rows: tuple[DddTrajectoryResourceWindowRow, ...],
    continuous_start_bounds_ticks: tuple[float, float] | None = None,
    visit_index_offset: int = 0,
    station_boundary: bool = False,
    relative_graph: _DddRelativeTimeGraph | None = None,
    waiting_policy: DddTrajectoryWaitingPolicy | None = None,
) -> _ExactPricingModel:
    build_started = perf_counter()
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
    waiting_policy = waiting_policy or DddTrajectoryWaitingPolicy()
    waiting_policy.validate(movement_problem.core)
    event_time_bounds = _event_time_bounds(
        movement_problem=movement_problem,
        start=start,
        states=states,
        formulation=formulation,
        waiting_policy=waiting_policy,
    )
    active_event_time_bounds = _active_event_time_bounds(
        movement_problem=movement_problem,
        start=start,
        states=states,
        waiting_policy=waiting_policy,
    )
    if continuous_start_bounds_ticks is not None:
        lower, upper = continuous_start_bounds_ticks
        maximum_duration = max(
            option.duration_tick for option in movement_problem.route_options
        )
        bounds = [(lower, upper)]
        active_bounds = [(lower, upper)]
        current_lower = lower
        current_upper = upper
        continuous_horizon_tail = (
            movement_problem.operational_end_tick
            + DDD_OIP_HORIZON_TAIL_EPSILON_SECONDS / DDD_TIME_TICK_SECONDS
        )
        for state_id in states[:-1]:
            durations = tuple(
                option.duration_tick
                for option in movement_problem.route_options_by_state_id[state_id]
            )
            current_lower += min(durations)
            station_id = movement_problem.route_options_by_state_id[state_id][0].station_id
            current_upper += max(durations) + ddd_seconds_to_tick(
                waiting_policy.maximum_wait_seconds(station_id)
            )
            bounds.append(
                (
                    min(current_lower, continuous_horizon_tail),
                    current_upper + maximum_duration,
                )
            )
            active_lower = min(
                current_lower,
                movement_problem.operational_end_tick,
            )
            active_upper = max(
                active_lower,
                min(current_upper, movement_problem.operational_end_tick),
            )
            active_bounds.append(
                (active_lower, active_upper)
            )
        event_time_bounds = tuple(bounds)
        active_event_time_bounds = tuple(active_bounds)
        if _is_relative_oip_formulation(formulation) and relative_graph is not None:
            terminal_arcs = tuple(
                arc for arc in relative_graph.arcs if not arc.continues
            )
            if not terminal_arcs:
                raise ValueError("relative OIP graph has no horizon-crossing arc")
            event_time_bounds = (
                *event_time_bounds[:-1],
                (
                    min(lower + arc.target_elapsed_tick for arc in terminal_arcs),
                    max(upper + arc.target_elapsed_tick for arc in terminal_arcs),
                ),
            )
    relative_arc_variables: tuple[_DddRelativeArcVariable, ...] = ()
    origin: gp.Var | None = None
    if formulation is DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH:
        (
            event_time,
            active,
            route_selection,
            wait_steps,
            active_time_membership,
            route_time_membership,
            time_expanded_arcs,
        ) = _add_time_expanded_route_core(
            model=model,
            movement_problem=movement_problem,
            start=start,
            states=states,
            event_time_bounds=event_time_bounds,
            waiting_policy=waiting_policy,
        )
    elif _is_relative_oip_formulation(formulation):
        if continuous_start_bounds_ticks is None or relative_graph is None:
            raise ValueError(
                "relative OIP pricing requires a continuous start class and graph"
            )
        (
            event_time,
            active,
            route_selection,
            relative_arc_variables,
            origin,
        ) = _add_relative_time_expanded_route_core(
            model=model,
            movement_problem=movement_problem,
            start=start,
            states=states,
            event_time_bounds=event_time_bounds,
            start_bounds=continuous_start_bounds_ticks,
            graph=relative_graph,
        )
        active_time_membership = {}
        route_time_membership = {}
        time_expanded_arcs = ()
    else:
        event_time, active, route_selection, wait_steps = _add_compact_route_core(
            model=model,
            movement_problem=movement_problem,
            start=start,
            states=states,
            event_time_bounds=event_time_bounds,
            continuous_start=(continuous_start_bounds_ticks is not None),
            waiting_policy=waiting_policy,
        )
        active_time_membership = {}
        route_time_membership = {}
        time_expanded_arcs = ()
    if _is_relative_oip_formulation(formulation):
        wait_steps = tuple(
            model.addVar(lb=0.0, ub=0.0, vtype=GRB.INTEGER, name=f"wait_steps[{index}]")
            for index in range(start.max_visit_count)
        )
    if station_boundary:
        first_options = movement_problem.route_options_by_state_id[states[0]]
        model.addConstr(
            event_time[0]
            + gp.quicksum(
                option.exit_switch_offset_tick * route_selection[0, option.id]
                for option in first_options
            )
            >= 0.0,
            name="oip_station_covers_boundary",
        )
    for index, sequence in enumerate(sorted(excluded_route_option_sequences)):
        _exclude_route_sequence(
            model,
            route_selection,
            sequence,
            name=f"excluded[{index}]",
        )
    if excluded_timed_support_signatures:
        if formulation is not DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH:
            raise ValueError(
                "timed-support exclusions require time_expanded_path pricing"
            )
        for index, signature in enumerate(
            sorted(excluded_timed_support_signatures)
        ):
            _exclude_time_expanded_timed_support(
                model=model,
                movement_problem=movement_problem,
                start=start,
                signature=signature,
                route_time_membership=route_time_membership,
                name=f"excluded_timed[{index}]",
            )

    resource_window_membership = (
        {}
        if _is_relative_oip_formulation(formulation)
        else _add_resource_window_pricing_terms(
            model=model,
            movement_problem=movement_problem,
            states=states,
            event_time=event_time,
            route_selection=route_selection,
            rows=resource_window_rows,
            duals=duals,
        )
    )

    definition = ean_passenger_objective_definition(objective)
    group_by_id = {group.id: group for group in passenger_build.demand_groups}
    earliest_event_time = [
        (
            continuous_start_bounds_ticks[0]
            if continuous_start_bounds_ticks is not None
            else start.time_tick
        )
    ]
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
    passenger_flow_by_candidate_arc: dict[
        tuple[str, int, int, str, int], gp.Var
    ] = {}
    relative_passenger_flow: dict[tuple[str, int, int], gp.Var] = {}
    relative_alight_visit_by_candidate: dict[str, int] = {}
    origin_product_count = 0
    for candidate in sorted(passenger_build.ride_candidates, key=lambda item: item.id):
        if candidate.cabin_id != start.cabin_id:
            continue
        board_visit_index = candidate.board_visit_index - visit_index_offset
        alight_visit_index = candidate.alight_visit_index - visit_index_offset
        if board_visit_index < 0 or alight_visit_index >= start.max_visit_count:
            continue
        if any(
            active_event_time_bounds[visit_index][0]
            > active_event_time_bounds[visit_index][1]
            for visit_index in (
                board_visit_index,
                alight_visit_index,
            )
        ):
            continue
        board_stop = unique_stop_route_option(
            movement_problem,
            states[board_visit_index],
            error_context="exact trajectory pricing",
        )
        alight_stop = unique_stop_route_option(
            movement_problem,
            states[alight_visit_index],
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
            (board_visit_index, board_offset)
            if definition.event is EanPassengerObjectiveEvent.BOARDING
            else (alight_visit_index, alight_offset)
        )
        wait_step_tick = (
            0
            if waiting_policy.step_seconds is None
            else ddd_seconds_to_tick(waiting_policy.step_seconds)
        )
        event_wait_expression: gp.LinExpr | float = (
            wait_step_tick * wait_steps[event_index]
            if definition.event is EanPassengerObjectiveEvent.BOARDING
            else 0.0
        )
        event_wait_upper = (
            ddd_seconds_to_tick(
                waiting_policy.maximum_wait_seconds(
                    movement_problem.route_options_by_state_id[
                        states[event_index]
                    ][0].station_id
                )
            )
            if definition.event is EanPassengerObjectiveEvent.BOARDING
            else 0.0
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
        earliest_alight = earliest_event_time[alight_visit_index] + alight_offset
        earliest_priced_event = earliest_event_time[event_index] + event_offset
        optimistic_unit_reduced_cost = (
            float(earliest_priced_event) * DDD_TIME_TICK_SECONDS
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
                board_visit_index=board_visit_index,
                alight_visit_index=alight_visit_index,
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
                    (
                        candidate.id,
                        visit_index,
                        source_tick,
                        option_id,
                        wait_tick,
                    ): variable
                    for (
                        visit_index,
                        source_tick,
                        option_id,
                        wait_tick,
                    ), variable in flow_by_arc.items()
                }
            )
            ride_count_expressions[candidate.id] = gp.quicksum(
                variable
                for (visit_index, _, _, _), variable in flow_by_arc.items()
                if visit_index == board_visit_index
            )
            continue
        if (
            formulation
            is DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP_FLOW
        ):
            if origin is None:
                raise RuntimeError("relative OIP origin is missing")
            relative_result = _add_relative_time_expanded_ride(
                model=model,
                candidate_id=candidate.id,
                board_visit_index=board_visit_index,
                alight_visit_index=alight_visit_index,
                board_option_id=board_stop.id,
                alight_option_id=alight_stop.id,
                board_offset=board_offset,
                alight_offset=alight_offset,
                release_tick=ddd_seconds_to_tick(group.release_time_seconds),
                service_end_tick=movement_problem.passenger_service_end_tick,
                objective_event=definition.event,
                constant_unit_cost=(-artifact.config.horizon_seconds - raw_demand_dual),
                upper=upper,
                origin=origin,
                origin_bounds=continuous_start_bounds_ticks,
                arcs=relative_arc_variables,
            )
            if relative_result is None:
                continue
            bits, flow_by_bit_arc, products = relative_result
            ride_count_bits[candidate.id] = bits
            relative_passenger_flow.update(
                {
                    (candidate.id, bit_index, arc_index): variable
                    for (bit_index, arc_index), variable in flow_by_bit_arc.items()
                }
            )
            relative_alight_visit_by_candidate[candidate.id] = alight_visit_index
            origin_product_count += products
            continue
        interval_relative = (
            formulation is DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP
        )
        used = (
            None
            if interval_relative
            else model.addVar(
                vtype=GRB.BINARY,
                name=f"ride_used[{candidate.id}]",
            )
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
                active_product_lower = (
                    active_event_time_bounds[event_index][0] + event_offset
                )
                active_product_upper = (
                    active_event_time_bounds[event_index][1]
                    + event_offset
                    + event_wait_upper
                )
                event_product = model.addVar(
                    # The product is zero when the passenger bit is zero, even
                    # if every reachable event time in this restricted start
                    # interval is negative.  Hence zero must belong to the
                    # variable domain on both sides of the active interval.
                    lb=float(min(0.0, active_product_lower)),
                    ub=float(
                        max(
                            0.0,
                            min(
                                movement_problem.passenger_service_end_tick,
                                active_product_upper,
                            ),
                        )
                    ),
                    obj=weight * DDD_TIME_TICK_SECONDS,
                    name=f"ride_event_bit[{candidate.id},{bit_index}]",
                )
            if formulation is DddTrajectoryPricingFormulation.LEGACY_INDICATORS:
                model.addGenConstrIndicator(
                    bit,
                    True,
                    event_product
                    == event_time[event_index]
                    + event_offset
                    + event_wait_expression,
                    name=f"ride_event_on[{candidate.id},{bit_index}]",
                )
                model.addGenConstrIndicator(
                    bit,
                    False,
                    event_product == 0,
                    name=f"ride_event_off[{candidate.id},{bit_index}]",
                )
            elif formulation in {
                DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
                DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP,
            }:
                _add_binary_event_product_convex_hull(
                    model=model,
                    product=event_product,
                    binary=bit,
                    event_time=event_time[event_index],
                    event_offset=event_offset,
                    additional_event_expression=event_wait_expression,
                    additional_event_upper=event_wait_upper,
                    global_event_lower=event_time_bounds[event_index][0],
                    global_event_upper=event_time_bounds[event_index][1],
                    active_event_lower=active_event_time_bounds[event_index][0],
                    active_event_upper=active_event_time_bounds[event_index][1],
                    name=f"ride_event_product[{candidate.id},{bit_index}]",
                )
                if (
                    formulation
                    is DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP
                ):
                    origin_product_count += 1
            bits.append((weight, bit))
        ride_count = gp.quicksum(weight * bit for weight, bit in bits)
        model.addConstr(
            ride_count <= upper,
            name=f"ride_count_upper[{candidate.id}]",
        )
        release_tick = ddd_seconds_to_tick(group.release_time_seconds)
        if interval_relative:
            board_expression = event_time[board_visit_index] + board_offset
            alight_expression = event_time[alight_visit_index] + alight_offset
            board_global_lower = event_time_bounds[board_visit_index][0] + board_offset
            alight_global_upper = (
                event_time_bounds[alight_visit_index][1] + alight_offset
            )
            release_big_m = max(0.0, release_tick - board_global_lower)
            horizon_big_m = max(
                0.0,
                alight_global_upper - movement_problem.passenger_service_end_tick,
            )
            for bit_index, (_, bit) in enumerate(bits):
                model.addConstr(
                    bit <= route_selection[board_visit_index, board_stop.id],
                    name=f"ride_board_stop[{candidate.id},{bit_index}]",
                )
                model.addConstr(
                    bit <= route_selection[alight_visit_index, alight_stop.id],
                    name=f"ride_alight_stop[{candidate.id},{bit_index}]",
                )
                model.addConstr(
                    board_expression >= release_tick - release_big_m * (1 - bit),
                    name=f"ride_release[{candidate.id},{bit_index}]",
                )
                model.addConstr(
                    alight_expression
                    <= movement_problem.passenger_service_end_tick
                    + horizon_big_m * (1 - bit),
                    name=f"ride_horizon[{candidate.id},{bit_index}]",
                )
        else:
            if used is None:
                raise RuntimeError("non-relative ride usage variable is missing")
            model.addConstr(
                ride_count <= upper * used,
                name=f"ride_count_used_upper[{candidate.id}]",
            )
            model.addConstr(
                ride_count >= used,
                name=f"ride_count_used_lower[{candidate.id}]",
            )
            model.addConstr(
                used <= route_selection[board_visit_index, board_stop.id],
                name=f"ride_board_stop[{candidate.id}]",
            )
            model.addConstr(
                used <= route_selection[alight_visit_index, alight_stop.id],
                name=f"ride_alight_stop[{candidate.id}]",
            )
        if formulation is DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH:
            board_path_mass = gp.quicksum(
                variable
                for (
                    visit_index,
                    option_id,
                    tick,
                    wait_tick,
                ), variable in route_time_membership.items()
                if visit_index == board_visit_index
                and option_id == board_stop.id
                and tick + board_offset + wait_tick >= release_tick
            )
            alight_path_mass = gp.quicksum(
                variable
                for (
                    visit_index,
                    option_id,
                    tick,
                    _,
                ), variable in route_time_membership.items()
                if visit_index == alight_visit_index
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
        if not interval_relative:
            if used is None:
                raise RuntimeError("ride usage variable is missing")
            model.addGenConstrIndicator(
                used,
                True,
                event_time[board_visit_index]
                + board_offset
                + wait_step_tick * wait_steps[board_visit_index]
                >= release_tick,
                name=f"ride_release[{candidate.id}]",
            )
            model.addGenConstrIndicator(
                used,
                True,
                event_time[alight_visit_index] + alight_offset
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
    elif formulation is DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP_FLOW:
        _add_relative_time_expanded_passenger_capacity(
            model=model,
            passenger_build=passenger_build,
            cabin_id=start.cabin_id,
            cabin_capacity=artifact.config.cabin_capacity,
            passenger_flow=relative_passenger_flow,
            alight_visit_by_candidate=relative_alight_visit_by_candidate,
            arcs=relative_arc_variables,
        )
    else:
        for visit_index in range(start.max_visit_count):
            onboard = tuple(
                unit
                for candidate in passenger_build.ride_candidates
                if candidate.cabin_id == start.cabin_id
                and candidate.id in ride_count_bits
                and candidate.board_visit_index - visit_index_offset
                <= visit_index
                < candidate.alight_visit_index - visit_index_offset
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
        wait_steps=wait_steps,
        ride_count_bits=ride_count_bits,
        ride_count_expressions=ride_count_expressions,
        resource_window_membership=resource_window_membership,
        relative_arc_variables=relative_arc_variables,
        origin=origin,
        relative_node_count=(
            0 if relative_graph is None else len(relative_graph.nodes)
        ),
        relative_arc_count=(0 if relative_graph is None else len(relative_graph.arcs)),
        origin_product_count=origin_product_count,
        model_build_seconds=perf_counter() - build_started,
    )


def _event_time_bounds(
    *,
    movement_problem: DddMovementProblem,
    start: DddFixedStart,
    states: tuple[str, ...],
    formulation: DddTrajectoryPricingFormulation,
    waiting_policy: DddTrajectoryWaitingPolicy | None = None,
) -> tuple[tuple[int, int], ...]:
    waiting_policy = waiting_policy or DddTrajectoryWaitingPolicy()
    maximum_duration = max(
        option.duration_tick for option in movement_problem.route_options
    )
    maximum_wait = max(
        (
            ddd_seconds_to_tick(
                waiting_policy.maximum_wait_seconds(option.station_id)
            )
            for option in movement_problem.route_options
        ),
        default=0,
    )
    global_upper = (
        movement_problem.operational_end_tick + maximum_duration + maximum_wait
    )
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
        station_id = movement_problem.route_options_by_state_id[state_id][0].station_id
        upper_if_active += max(durations) + ddd_seconds_to_tick(
            waiting_policy.maximum_wait_seconds(station_id)
        )
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
    waiting_policy: DddTrajectoryWaitingPolicy | None = None,
) -> tuple[tuple[int, int], ...]:
    waiting_policy = waiting_policy or DddTrajectoryWaitingPolicy()
    earliest = start.time_tick
    latest = start.time_tick
    bounds = [(earliest, latest)]
    for state_id in states[:-1]:
        durations = tuple(
            option.duration_tick
            for option in movement_problem.route_options_by_state_id[state_id]
        )
        earliest += min(durations)
        station_id = movement_problem.route_options_by_state_id[state_id][0].station_id
        latest += max(durations) + ddd_seconds_to_tick(
            waiting_policy.maximum_wait_seconds(station_id)
        )
        bounds.append(
            (
                earliest,
                min(latest, movement_problem.operational_end_tick),
            )
        )
    return tuple(bounds)


def _add_relative_time_expanded_route_core(
    *,
    model: gp.Model,
    movement_problem: DddMovementProblem,
    start: DddFixedStart,
    states: tuple[str, ...],
    event_time_bounds: tuple[tuple[float, float], ...],
    start_bounds: tuple[float, float],
    graph: _DddRelativeTimeGraph,
) -> tuple[
    tuple[gp.Var, ...],
    tuple[gp.Var, ...],
    dict[tuple[int, str], gp.Var],
    tuple[_DddRelativeArcVariable, ...],
    gp.Var,
]:
    origin = model.addVar(
        lb=float(start_bounds[0]),
        ub=float(start_bounds[1]),
        vtype=GRB.CONTINUOUS,
        name="origin",
    )
    event_time = tuple(
        model.addVar(
            lb=float(lower),
            ub=float(upper),
            vtype=GRB.CONTINUOUS,
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
    arc_variables = tuple(
        _DddRelativeArcVariable(
            arc=arc,
            variable=model.addVar(
                vtype=GRB.BINARY,
                name=f"relative_arc[{arc.index}]",
            ),
        )
        for arc in graph.arcs
    )
    outgoing_by_node: dict[tuple[int, str, int], list[_DddRelativeArcVariable]] = {}
    incoming_by_node: dict[tuple[int, str, int], list[_DddRelativeArcVariable]] = {}
    for item in arc_variables:
        arc = item.arc
        outgoing_by_node.setdefault(
            (arc.visit_index, arc.source_state_id, arc.source_elapsed_tick), []
        ).append(item)
        if arc.continues:
            incoming_by_node.setdefault(
                (
                    arc.visit_index + 1,
                    arc.target_state_id,
                    arc.target_elapsed_tick,
                ),
                [],
            ).append(item)
        model.addGenConstrIndicator(
            item.variable,
            True,
            origin + arc.source_elapsed_tick <= movement_problem.operational_end_tick,
            name=f"relative_source_horizon[{arc.index}]",
        )
        if arc.continues:
            model.addGenConstrIndicator(
                item.variable,
                True,
                origin + arc.target_elapsed_tick
                <= movement_problem.operational_end_tick,
                name=f"relative_continue_horizon[{arc.index}]",
            )
        else:
            tail_epsilon_tick = (
                DDD_OIP_HORIZON_TAIL_EPSILON_SECONDS / DDD_TIME_TICK_SECONDS
            )
            model.addGenConstrIndicator(
                item.variable,
                True,
                origin + arc.target_elapsed_tick
                >= movement_problem.operational_end_tick + tail_epsilon_tick,
                name=f"relative_terminal_horizon[{arc.index}]",
            )

    for node in graph.nodes:
        key = (node.visit_index, node.state_id, node.elapsed_tick)
        outgoing = gp.quicksum(item.variable for item in outgoing_by_node.get(key, ()))
        incoming = (
            1.0
            if node.visit_index == 0 and node.elapsed_tick == 0
            else gp.quicksum(item.variable for item in incoming_by_node.get(key, ()))
        )
        model.addConstr(
            outgoing == incoming,
            name=(f"relative_flow[{node.visit_index},{node.elapsed_tick}]"),
        )
    terminal_arcs = tuple(item for item in arc_variables if not item.arc.continues)
    model.addConstr(
        gp.quicksum(item.variable for item in terminal_arcs) == 1.0,
        name="relative_terminal",
    )
    for visit_index, state_id in enumerate(states[:-1]):
        layer_arcs = tuple(
            item for item in arc_variables if item.arc.visit_index == visit_index
        )
        model.addConstr(
            active[visit_index] == gp.quicksum(item.variable for item in layer_arcs),
            name=f"relative_active[{visit_index}]",
        )
        model.addGenConstrIndicator(
            active[visit_index],
            False,
            event_time[visit_index] == event_time_bounds[visit_index][0],
            name=f"relative_inactive_time[{visit_index}]",
        )
        for item in layer_arcs:
            model.addGenConstrIndicator(
                item.variable,
                True,
                event_time[visit_index] == origin + item.arc.source_elapsed_tick,
                name=f"relative_time[{item.arc.index}]",
            )
        for option in movement_problem.route_options_by_state_id[state_id]:
            model.addConstr(
                route_selection[visit_index, option.id]
                == gp.quicksum(
                    item.variable
                    for item in layer_arcs
                    if item.arc.option_id == option.id
                ),
                name=f"relative_route[{visit_index},{option.id}]",
            )
    model.addConstr(active[-1] == 0.0, name="relative_final_inactive")
    for item in terminal_arcs:
        model.addGenConstrIndicator(
            item.variable,
            True,
            event_time[-1] == origin + item.arc.target_elapsed_tick,
            name=f"relative_final_time[{item.arc.index}]",
        )
    return event_time, active, route_selection, arc_variables, origin


def _add_compact_route_core(
    *,
    model: gp.Model,
    movement_problem: DddMovementProblem,
    start: DddFixedStart,
    states: tuple[str, ...],
    event_time_bounds: tuple[tuple[float, float], ...],
    continuous_start: bool = False,
    waiting_policy: DddTrajectoryWaitingPolicy | None = None,
) -> tuple[
    tuple[gp.Var, ...],
    tuple[gp.Var, ...],
    dict[tuple[int, str], gp.Var],
    tuple[gp.Var, ...],
]:
    waiting_policy = waiting_policy or DddTrajectoryWaitingPolicy()
    horizon_tail = (
        DDD_OIP_HORIZON_TAIL_EPSILON_SECONDS / DDD_TIME_TICK_SECONDS
        if continuous_start
        else 1.0
    )
    event_time = tuple(
        model.addVar(
            lb=float(lower),
            ub=float(upper),
            vtype=(GRB.CONTINUOUS if continuous_start else GRB.INTEGER),
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
    wait_step_tick = (
        0
        if waiting_policy.step_seconds is None
        else ddd_seconds_to_tick(waiting_policy.step_seconds)
    )
    wait_steps = tuple(
        model.addVar(
            lb=0.0,
            ub=(
                waiting_policy.maximum_wait_seconds(
                    movement_problem.route_options_by_state_id[state_id][0].station_id
                )
                / waiting_policy.step_seconds
                if waiting_policy.step_seconds is not None
                else 0.0
            ),
            vtype=GRB.INTEGER,
            name=f"wait_steps[{visit_index}]",
        )
        for visit_index, state_id in enumerate(states[:-1])
    )
    if not continuous_start:
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
            )
            + wait_step_tick * wait_steps[visit_index],
            name=f"propagate_time[{visit_index}]",
        )
        stop_selection = gp.quicksum(
            route_selection[visit_index, option.id]
            for option in options
            if option.decision is DddRouteDecision.STOP
        )
        maximum_wait_steps = (
            waiting_policy.maximum_wait_seconds(options[0].station_id)
            / waiting_policy.step_seconds
            if waiting_policy.step_seconds is not None
            else 0.0
        )
        model.addConstr(
            wait_steps[visit_index]
            <= maximum_wait_steps * stop_selection,
            name=f"wait_only_stop[{visit_index}]",
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
                >= movement_problem.operational_end_tick + horizon_tail,
                name=f"inactive_after_horizon[{visit_index + 1}]",
            )
    model.addConstr(
        event_time[-1] >= movement_problem.operational_end_tick + horizon_tail,
        name="complete_horizon_coverage",
    )
    return event_time, active, route_selection, wait_steps


def _add_time_expanded_route_core(
    *,
    model: gp.Model,
    movement_problem: DddMovementProblem,
    start: DddFixedStart,
    states: tuple[str, ...],
    event_time_bounds: tuple[tuple[int, int], ...],
    waiting_policy: DddTrajectoryWaitingPolicy | None = None,
) -> tuple[
    tuple[gp.Var, ...],
    tuple[gp.Var, ...],
    dict[tuple[int, str], gp.Var],
    tuple[gp.Var, ...],
    dict[tuple[int, int], gp.LinExpr],
    dict[tuple[int, str, int, int], gp.Var],
    tuple[tuple[int, int, bool, str | None, int, int, bool, gp.Var], ...],
]:
    waiting_policy = waiting_policy or DddTrajectoryWaitingPolicy()
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

    wait_step_tick = (
        0
        if waiting_policy.step_seconds is None
        else ddd_seconds_to_tick(waiting_policy.step_seconds)
    )
    nodes_by_layer: list[set[tuple[int, bool]]] = [{(start.time_tick, True)}]
    arcs_by_layer: list[
        tuple[tuple[int, bool, str | None, int, int, bool, gp.Var], ...]
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
                wait_values = (
                    (0.0,)
                    if option is None
                    else waiting_policy.wait_values_seconds(option.station_id)
                )
                for wait_index, wait_seconds in enumerate(wait_values):
                    wait_tick = ddd_seconds_to_tick(wait_seconds)
                    if option is not None and wait_tick > 0:
                        if option.decision is DddRouteDecision.SKIP:
                            continue
                        if option.platform_exit_offset_seconds is None:
                            continue
                        minimum_exit_tick = (
                            source_tick
                            + ddd_seconds_to_tick(
                                option.platform_exit_offset_seconds
                            )
                        )
                        if minimum_exit_tick < ddd_seconds_to_tick(
                            waiting_policy.earliest_wait_time_seconds
                        ):
                            continue
                    target_tick = (
                        source_tick
                        if option is None
                        else source_tick + option.duration_tick + wait_tick
                    )
                    target_active = (
                        option is not None
                        and target_tick <= movement_problem.operational_end_tick
                    )
                    target = (target_tick, target_active)
                    next_nodes.add(target)
                    variable = model.addVar(
                        vtype=GRB.BINARY,
                        name=(
                            f"time_arc[{visit_index},{source_index},"
                            f"{option_index},{wait_index}]"
                        ),
                    )
                    arcs.append(
                        (
                            source_tick,
                            source_active,
                            option.id if option is not None else None,
                            wait_tick,
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
            for source_tick, source_active, _, _, _, _, variable in arcs
            if source_active and source_tick == tick
        )
        for visit_index, arcs in enumerate(arcs_by_layer)
        for tick, node_active in nodes_by_layer[visit_index]
        if node_active
    }
    route_time_membership = {
        (visit_index, option_id, source_tick, wait_tick): variable
        for visit_index, arcs in enumerate(arcs_by_layer)
        for source_tick, source_active, option_id, wait_tick, _, _, variable in arcs
        if source_active and option_id is not None
    }
    wait_steps = tuple(
        model.addVar(
            lb=0.0,
            ub=(
                waiting_policy.maximum_wait_seconds(
                    movement_problem.route_options_by_state_id[state_id][0].station_id
                )
                / waiting_policy.step_seconds
                if waiting_policy.step_seconds is not None
                else 0.0
            ),
            vtype=GRB.INTEGER,
            name=f"wait_steps[{visit_index}]",
        )
        for visit_index, state_id in enumerate(states[:-1])
    )

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
                source_tick * variable
                for source_tick, _, _, _, _, _, variable in arcs
            ),
            name=f"time_from_flow[{visit_index}]",
        )
        model.addConstr(
            active[visit_index]
            == gp.quicksum(
                variable
                for _, source_active, _, _, _, _, variable in arcs
                if source_active
            ),
            name=f"active_from_flow[{visit_index}]",
        )
        for option in movement_problem.route_options_by_state_id[states[visit_index]]:
            model.addConstr(
                route_selection[visit_index, option.id]
                == gp.quicksum(
                    variable
                    for _, _, option_id, _, _, _, variable in arcs
                    if option_id == option.id
                ),
                name=f"route_from_flow[{visit_index},{option.id}]",
            )
        model.addConstr(
            wait_step_tick * wait_steps[visit_index]
            == gp.quicksum(
                wait_tick * variable
                for _, _, _, wait_tick, _, _, variable in arcs
            ),
            name=f"wait_from_flow[{visit_index}]",
        )

    final_arcs = arcs_by_layer[-1]
    model.addConstr(
        event_time[-1]
        == gp.quicksum(
            target_tick * variable
            for _, _, _, _, target_tick, _, variable in final_arcs
        ),
        name="final_time_from_flow",
    )
    model.addConstr(
        gp.quicksum(
            variable
            for _, _, _, _, _, target_active, variable in final_arcs
            if not target_active
        )
        == 1.0,
        name="complete_horizon_coverage",
    )
    return (
        event_time,
        active,
        route_selection,
        wait_steps,
        active_time_membership,
        route_time_membership,
        tuple(
            (
                visit_index,
                source_tick,
                source_active,
                option_id,
                wait_tick,
                target_tick,
                target_active,
                variable,
            )
            for visit_index, arcs in enumerate(arcs_by_layer)
            for (
                source_tick,
                source_active,
                option_id,
                wait_tick,
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
    additional_event_expression: gp.LinExpr | gp.Var | float = 0.0,
    additional_event_upper: float = 0.0,
    global_event_lower: float,
    global_event_upper: float,
    active_event_lower: float,
    active_event_upper: float,
    name: str,
) -> None:
    global_lower = global_event_lower + event_offset
    global_upper = global_event_upper + event_offset + additional_event_upper
    active_lower = active_event_lower + event_offset
    active_upper = active_event_upper + event_offset + additional_event_upper
    event_expression = event_time + event_offset + additional_event_expression
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


def _add_relative_time_expanded_ride(
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
    origin: gp.Var,
    origin_bounds: tuple[float, float] | None,
    arcs: tuple[_DddRelativeArcVariable, ...],
) -> (
    tuple[
        tuple[tuple[int, gp.Var], ...],
        dict[tuple[int, int], gp.Var],
        int,
    ]
    | None
):
    if origin_bounds is None:
        raise ValueError("relative passenger pricing requires origin bounds")
    candidate_arcs = tuple(
        item
        for item in arcs
        if board_visit_index <= item.arc.visit_index <= alight_visit_index
        and (
            item.arc.visit_index != board_visit_index
            or item.arc.option_id == board_option_id
        )
        and (
            item.arc.visit_index != alight_visit_index
            or item.arc.option_id == alight_option_id
        )
    )
    if not any(
        item.arc.visit_index == board_visit_index for item in candidate_arcs
    ) or not any(item.arc.visit_index == alight_visit_index for item in candidate_arcs):
        return None

    bits: list[tuple[int, gp.Var]] = []
    flow_by_bit_arc: dict[tuple[int, int], gp.Var] = {}
    for bit_index in range(upper.bit_length()):
        weight = 1 << bit_index
        bit = model.addVar(
            vtype=GRB.BINARY,
            obj=weight * constant_unit_cost,
            name=f"ride_bit[{candidate_id},{bit_index}]",
        )
        product = model.addVar(
            lb=min(0.0, float(origin_bounds[0])),
            ub=max(0.0, float(origin_bounds[1])),
            obj=weight * DDD_TIME_TICK_SECONDS,
            name=f"ride_origin_bit[{candidate_id},{bit_index}]",
        )
        _add_binary_event_product_convex_hull(
            model=model,
            product=product,
            binary=bit,
            event_time=origin,
            event_offset=0,
            global_event_lower=origin_bounds[0],
            global_event_upper=origin_bounds[1],
            active_event_lower=origin_bounds[0],
            active_event_upper=origin_bounds[1],
            name=f"ride_origin_product[{candidate_id},{bit_index}]",
        )
        for item in candidate_arcs:
            arc = item.arc
            relative_objective = 0.0
            if (
                objective_event is EanPassengerObjectiveEvent.BOARDING
                and arc.visit_index == board_visit_index
            ):
                relative_objective = weight * ddd_tick_to_seconds(
                    arc.source_elapsed_tick + board_offset
                )
            elif (
                objective_event is EanPassengerObjectiveEvent.ALIGHTING
                and arc.visit_index == alight_visit_index
            ):
                relative_objective = weight * ddd_tick_to_seconds(
                    arc.source_elapsed_tick + alight_offset
                )
            flow = model.addVar(
                vtype=GRB.BINARY,
                obj=relative_objective,
                name=f"ride_flow[{candidate_id},{bit_index},{arc.index}]",
            )
            model.addConstr(
                flow <= item.variable,
                name=f"ride_flow_route[{candidate_id},{bit_index},{arc.index}]",
            )
            if arc.visit_index == board_visit_index:
                model.addGenConstrIndicator(
                    flow,
                    True,
                    origin + arc.source_elapsed_tick + board_offset >= release_tick,
                    name=f"ride_release[{candidate_id},{bit_index},{arc.index}]",
                )
            if arc.visit_index == alight_visit_index:
                model.addGenConstrIndicator(
                    flow,
                    True,
                    origin + arc.source_elapsed_tick + alight_offset
                    <= service_end_tick,
                    name=f"ride_horizon[{candidate_id},{bit_index},{arc.index}]",
                )
            flow_by_bit_arc[bit_index, arc.index] = flow

        board_flow = gp.quicksum(
            flow_by_bit_arc[bit_index, item.arc.index]
            for item in candidate_arcs
            if item.arc.visit_index == board_visit_index
        )
        alight_flow = gp.quicksum(
            flow_by_bit_arc[bit_index, item.arc.index]
            for item in candidate_arcs
            if item.arc.visit_index == alight_visit_index
        )
        model.addConstr(
            board_flow == bit, name=f"ride_board[{candidate_id},{bit_index}]"
        )
        model.addConstr(
            alight_flow == bit,
            name=f"ride_alight[{candidate_id},{bit_index}]",
        )
        for visit_index in range(board_visit_index + 1, alight_visit_index + 1):
            node_keys = {
                (item.arc.target_state_id, item.arc.target_elapsed_tick)
                for item in candidate_arcs
                if item.arc.visit_index == visit_index - 1 and item.arc.continues
            } | {
                (item.arc.source_state_id, item.arc.source_elapsed_tick)
                for item in candidate_arcs
                if item.arc.visit_index == visit_index
            }
            for state_id, elapsed_tick in sorted(node_keys):
                incoming = gp.quicksum(
                    flow_by_bit_arc[bit_index, item.arc.index]
                    for item in candidate_arcs
                    if item.arc.visit_index == visit_index - 1
                    and item.arc.continues
                    and item.arc.target_state_id == state_id
                    and item.arc.target_elapsed_tick == elapsed_tick
                )
                outgoing = gp.quicksum(
                    flow_by_bit_arc[bit_index, item.arc.index]
                    for item in candidate_arcs
                    if item.arc.visit_index == visit_index
                    and item.arc.source_state_id == state_id
                    and item.arc.source_elapsed_tick == elapsed_tick
                )
                model.addConstr(
                    incoming == outgoing,
                    name=(
                        f"ride_balance[{candidate_id},{bit_index},"
                        f"{visit_index},{elapsed_tick}]"
                    ),
                )
        bits.append((weight, bit))
    model.addConstr(
        gp.quicksum(weight * bit for weight, bit in bits) <= upper,
        name=f"ride_count_upper[{candidate_id}]",
    )
    return tuple(bits), flow_by_bit_arc, len(bits)


def _add_relative_time_expanded_passenger_capacity(
    *,
    model: gp.Model,
    passenger_build: EanPassengerCandidateBuildResult,
    cabin_id: int,
    cabin_capacity: float,
    passenger_flow: dict[tuple[str, int, int], gp.Var],
    alight_visit_by_candidate: dict[str, int],
    arcs: tuple[_DddRelativeArcVariable, ...],
) -> None:
    candidate_ids = {
        candidate.id
        for candidate in passenger_build.ride_candidates
        if candidate.cabin_id == cabin_id
    }
    for item in arcs:
        onboard = tuple(
            (1 << bit_index) * variable
            for (candidate_id, bit_index, arc_index), variable in passenger_flow.items()
            if candidate_id in candidate_ids
            and arc_index == item.arc.index
            and item.arc.visit_index < alight_visit_by_candidate[candidate_id]
        )
        if onboard:
            model.addConstr(
                gp.quicksum(onboard) <= cabin_capacity * item.variable,
                name=f"relative_capacity[{item.arc.index}]",
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
    arcs: tuple[
        tuple[int, int, bool, str | None, int, int, bool, gp.Var], ...
    ],
) -> dict[tuple[int, int, str, int], gp.Var]:
    flow_by_arc: dict[tuple[int, int, str, int], gp.Var] = {}
    arc_target_by_key: dict[tuple[int, int, str, int], int] = {}
    for arc_index, (
        visit_index,
        source_tick,
        source_active,
        option_id,
        wait_tick,
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
            option_id != board_option_id
            or source_tick + board_offset + wait_tick < release_tick
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
                objective_coefficient += ddd_tick_to_seconds(
                    source_tick + board_offset + wait_tick
                )
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
        key = (visit_index, source_tick, option_id, wait_tick)
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
            source_tick
            for layer, source_tick, _, _ in flow_by_arc
            if layer == visit_index
        }
        for tick in sorted(ticks):
            incoming = gp.quicksum(
                variable
                for key, variable in flow_by_arc.items()
                if key[0] == visit_index - 1 and arc_target_by_key[key] == tick
            )
            outgoing = gp.quicksum(
                variable
                for (layer, source_tick, _, _), variable in flow_by_arc.items()
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
    passenger_flow_by_candidate_arc: dict[
        tuple[str, int, int, str, int], gp.Var
    ],
    route_time_membership: dict[tuple[int, str, int, int], gp.Var],
) -> None:
    candidate_by_id = {
        candidate.id: candidate
        for candidate in passenger_build.ride_candidates
        if candidate.cabin_id == cabin_id
    }
    for (visit_index, option_id, source_tick, wait_tick), route_arc in sorted(
        route_time_membership.items()
    ):
        onboard = tuple(
            variable
            for (
                candidate_id,
                layer,
                tick,
                flow_option_id,
                flow_wait_tick,
            ), variable in passenger_flow_by_candidate_arc.items()
            if layer == visit_index
            and tick == source_tick
            and flow_option_id == option_id
            and flow_wait_tick == wait_tick
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
    waiting_policy: DddTrajectoryWaitingPolicy | None = None,
) -> DddReferenceTrajectory:
    waiting_policy = waiting_policy or DddTrajectoryWaitingPolicy()
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
                wait_seconds=(
                    float(model_data.wait_steps[visit_index].X)
                    * float(waiting_policy.step_seconds or 0.0)
                ),
            )
        )
    return DddReferenceTrajectory(cabin_id=start.cabin_id, visits=tuple(visits))


def _extract_oip_reference_trajectory(
    *,
    trajectory_problem: DddTrajectoryProblem,
    artifact: EanBuildArtifact,
    cabin_id: int,
    phase_index: int,
    station_start: bool,
    previous_service: bool | None,
    model_data: _ExactPricingModel,
) -> DddReferenceTrajectory:
    movement_problem = trajectory_problem.structural_movement_problem
    route_option_ids = []
    for visit_index, state_id in enumerate(model_data.states[:-1]):
        if model_data.active[visit_index].X < 0.5:
            break
        selected = tuple(
            option.id
            for option in movement_problem.route_options_by_state_id[state_id]
            if model_data.route_selection[visit_index, option.id].X >= 0.5
        )
        if len(selected) != 1:
            raise RuntimeError("exact OIP pricing route is not unique")
        route_option_ids.append(selected[0])
    return build_ddd_oip_reference_trajectory(
        problem=trajectory_problem,
        artifact=artifact,
        cabin_id=cabin_id,
        start=DddOipTrajectoryStart(
            phase_index=phase_index,
            station_start=station_start,
            first_switch_time_seconds=(
                float(model_data.event_time[0].X) * DDD_TIME_TICK_SECONDS
            ),
            previous_service=previous_service,
        ),
        route_option_ids=tuple(route_option_ids),
    )


def _add_reference_self_conflict_disjunction(
    *,
    model_data: _ExactPricingModel,
    movement_problem: DddMovementProblem,
    trajectory: DddReferenceTrajectory,
    waiting_policy: DddTrajectoryWaitingPolicy,
    name: str,
) -> None:
    conflicts = find_ddd_reference_conflicts(
        trajectory.resource_occurrences,
        movement_problem,
    )
    if not conflicts:
        raise RuntimeError("cannot add a self-conflict row without a conflict")
    conflict = conflicts[0]
    first_visit = trajectory.visits[conflict.first_visit_index]
    second_visit = trajectory.visits[conflict.second_visit_index]
    options_by_id = {option.id: option for option in movement_problem.route_options}
    first_option = options_by_id[first_visit.route_option_id]
    second_option = options_by_id[second_visit.route_option_id]
    first_usage = next(
        usage
        for usage in first_option.resource_usages
        if usage.resource_id == conflict.resource_id
    )
    second_usage = next(
        usage
        for usage in second_option.resource_usages
        if usage.resource_id == conflict.resource_id
    )
    resource = movement_problem.resources_by_id[conflict.resource_id]
    step_tick = (
        0
        if waiting_policy.step_seconds is None
        else ddd_seconds_to_tick(waiting_policy.step_seconds)
    )

    def occurrence_expressions(
        visit_index: int,
        usage: DddResourceUsage,
    ) -> tuple[gp.LinExpr, gp.LinExpr]:
        leader = (
            model_data.event_time[visit_index]
            + usage.leader_clear_offset_tick
            + usage.leader_clear_wait_coefficient
            * step_tick
            * model_data.wait_steps[visit_index]
        )
        follower = (
            model_data.event_time[visit_index]
            + usage.follower_enter_offset_tick
            + usage.follower_enter_wait_coefficient
            * step_tick
            * model_data.wait_steps[visit_index]
        )
        return leader, follower

    first_leader, first_follower = occurrence_expressions(
        first_visit.visit_index, first_usage
    )
    second_leader, second_follower = occurrence_expressions(
        second_visit.visit_index, second_usage
    )
    first_separation = first_usage.separation_after_tick(
        resource.minimum_headway_tick
    )
    second_separation = second_usage.separation_after_tick(
        resource.minimum_headway_tick
    )
    event_span = max(variable.UB for variable in model_data.event_time) - min(
        variable.LB for variable in model_data.event_time
    )
    maximum_offset = max(
        first_usage.leader_clear_offset_tick,
        first_usage.follower_enter_offset_tick,
        second_usage.leader_clear_offset_tick,
        second_usage.follower_enter_offset_tick,
    )
    maximum_wait = max(
        step_tick * model_data.wait_steps[first_visit.visit_index].UB,
        step_tick * model_data.wait_steps[second_visit.visit_index].UB,
    )
    big_m = max(
        1.0,
        event_span + 2 * (maximum_offset + maximum_wait) + resource.maximum_headway_tick,
    )
    order = model_data.model.addVar(vtype=GRB.BINARY, name=f"{name}_order")
    first_selected = model_data.route_selection[
        first_visit.visit_index, first_option.id
    ]
    second_selected = model_data.route_selection[
        second_visit.visit_index, second_option.id
    ]
    inactive = 2 - first_selected - second_selected
    model_data.model.addConstr(
        second_follower - first_leader
        >= first_separation - big_m * (1 - order) - big_m * inactive,
        name=f"{name}_forward",
    )
    model_data.model.addConstr(
        first_follower - second_leader
        >= second_separation - big_m * order - big_m * inactive,
        name=f"{name}_reverse",
    )


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


def _exclude_time_expanded_timed_support(
    *,
    model: gp.Model,
    movement_problem: DddMovementProblem,
    start: DddFixedStart,
    signature: tuple[tuple[str, float], ...],
    route_time_membership: dict[tuple[int, str, int, int], gp.Var],
    name: str,
) -> None:
    """Exclude one exact fixed-start Route/Wait path, not its route family."""

    if not signature:
        raise ValueError("timed-support exclusion cannot be empty")
    option_by_id = {option.id: option for option in movement_problem.route_options}
    source_tick = start.time_tick
    matching = []
    expected_state = start.state_id
    for visit_index, (option_id, wait_seconds) in enumerate(signature):
        option = option_by_id.get(option_id)
        if option is None or option.from_state_id != expected_state:
            raise ValueError("timed-support exclusion is not a valid cabin path")
        wait_tick = ddd_seconds_to_tick(wait_seconds)
        variable = route_time_membership.get(
            (visit_index, option_id, source_tick, wait_tick)
        )
        if variable is None:
            raise ValueError("timed-support exclusion lies outside the pricing DAG")
        matching.append(variable)
        source_tick += option.duration_tick + wait_tick
        expected_state = option.to_state_id
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
    waiting_policy: DddTrajectoryWaitingPolicy | None = None,
    instance_fingerprint: str | None = None,
) -> DddTrajectoryExactPricingResult | None:
    if model_data.model.SolCount <= 0:
        return None
    trajectory = _extract_reference_trajectory(
        movement_problem,
        start,
        model_data,
        tolerance_seconds=tolerance_seconds,
        waiting_policy=(
            waiting_policy or _waiting_policy_for_artifact(artifact)
        ),
    )
    try:
        validate_ddd_reference_trajectory(
            movement_problem,
            trajectory,
            tolerance_seconds=tolerance_seconds,
            waiting_policy=(
                waiting_policy or _waiting_policy_for_artifact(artifact)
            ),
        )
    except DddReferenceResourceConflictError:
        return None
    column = ddd_trajectory_column(
        trajectory,
        instance_fingerprint=(
            instance_fingerprint or ddd_trajectory_instance_fingerprint(artifact)
        ),
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
        "relative_node_count": model_data.relative_node_count,
        "relative_arc_count": model_data.relative_arc_count,
        "origin_product_count": model_data.origin_product_count,
        "model_build_seconds": model_data.model_build_seconds,
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
