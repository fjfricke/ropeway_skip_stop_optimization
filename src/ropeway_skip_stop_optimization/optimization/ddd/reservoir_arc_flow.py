from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Callable, Mapping
from threading import Event, Lock, Thread

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.anonymous_reservoir_network import (
    DddAnonymousReservoirArc,
    DddAnonymousReservoirNetwork,
    DddAnonymousReservoirNetworkBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_network import (
    DddArcFlowBuildTimeLimitError,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import DddRouteDecision
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
    DddReservoirArcFlowProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_passenger import (
    DddReservoirPassengerDomainBuilder,
    DddReservoirPassengerModel,
    DddReservoirPassengerModelBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_tick_to_seconds,
)


class DddReservoirArcFlowStatus(StrEnum):
    BUILD_ONLY_COMPLETE = "build_only_complete"
    INTEGER_OPTIMAL = "integer_optimal"
    PRIMARY_OPTIMAL_SECONDARY_OPEN = "primary_optimal_secondary_open"
    TIME_LIMIT_WITH_CERTIFIED_INTERVAL = "time_limit_with_certified_interval"
    UNKNOWN_NO_FEASIBLE_SEED = "unknown_no_feasible_seed"
    MOVEMENT_INFEASIBLE = "movement_infeasible"
    BUILD_LIMIT = "build_limit"
    INTERNAL_CERTIFICATE_ERROR = "internal_certificate_error"
    INTERNAL_VALIDATION_ERROR = "internal_validation_error"


@dataclass(frozen=True, slots=True)
class DddReservoirArcFlowSolveConfig:
    total_time_limit_seconds: float = 600.0
    threads: int = 8
    seed: int = 0
    mip_focus: int = 1
    mip_gap: float = 0.0
    output_flag: bool = False
    progress_interval_seconds: float = 30.0
    nodefile_start_gb: float = 8.0
    soft_memory_limit_gb: float = 28.0
    nodefile_dir: Path | None = None
    checkpoint_path: Path | None = None

    def validate(self) -> None:
        if not math.isfinite(self.total_time_limit_seconds) or self.total_time_limit_seconds <= 0:
            raise ValueError("reservoir total time limit must be positive and finite")
        if self.threads <= 0 or self.seed < 0 or self.mip_focus not in range(4):
            raise ValueError("reservoir solver controls are invalid")
        if not 0 <= self.mip_gap <= 1:
            raise ValueError("reservoir MIP gap must lie in [0, 1]")
        if self.progress_interval_seconds <= 0:
            raise ValueError("reservoir progress interval must be positive")
        if self.nodefile_start_gb <= 0 or self.soft_memory_limit_gb <= 0:
            raise ValueError("reservoir memory controls must be positive")


@dataclass(frozen=True, slots=True)
class DddReservoirArcFlowProgress:
    phase: str
    elapsed_seconds: float
    remaining_seconds: float
    primary_lower_bound: float | None
    primary_upper_bound: float | None
    served_lower_bound: float | None
    served_upper_bound: float | None
    secondary_lower_bound: float | None
    secondary_upper_bound: float | None
    dispatched_fleet_count: int | None
    node_count: float
    solution_count: int
    movement_variable_count: int
    passenger_variable_count: int
    linear_constraint_count: int
    resource_row_count: int
    network_node_count: int
    network_arc_count: int
    peak_rss_gb: float


@dataclass(frozen=True, slots=True)
class DddAnonymousReservoirPath:
    cabin_id: int
    dispatch_arc_id: str
    movement_arc_ids: tuple[str, ...]
    recovery_arc_id: str


@dataclass(frozen=True, slots=True)
class DddReservoirPassengerMetrics:
    total_demand: int
    served_passenger_count: int
    unserved_passenger_count: int
    journey_time_passenger_seconds: float


@dataclass(frozen=True, slots=True)
class DddReservoirAllStopReference:
    selected_arc_ids: tuple[str, ...]
    paths: tuple[DddAnonymousReservoirPath, ...]
    onboard_values: tuple[tuple[str, str, float], ...]
    board_values: tuple[tuple[str, str, float], ...]
    alight_values: tuple[tuple[str, str, float], ...]
    unserved_values: tuple[tuple[str, float], ...]
    metrics: DddReservoirPassengerMetrics
    validated: bool


@dataclass(frozen=True, slots=True)
class DddReservoirArcFlowResult:
    status: DddReservoirArcFlowStatus
    problem_fingerprint: str
    network_fingerprint: str | None
    primary_lower_bound: float
    primary_upper_bound: float | None
    served_lower_bound: float | None
    served_upper_bound: float
    primary_absolute_gap: float | None
    secondary_lower_bound: float | None
    secondary_upper_bound: float | None
    dispatched_fleet_count: int | None
    peak_active_fleet_count: int | None
    paths: tuple[DddAnonymousReservoirPath, ...]
    passenger_metrics: DddReservoirPassengerMetrics | None
    all_stop_reference_unserved: int | None
    all_stop_reference_journey_time: float | None
    all_stop_seed_accepted: bool
    seed_provenance: str | None
    network_node_count: int
    network_arc_count: int
    movement_variable_count: int
    passenger_variable_count: int
    movement_constraint_count: int
    passenger_constraint_count: int
    resource_row_count: int
    linear_constraint_count: int
    solver_node_count: float
    solver_solution_count: int
    network_build_seconds: float
    model_build_seconds: float
    primary_solve_seconds: float
    secondary_solve_seconds: float
    validation_seconds: float
    total_seconds: float
    peak_rss_gb: float
    detail: str | None = None
    primary_solver_status_code: int | None = None
    primary_solver_status: str | None = None
    secondary_solver_status_code: int | None = None
    secondary_solver_status: str | None = None

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


DddReservoirProgressHook = Callable[[DddReservoirArcFlowProgress], None]


class DddReservoirProgressHeartbeat:
    def __init__(
        self,
        *,
        hook: DddReservoirProgressHook | None,
        initial: DddReservoirArcFlowProgress,
        total_time_limit_seconds: float,
        interval_seconds: float,
    ) -> None:
        self._hook = hook
        self._current = initial
        self._total = total_time_limit_seconds
        self._interval = interval_seconds
        self._started = perf_counter()
        self._lock = Lock()
        self._publish_lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._hook is None:
            return
        self._publish()
        self._thread = Thread(target=self._run, daemon=True, name="ddd-reservoir-progress")
        self._thread.start()

    def update(self, progress: DddReservoirArcFlowProgress) -> None:
        with self._lock:
            self._current = progress

    def stop(self) -> None:
        if self._hook is None:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._interval + 1.0))
        self._publish()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._publish()

    def _publish(self) -> None:
        if self._hook is None:
            return
        elapsed = perf_counter() - self._started
        with self._lock:
            current = self._current
        sample = replace(
            current,
            elapsed_seconds=elapsed,
            remaining_seconds=max(0.0, self._total - elapsed),
            peak_rss_gb=_peak_rss_gb(),
        )
        with self._publish_lock:
            self._hook(sample)


@dataclass(slots=True)
class _DddReservoirMovementMaster:
    model: gp.Model
    problem: DddReservoirArcFlowProblem
    network: DddAnonymousReservoirNetwork
    route_by_arc_id: dict[str, gp.Var]
    movement_constraint_count: int
    resource_row_count: int

    def selected_arc_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                arc_id
                for arc_id, variable in self.route_by_arc_id.items()
                if variable.X > 0.5
            )
        )

    def apply_start(self, selected_arc_ids: tuple[str, ...]) -> None:
        selected = set(selected_arc_ids)
        unknown = selected - set(self.route_by_arc_id)
        if unknown:
            raise ValueError("reservoir MIP start references unknown arcs")
        for arc_id, variable in self.route_by_arc_id.items():
            variable.Start = float(arc_id in selected)


@dataclass(frozen=True, slots=True)
class _DddReservoirMovementMasterBuilder:
    def build(
        self,
        *,
        model: gp.Model,
        problem: DddReservoirArcFlowProblem,
        network: DddAnonymousReservoirNetwork,
    ) -> _DddReservoirMovementMaster:
        route = {
            arc.id: model.addVar(
                lb=0.0,
                ub=1.0,
                vtype=GRB.BINARY,
                name=f"reservoir_route[{index}]",
            )
            for index, arc in enumerate(network.arcs)
        }
        incoming: dict[str, list[DddAnonymousReservoirArc]] = defaultdict(list)
        outgoing: dict[str, list[DddAnonymousReservoirArc]] = defaultdict(list)
        for arc in network.arcs:
            if arc.target_node_id is not None:
                incoming[arc.target_node_id].append(arc)
            if arc.source_node_id is not None:
                outgoing[arc.source_node_id].append(arc)
        count = 0
        for node in network.nodes:
            node_in = tuple(route[arc.id] for arc in incoming.get(node.id, ()))
            node_out = tuple(route[arc.id] for arc in outgoing.get(node.id, ()))
            model.addConstr(
                gp.quicksum(node_in) == gp.quicksum(node_out),
                name=f"reservoir_flow[{count}]",
            )
            model.addConstr(
                gp.quicksum(node_in) <= 1,
                name=f"reservoir_node_capacity[{count}]",
            )
            count += 2
        dispatch = tuple(route[arc.id] for arc in network.dispatch_arcs)
        recovery = tuple(route[arc.id] for arc in network.recovery_arcs)
        model.addConstr(
            gp.quicksum(dispatch) == gp.quicksum(recovery),
            name="reservoir_fleet_balance",
        )
        model.addConstr(
            gp.quicksum(dispatch) <= problem.available_fleet_count,
            name="reservoir_fleet_cap",
        )
        count += 2
        resource_rows = 0
        for clique in network.resource_cliques:
            if len(clique.coefficients) == 1 and clique.coefficients[0][1] == 1:
                continue
            model.addConstr(
                gp.quicksum(
                    coefficient * route[arc_id]
                    for arc_id, coefficient in clique.coefficients
                )
                <= 1,
                name=f"reservoir_resource[{resource_rows}]",
            )
            resource_rows += 1
        model.update()
        return _DddReservoirMovementMaster(
            model=model,
            problem=problem,
            network=network,
            route_by_arc_id=route,
            movement_constraint_count=count,
            resource_row_count=resource_rows,
        )


@dataclass(frozen=True, slots=True)
class DddReservoirAllStopReferenceBuilder:
    time_limit_seconds: float = 120.0

    def build(
        self,
        problem: DddReservoirArcFlowProblem,
        network: DddAnonymousReservoirNetwork,
    ) -> DddReservoirAllStopReference:
        count = problem.all_stop_maximum_cabin_count
        if count is None or count > problem.available_fleet_count:
            raise ValueError("all-stop reference does not fit the reservoir fleet")
        selected = _select_all_stop_reference_arcs(problem, network)
        paths = decompose_ddd_anonymous_reservoir_paths(network, selected)
        if len(paths) != count:
            raise RuntimeError("all-stop reference dispatch count is inconsistent")
        validate_ddd_anonymous_reservoir_selection(problem, network, selected)
        model = gp.Model("ddd_reservoir_all_stop_reference")
        model.Params.OutputFlag = 0
        model.Params.Threads = 1
        model.Params.TimeLimit = self.time_limit_seconds
        active_movement = frozenset(
            arc_id
            for arc_id in selected
            if network.arc_by_id[arc_id].is_movement
        )
        route = {
            arc.id: model.addVar(
                lb=1.0,
                ub=1.0,
                vtype=GRB.BINARY,
                name=f"reference_route[{index}]",
            )
            for index, arc in enumerate(network.movement_arcs)
            if arc.id in active_movement
        }
        passenger = DddReservoirPassengerModelBuilder().build(
            model=model,
            problem=problem,
            network=network,
            route_by_arc_id=route,
            active_movement_arc_ids=active_movement,
        )
        model.setObjective(passenger.total_unserved_expression, GRB.MINIMIZE)
        model.optimize()
        if model.Status != GRB.OPTIMAL:
            raise RuntimeError("all-stop Passenger reference was not solved exactly")
        unserved = int(round(model.ObjVal))
        model.addConstr(
            passenger.total_unserved_expression == unserved,
            name="reference_fixed_unserved",
        )
        model.setObjective(passenger.journey_time_expression(problem), GRB.MINIMIZE)
        model.optimize()
        if model.Status != GRB.OPTIMAL:
            raise RuntimeError("all-stop journey-time reference was not solved exactly")
        metrics = DddReservoirPassengerMetrics(
            total_demand=problem.total_demand,
            served_passenger_count=problem.total_demand - unserved,
            unserved_passenger_count=unserved,
            journey_time_passenger_seconds=float(model.ObjVal),
        )
        return DddReservoirAllStopReference(
            selected_arc_ids=selected,
            paths=paths,
            onboard_values=tuple(
                sorted((*key, variable.X) for key, variable in passenger.onboard_by_group_arc.items())
            ),
            board_values=tuple(
                sorted((*key, variable.X) for key, variable in passenger.board_by_group_arc.items())
            ),
            alight_values=tuple(
                sorted((*key, variable.X) for key, variable in passenger.alight_by_group_arc.items())
            ),
            unserved_values=tuple(
                sorted((key, variable.X) for key, variable in passenger.unserved_by_group.items())
            ),
            metrics=metrics,
            validated=True,
        )


@dataclass(slots=True)
class DddReservoirArcFlowOptimizer:
    config: DddReservoirArcFlowSolveConfig = DddReservoirArcFlowSolveConfig()

    def solve(
        self,
        problem: DddReservoirArcFlowProblem,
        *,
        progress_hook: DddReservoirProgressHook | None = None,
        resume_checkpoint_path: Path | None = None,
        import_checkpoint_path: Path | None = None,
        build_only: bool = False,
    ) -> DddReservoirArcFlowResult:
        self.config.validate()
        problem.validate()
        initial = DddReservoirArcFlowProgress(
            phase="build",
            elapsed_seconds=0.0,
            remaining_seconds=self.config.total_time_limit_seconds,
            primary_lower_bound=0.0,
            primary_upper_bound=None,
            served_lower_bound=None,
            served_upper_bound=float(problem.total_demand),
            secondary_lower_bound=None,
            secondary_upper_bound=None,
            dispatched_fleet_count=None,
            node_count=0.0,
            solution_count=0,
            movement_variable_count=0,
            passenger_variable_count=0,
            linear_constraint_count=0,
            resource_row_count=0,
            network_node_count=0,
            network_arc_count=0,
            peak_rss_gb=_peak_rss_gb(),
        )
        heartbeat = DddReservoirProgressHeartbeat(
            hook=progress_hook,
            initial=initial,
            total_time_limit_seconds=self.config.total_time_limit_seconds,
            interval_seconds=self.config.progress_interval_seconds,
        )
        heartbeat.start()
        try:
            return self._solve(
                problem,
                progress_hook=heartbeat.update,
                resume_checkpoint_path=resume_checkpoint_path,
                import_checkpoint_path=import_checkpoint_path,
                build_only=build_only,
            )
        finally:
            heartbeat.stop()

    def _solve(
        self,
        problem: DddReservoirArcFlowProblem,
        *,
        progress_hook: DddReservoirProgressHook | None,
        resume_checkpoint_path: Path | None,
        import_checkpoint_path: Path | None,
        build_only: bool,
    ) -> DddReservoirArcFlowResult:
        started = perf_counter()
        deadline = started + self.config.total_time_limit_seconds
        self._publish(progress_hook, "build", started, problem, None, None)
        try:
            network = DddAnonymousReservoirNetworkBuilder().build(
                problem,
                deadline_monotonic=deadline,
            )
        except DddArcFlowBuildTimeLimitError as error:
            return self._empty_result(
                problem,
                started,
                DddReservoirArcFlowStatus.BUILD_LIMIT,
                str(error),
            )
        network_build_seconds = perf_counter() - started
        if build_only:
            try:
                domain = DddReservoirPassengerDomainBuilder().build(
                    problem,
                    network,
                    deadline_monotonic=deadline,
                )
            except DddArcFlowBuildTimeLimitError as error:
                return self._empty_result(
                    problem,
                    started,
                    DddReservoirArcFlowStatus.BUILD_LIMIT,
                    str(error),
                    network=network,
                    network_build_seconds=network_build_seconds,
                )
            passenger_variables = (
                sum(len(arc_ids) for _, arc_ids in domain.allowed_arc_ids_by_group)
                + len(domain.board_events)
                + len(domain.alight_events)
                + len(problem.demand_groups)
            )
            result = self._empty_result(
                problem,
                started,
                DddReservoirArcFlowStatus.BUILD_ONLY_COMPLETE,
                "build-only network completed",
                network=network,
                network_build_seconds=network_build_seconds,
            )
            return replace(
                result,
                movement_variable_count=len(network.arcs),
                passenger_variable_count=passenger_variables,
                resource_row_count=len(network.resource_cliques),
                peak_rss_gb=_peak_rss_gb(),
            )
        self._publish(
            progress_hook,
            "reference_build",
            started,
            problem,
            network,
            None,
        )
        reference_started = perf_counter()
        reference = DddReservoirAllStopReferenceBuilder(
            time_limit_seconds=max(1.0, min(120.0, deadline - perf_counter()))
        ).build(problem, network)
        if self.config.checkpoint_path is not None:
            write_ddd_reservoir_reference_checkpoint(
                self.config.checkpoint_path,
                problem=problem,
                network=network,
                reference=reference,
            )
        self._publish(
            progress_hook,
            "model_build",
            started,
            problem,
            network,
            None,
            external_primary_upper=float(reference.metrics.unserved_passenger_count),
        )
        model = gp.Model("ddd_anonymous_reservoir_arc_flow")
        _configure_model(model, self.config, deadline - perf_counter())
        movement = _DddReservoirMovementMasterBuilder().build(
            model=model,
            problem=problem,
            network=network,
        )
        passenger = DddReservoirPassengerModelBuilder().build(
            model=model,
            problem=problem,
            network=network,
            route_by_arc_id=movement.route_by_arc_id,
            deadline_monotonic=deadline,
        )
        model_build_seconds = perf_counter() - reference_started
        movement.apply_start(reference.selected_arc_ids)
        _apply_reference_passenger_start(passenger, reference)
        seed_provenance = "validated_all_stop_reference"
        if resume_checkpoint_path is not None:
            selected, passenger_start = load_ddd_reservoir_incumbent_checkpoint(
                resume_checkpoint_path,
                problem=problem,
                network=network,
            )
            movement.apply_start(selected)
            _apply_semantic_passenger_start(passenger, passenger_start)
            seed_provenance = "validated_resume_checkpoint"
        elif import_checkpoint_path is not None:
            selected, semantic = import_ddd_reservoir_incumbent_checkpoint(
                import_checkpoint_path,
                problem=problem,
                network=network,
            )
            movement.apply_start(selected)
            _apply_semantic_passenger_start(passenger, semantic)
            seed_provenance = "validated_compatible_policy_checkpoint"
        self._publish(
            progress_hook,
            "primary_mip",
            started,
            problem,
            network,
            model,
            external_primary_upper=float(reference.metrics.unserved_passenger_count),
            passenger_variable_count=passenger.variable_count,
        )
        model.setObjective(passenger.total_unserved_expression, GRB.MINIMIZE)
        primary_started = perf_counter()
        callback = self._callback(
            progress_hook=progress_hook,
            phase="primary_mip",
            started=started,
            deadline=deadline,
            problem=problem,
            network=network,
            model=model,
            external_primary_upper=float(reference.metrics.unserved_passenger_count),
            passenger_variable_count=passenger.variable_count,
        )
        model.optimize(callback)
        primary_solve_seconds = perf_counter() - primary_started
        primary_solver_status_code = int(model.Status)
        primary_solver_status = _solver_status_name(model.Status)
        primary_bound = max(0.0, float(model.ObjBound))
        primary_upper = float(reference.metrics.unserved_passenger_count)
        if model.SolCount > 0:
            primary_upper = min(primary_upper, float(model.ObjVal))
        if primary_bound > primary_upper + 1e-5:
            return self._certificate_error(
                problem,
                network,
                reference,
                started,
                network_build_seconds,
                model_build_seconds,
                primary_solve_seconds,
                "primary lower bound exceeds the validated upper bound",
            )
        secondary_lower = None
        secondary_upper = None
        secondary_seconds = 0.0
        secondary_solver_status_code = None
        secondary_solver_status = None
        primary_optimal = model.Status == GRB.OPTIMAL
        if primary_optimal and perf_counter() < deadline:
            primary_value = int(round(model.ObjVal))
            model.addConstr(
                passenger.total_unserved_expression == primary_value,
                name="reservoir_primary_optimum",
            )
            for variable in model.getVars():
                variable.Start = variable.X
            model.setObjective(passenger.journey_time_expression(problem), GRB.MINIMIZE)
            model.Params.TimeLimit = max(0.001, deadline - perf_counter())
            self._publish(
                progress_hook,
                "secondary_mip",
                started,
                problem,
                network,
                model,
                primary_bounds=(float(primary_value), float(primary_value)),
                passenger_variable_count=passenger.variable_count,
            )
            secondary_started = perf_counter()
            model.optimize(
                self._callback(
                    progress_hook=progress_hook,
                    phase="secondary_mip",
                    started=started,
                    deadline=deadline,
                    problem=problem,
                    network=network,
                    model=model,
                    fixed_primary=float(primary_value),
                    passenger_variable_count=passenger.variable_count,
                )
            )
            secondary_seconds = perf_counter() - secondary_started
            secondary_solver_status_code = int(model.Status)
            secondary_solver_status = _solver_status_name(model.Status)
            secondary_lower = float(model.ObjBound)
            if model.SolCount > 0:
                secondary_upper = float(model.ObjVal)
        validation_started = perf_counter()
        paths: tuple[DddAnonymousReservoirPath, ...] = reference.paths
        metrics = reference.metrics
        dispatched = len(reference.paths)
        use_solver_incumbent = (
            model.SolCount > 0
            and (
                primary_optimal
                or float(model.ObjVal)
                <= reference.metrics.unserved_passenger_count + 1e-5
            )
        )
        if use_solver_incumbent:
            selected = movement.selected_arc_ids()
            try:
                validate_ddd_anonymous_reservoir_selection(problem, network, selected)
                paths = decompose_ddd_anonymous_reservoir_paths(network, selected)
                dispatched = len(paths)
                metrics = _extract_passenger_metrics(problem, passenger)
                _validate_passenger_metrics(problem, passenger, movement, metrics)
                if self.config.checkpoint_path is not None:
                    write_ddd_reservoir_incumbent_checkpoint(
                        self.config.checkpoint_path,
                        problem=problem,
                        network=network,
                        selected_arc_ids=selected,
                        passenger_model=passenger,
                        metrics=metrics,
                        provenance="independently_validated_solver_incumbent",
                    )
            except (ValueError, RuntimeError) as error:
                return self._validation_error(
                    problem,
                    network,
                    reference,
                    started,
                    network_build_seconds,
                    model_build_seconds,
                    primary_solve_seconds,
                    secondary_seconds,
                    str(error),
                )
        validation_seconds = perf_counter() - validation_started
        secondary_optimal = (
            secondary_lower is not None
            and secondary_upper is not None
            and abs(secondary_upper - secondary_lower) <= 1e-5
        )
        if primary_optimal and secondary_optimal:
            status = DddReservoirArcFlowStatus.INTEGER_OPTIMAL
        elif primary_optimal:
            status = DddReservoirArcFlowStatus.PRIMARY_OPTIMAL_SECONDARY_OPEN
        elif model.SolCount > 0 or reference.validated:
            status = DddReservoirArcFlowStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL
        elif model.Status == GRB.INFEASIBLE:
            status = DddReservoirArcFlowStatus.MOVEMENT_INFEASIBLE
        else:
            status = DddReservoirArcFlowStatus.UNKNOWN_NO_FEASIBLE_SEED
        if metrics is not None:
            primary_upper = min(primary_upper, float(metrics.unserved_passenger_count))
        total = perf_counter() - started
        served_lower = problem.total_demand - primary_upper
        served_upper = problem.total_demand - primary_bound
        return DddReservoirArcFlowResult(
            status=status,
            problem_fingerprint=problem.fingerprint,
            network_fingerprint=network.fingerprint,
            primary_lower_bound=primary_bound,
            primary_upper_bound=primary_upper,
            served_lower_bound=served_lower,
            served_upper_bound=served_upper,
            primary_absolute_gap=max(0.0, primary_upper - primary_bound),
            secondary_lower_bound=secondary_lower,
            secondary_upper_bound=secondary_upper,
            dispatched_fleet_count=dispatched,
            peak_active_fleet_count=dispatched,
            paths=paths,
            passenger_metrics=metrics,
            all_stop_reference_unserved=reference.metrics.unserved_passenger_count,
            all_stop_reference_journey_time=(reference.metrics.journey_time_passenger_seconds),
            all_stop_seed_accepted=True,
            seed_provenance=seed_provenance,
            network_node_count=len(network.nodes),
            network_arc_count=len(network.arcs),
            movement_variable_count=len(movement.route_by_arc_id),
            passenger_variable_count=passenger.variable_count,
            movement_constraint_count=movement.movement_constraint_count,
            passenger_constraint_count=passenger.constraint_count,
            resource_row_count=movement.resource_row_count,
            linear_constraint_count=model.NumConstrs,
            solver_node_count=float(model.NodeCount),
            solver_solution_count=int(model.SolCount),
            network_build_seconds=network_build_seconds,
            model_build_seconds=model_build_seconds,
            primary_solve_seconds=primary_solve_seconds,
            secondary_solve_seconds=secondary_seconds,
            validation_seconds=validation_seconds,
            total_seconds=total,
            peak_rss_gb=_peak_rss_gb(),
            detail=(
                None
                if primary_optimal and secondary_optimal
                else f"primary={primary_solver_status}; "
                f"secondary={secondary_solver_status or 'not_started'}"
            ),
            primary_solver_status_code=primary_solver_status_code,
            primary_solver_status=primary_solver_status,
            secondary_solver_status_code=secondary_solver_status_code,
            secondary_solver_status=secondary_solver_status,
        )

    def _callback(
        self,
        *,
        progress_hook: DddReservoirProgressHook | None,
        phase: str,
        started: float,
        deadline: float,
        problem: DddReservoirArcFlowProblem,
        network: DddAnonymousReservoirNetwork,
        model: gp.Model,
        external_primary_upper: float | None = None,
        fixed_primary: float | None = None,
        passenger_variable_count: int = 0,
    ):
        last = [0.0]

        def callback(callback_model: gp.Model, where: int) -> None:
            if where != GRB.Callback.MIP:
                return
            elapsed = perf_counter() - started
            if elapsed - last[0] < self.config.progress_interval_seconds:
                return
            last[0] = elapsed
            incumbent = float(callback_model.cbGet(GRB.Callback.MIP_OBJBST))
            bound = float(callback_model.cbGet(GRB.Callback.MIP_OBJBND))
            solutions = int(callback_model.cbGet(GRB.Callback.MIP_SOLCNT))
            nodes = float(callback_model.cbGet(GRB.Callback.MIP_NODCNT))
            if incumbent >= GRB.INFINITY / 2:
                incumbent = math.inf
            if phase == "primary_mip":
                lower = max(0.0, bound)
                upper = external_primary_upper
                if math.isfinite(incumbent):
                    upper = incumbent if upper is None else min(upper, incumbent)
                primary_bounds = (lower, upper)
                secondary_bounds = (None, None)
            else:
                primary_bounds = (fixed_primary, fixed_primary)
                secondary_bounds = (
                    bound if math.isfinite(bound) else None,
                    incumbent if math.isfinite(incumbent) else None,
                )
            self._publish(
                progress_hook,
                phase,
                started,
                problem,
                network,
                model,
                primary_bounds=primary_bounds,
                secondary_bounds=secondary_bounds,
                solver_nodes=nodes,
                solver_solutions=solutions,
                passenger_variable_count=passenger_variable_count,
            )

        return callback

    def _publish(
        self,
        hook: DddReservoirProgressHook | None,
        phase: str,
        started: float,
        problem: DddReservoirArcFlowProblem,
        network: DddAnonymousReservoirNetwork | None,
        model: gp.Model | None,
        *,
        external_primary_upper: float | None = None,
        primary_bounds: tuple[float | None, float | None] | None = None,
        secondary_bounds: tuple[float | None, float | None] = (None, None),
        solver_nodes: float = 0.0,
        solver_solutions: int = 0,
        passenger_variable_count: int = 0,
    ) -> None:
        if hook is None:
            return
        elapsed = perf_counter() - started
        lower, upper = primary_bounds or (0.0, external_primary_upper)
        hook(
            DddReservoirArcFlowProgress(
                phase=phase,
                elapsed_seconds=elapsed,
                remaining_seconds=max(0.0, self.config.total_time_limit_seconds - elapsed),
                primary_lower_bound=lower,
                primary_upper_bound=upper,
                served_lower_bound=(None if upper is None else problem.total_demand - upper),
                served_upper_bound=(None if lower is None else problem.total_demand - lower),
                secondary_lower_bound=secondary_bounds[0],
                secondary_upper_bound=secondary_bounds[1],
                dispatched_fleet_count=None,
                node_count=solver_nodes,
                solution_count=solver_solutions,
                movement_variable_count=0 if network is None else len(network.arcs),
                passenger_variable_count=passenger_variable_count,
                linear_constraint_count=0 if model is None else model.NumConstrs,
                resource_row_count=0 if network is None else len(network.resource_cliques),
                network_node_count=0 if network is None else len(network.nodes),
                network_arc_count=0 if network is None else len(network.arcs),
                peak_rss_gb=_peak_rss_gb(),
            )
        )

    def _empty_result(
        self,
        problem: DddReservoirArcFlowProblem,
        started: float,
        status: DddReservoirArcFlowStatus,
        detail: str,
        *,
        network: DddAnonymousReservoirNetwork | None = None,
        network_build_seconds: float = 0.0,
    ) -> DddReservoirArcFlowResult:
        return DddReservoirArcFlowResult(
            status=status,
            problem_fingerprint=problem.fingerprint,
            network_fingerprint=None if network is None else network.fingerprint,
            primary_lower_bound=0.0,
            primary_upper_bound=None,
            served_lower_bound=None,
            served_upper_bound=float(problem.total_demand),
            primary_absolute_gap=None,
            secondary_lower_bound=None,
            secondary_upper_bound=None,
            dispatched_fleet_count=None,
            peak_active_fleet_count=None,
            paths=(),
            passenger_metrics=None,
            all_stop_reference_unserved=None,
            all_stop_reference_journey_time=None,
            all_stop_seed_accepted=False,
            seed_provenance=None,
            network_node_count=0 if network is None else len(network.nodes),
            network_arc_count=0 if network is None else len(network.arcs),
            movement_variable_count=0,
            passenger_variable_count=0,
            movement_constraint_count=0,
            passenger_constraint_count=0,
            resource_row_count=0 if network is None else len(network.resource_cliques),
            linear_constraint_count=0,
            solver_node_count=0.0,
            solver_solution_count=0,
            network_build_seconds=network_build_seconds,
            model_build_seconds=0.0,
            primary_solve_seconds=0.0,
            secondary_solve_seconds=0.0,
            validation_seconds=0.0,
            total_seconds=perf_counter() - started,
            peak_rss_gb=_peak_rss_gb(),
            detail=detail,
        )

    def _certificate_error(self, problem, network, reference, started, network_seconds, model_seconds, primary_seconds, detail):
        result = self._empty_result(problem, started, DddReservoirArcFlowStatus.INTERNAL_CERTIFICATE_ERROR, detail, network=network, network_build_seconds=network_seconds)
        return DddReservoirArcFlowResult(**{**asdict(result), "status": DddReservoirArcFlowStatus.INTERNAL_CERTIFICATE_ERROR, "model_build_seconds": model_seconds, "primary_solve_seconds": primary_seconds, "all_stop_reference_unserved": reference.metrics.unserved_passenger_count, "all_stop_reference_journey_time": reference.metrics.journey_time_passenger_seconds})

    def _validation_error(self, problem, network, reference, started, network_seconds, model_seconds, primary_seconds, secondary_seconds, detail):
        result = self._certificate_error(problem, network, reference, started, network_seconds, model_seconds, primary_seconds, detail)
        return DddReservoirArcFlowResult(**{**asdict(result), "status": DddReservoirArcFlowStatus.INTERNAL_VALIDATION_ERROR, "secondary_solve_seconds": secondary_seconds})


def _configure_model(
    model: gp.Model,
    config: DddReservoirArcFlowSolveConfig,
    remaining_seconds: float,
) -> None:
    model.Params.OutputFlag = int(config.output_flag)
    model.Params.Threads = config.threads
    model.Params.Seed = config.seed
    model.Params.MIPFocus = config.mip_focus
    model.Params.MIPGap = config.mip_gap
    model.Params.TimeLimit = max(0.001, remaining_seconds)
    model.Params.NodefileStart = config.nodefile_start_gb
    model.Params.SoftMemLimit = config.soft_memory_limit_gb
    if config.nodefile_dir is not None:
        config.nodefile_dir.mkdir(parents=True, exist_ok=True)
        model.Params.NodefileDir = str(config.nodefile_dir)


def _peak_rss_gb() -> float:
    import resource
    import sys

    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # Darwin reports bytes; Linux reports kibibytes.
    divisor = 1024.0**3 if sys.platform == "darwin" else 1024.0**2
    return value / divisor


def _apply_reference_passenger_start(
    passenger: DddReservoirPassengerModel,
    reference: DddReservoirAllStopReference,
) -> None:
    for variable in (
        *passenger.onboard_by_group_arc.values(),
        *passenger.board_by_group_arc.values(),
        *passenger.alight_by_group_arc.values(),
    ):
        variable.Start = 0.0
    for group_id, variable in passenger.unserved_by_group.items():
        variable.Start = dict(reference.unserved_values).get(group_id, variable.UB)
    for values, variables in (
        (reference.onboard_values, passenger.onboard_by_group_arc),
        (reference.board_values, passenger.board_by_group_arc),
        (reference.alight_values, passenger.alight_by_group_arc),
    ):
        for group_id, arc_id, value in values:
            variable = variables.get((group_id, arc_id))
            if variable is None:
                raise ValueError("all-stop Passenger seed is outside full domain")
            variable.Start = value


def _apply_semantic_passenger_start(
    passenger: DddReservoirPassengerModel,
    values: Mapping[str, object],
) -> None:
    for variable in (
        *passenger.onboard_by_group_arc.values(),
        *passenger.board_by_group_arc.values(),
        *passenger.alight_by_group_arc.values(),
    ):
        variable.Start = 0.0
    for name, variables in (
        ("onboard", passenger.onboard_by_group_arc),
        ("board", passenger.board_by_group_arc),
        ("alight", passenger.alight_by_group_arc),
    ):
        for group_id, arc_id, value in values.get(name, ()):
            variable = variables.get((str(group_id), str(arc_id)))
            if variable is not None:
                variable.Start = float(value)
    unserved = dict(values.get("unserved", ()))
    for group_id, variable in passenger.unserved_by_group.items():
        variable.Start = float(unserved.get(group_id, variable.UB))


def _select_all_stop_reference_arcs(
    problem: DddReservoirArcFlowProblem,
    network: DddAnonymousReservoirNetwork,
) -> tuple[str, ...]:
    outgoing: dict[str, list[DddAnonymousReservoirArc]] = defaultdict(list)
    for arc in network.arcs:
        if arc.source_node_id is not None:
            outgoing[arc.source_node_id].append(arc)
    option_by_id = {option.id: option for option in problem.movement_core.route_options}
    selected: set[str] = set()
    for dispatch_tick in network.all_stop_seed_dispatch_ticks:
        dispatch_id = f"dispatch::t{dispatch_tick}"
        dispatch = network.arc_by_id.get(dispatch_id)
        if dispatch is None or dispatch.target_node_id is None:
            raise ValueError("all-stop dispatch anchor has no complete path")
        selected.add(dispatch.id)
        node_id = dispatch.target_node_id
        while True:
            choices = outgoing.get(node_id, ())
            recovery = tuple(arc for arc in choices if arc.is_recovery)
            if recovery:
                selected.add(recovery[0].id)
                break
            movement = tuple(arc for arc in choices if arc.is_movement)
            stop = tuple(
                arc
                for arc in movement
                if arc.wait_tick == 0
                and option_by_id[arc.option_id].decision is DddRouteDecision.STOP
            )
            candidates = stop or tuple(
                arc
                for arc in movement
                if arc.wait_tick == 0
                and option_by_id[arc.option_id].decision is DddRouteDecision.SKIP
            )
            if len(candidates) != 1 or candidates[0].target_node_id is None:
                raise ValueError("all-stop reference path is not deterministic")
            selected.add(candidates[0].id)
            node_id = candidates[0].target_node_id
    return tuple(sorted(selected))


def decompose_ddd_anonymous_reservoir_paths(
    network: DddAnonymousReservoirNetwork,
    selected_arc_ids: tuple[str, ...],
) -> tuple[DddAnonymousReservoirPath, ...]:
    selected = set(selected_arc_ids)
    outgoing: dict[str, list[DddAnonymousReservoirArc]] = defaultdict(list)
    for arc in network.arcs:
        if arc.id in selected and arc.source_node_id is not None:
            outgoing[arc.source_node_id].append(arc)
    paths = []
    consumed: set[str] = set()
    dispatches = sorted(
        (arc for arc in network.dispatch_arcs if arc.id in selected),
        key=lambda arc: (arc.source_tick, arc.id),
    )
    for cabin_id, dispatch in enumerate(dispatches):
        consumed.add(dispatch.id)
        node_id = dispatch.target_node_id
        movement_ids = []
        recovery_id = None
        while node_id is not None:
            choices = outgoing.get(node_id, ())
            if len(choices) != 1:
                raise RuntimeError("integral reservoir flow does not decompose uniquely")
            arc = choices[0]
            consumed.add(arc.id)
            if arc.is_recovery:
                recovery_id = arc.id
                break
            movement_ids.append(arc.id)
            node_id = arc.target_node_id
        if recovery_id is None:
            raise RuntimeError("reservoir path has no recovery arc")
        paths.append(
            DddAnonymousReservoirPath(
                cabin_id=cabin_id,
                dispatch_arc_id=dispatch.id,
                movement_arc_ids=tuple(movement_ids),
                recovery_arc_id=recovery_id,
            )
        )
    if consumed != selected:
        raise RuntimeError("reservoir selection contains disconnected flow")
    return tuple(paths)


def validate_ddd_anonymous_reservoir_selection(
    problem: DddReservoirArcFlowProblem,
    network: DddAnonymousReservoirNetwork,
    selected_arc_ids: tuple[str, ...],
) -> None:
    selected = set(selected_arc_ids)
    if selected - set(network.arc_by_id):
        raise ValueError("reservoir selection references unknown arcs")
    paths = decompose_ddd_anonymous_reservoir_paths(network, selected_arc_ids)
    if len(paths) > problem.available_fleet_count:
        raise ValueError("reservoir selection exceeds the available fleet")
    if any(
        sum(coefficient for arc_id, coefficient in clique.coefficients if arc_id in selected) > 1
        for clique in network.resource_cliques
    ):
        raise ValueError("reservoir selection violates a resource clique")
    for path in paths:
        dispatch = network.arc_by_id[path.dispatch_arc_id]
        recovery = network.arc_by_id[path.recovery_arc_id]
        if dispatch.source_tick >= problem.warmup_tick:
            raise ValueError("reservoir path dispatches outside warm-up")
        if recovery.source_tick < problem.service_end_tick:
            raise ValueError("reservoir path recovers during Passenger service")


def _extract_passenger_metrics(
    problem: DddReservoirArcFlowProblem,
    passenger: DddReservoirPassengerModel,
) -> DddReservoirPassengerMetrics:
    unserved = int(round(sum(variable.X for variable in passenger.unserved_by_group.values())))
    journey = float(passenger.journey_time_expression(problem).getValue())
    return DddReservoirPassengerMetrics(
        total_demand=problem.total_demand,
        served_passenger_count=problem.total_demand - unserved,
        unserved_passenger_count=unserved,
        journey_time_passenger_seconds=journey,
    )


def _validate_passenger_metrics(
    problem: DddReservoirArcFlowProblem,
    passenger: DddReservoirPassengerModel,
    movement: _DddReservoirMovementMaster,
    metrics: DddReservoirPassengerMetrics,
) -> None:
    if not 0 <= metrics.unserved_passenger_count <= problem.total_demand:
        raise ValueError("reservoir Passenger unserved count is invalid")
    for group in problem.demand_groups:
        boarded = sum(
            variable.X
            for (group_id, _), variable in passenger.board_by_group_arc.items()
            if group_id == group.id
        )
        alighted = sum(
            variable.X
            for (group_id, _), variable in passenger.alight_by_group_arc.items()
            if group_id == group.id
        )
        unserved = passenger.unserved_by_group[group.id].X
        if abs(boarded + unserved - group.count) > 1e-5 or abs(boarded - alighted) > 1e-5:
            raise ValueError("reservoir Passenger balance validation failed")
    load_by_arc: dict[str, float] = defaultdict(float)
    for (_, arc_id), variable in passenger.onboard_by_group_arc.items():
        load_by_arc[arc_id] += variable.X
    for arc_id, load in load_by_arc.items():
        active = movement.route_by_arc_id[arc_id].X
        if load > problem.cabin_capacity * active + 1e-5:
            raise ValueError("reservoir Passenger capacity validation failed")


def write_ddd_reservoir_incumbent_checkpoint(
    path: Path,
    *,
    problem: DddReservoirArcFlowProblem,
    network: DddAnonymousReservoirNetwork,
    selected_arc_ids: tuple[str, ...],
    passenger_model: DddReservoirPassengerModel,
    metrics: DddReservoirPassengerMetrics,
    provenance: str,
) -> None:
    from os import fdopen, fsync, replace
    import tempfile

    validate_ddd_anonymous_reservoir_selection(problem, network, selected_arc_ids)
    actual_metrics = _extract_passenger_metrics(problem, passenger_model)
    if actual_metrics != metrics:
        raise ValueError("reservoir checkpoint metrics are not the current solution")
    selected = set(selected_arc_ids)
    load_by_arc: dict[str, float] = defaultdict(float)
    for (_, arc_id), variable in passenger_model.onboard_by_group_arc.items():
        load_by_arc[arc_id] += variable.X
    if any(
        load > problem.cabin_capacity * float(arc_id in selected) + 1e-5
        for arc_id, load in load_by_arc.items()
    ):
        raise ValueError("reservoir checkpoint Passenger load violates movement")
    payload = {
        "schema_version": 1,
        "problem_fingerprint": problem.fingerprint,
        "network_fingerprint": network.fingerprint,
        "scenario_id": problem.movement_core.scenario_id,
        "available_fleet_count": problem.available_fleet_count,
        "entry_state_id": problem.entry_state_id,
        "warmup_seconds": problem.warmup_seconds,
        "service_seconds": problem.service_seconds,
        "recovery_seconds": problem.recovery_seconds,
        "selected_arc_ids": list(selected_arc_ids),
        "passenger_values": {
            variable.VarName: variable.X
            for variable in (
                *passenger_model.onboard_by_group_arc.values(),
                *passenger_model.board_by_group_arc.values(),
                *passenger_model.alight_by_group_arc.values(),
                *passenger_model.unserved_by_group.values(),
            )
        },
        "semantic_passenger_values": {
            "onboard": [
                [group_id, arc_id, variable.X]
                for (group_id, arc_id), variable in passenger_model.onboard_by_group_arc.items()
                if variable.X > 1e-9
            ],
            "board": [
                [group_id, arc_id, variable.X]
                for (group_id, arc_id), variable in passenger_model.board_by_group_arc.items()
                if variable.X > 1e-9
            ],
            "alight": [
                [group_id, arc_id, variable.X]
                for (group_id, arc_id), variable in passenger_model.alight_by_group_arc.items()
                if variable.X > 1e-9
            ],
            "unserved": [
                [group_id, variable.X]
                for group_id, variable in passenger_model.unserved_by_group.items()
            ],
        },
        "metrics": asdict(metrics),
        "provenance": provenance,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            fsync(stream.fileno())
        replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def load_ddd_reservoir_incumbent_checkpoint(
    path: Path,
    *,
    problem: DddReservoirArcFlowProblem,
    network: DddAnonymousReservoirNetwork,
) -> tuple[tuple[str, ...], dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("problem_fingerprint") != problem.fingerprint:
        raise ValueError("reservoir checkpoint problem fingerprint differs")
    if payload.get("network_fingerprint") != network.fingerprint:
        raise ValueError("reservoir checkpoint network fingerprint differs")
    selected = tuple(sorted(str(item) for item in payload["selected_arc_ids"]))
    validate_ddd_anonymous_reservoir_selection(problem, network, selected)
    passenger_values = dict(payload.get("semantic_passenger_values", {}))
    if not passenger_values:
        raise ValueError("reservoir checkpoint has no semantic Passenger values")
    return selected, passenger_values


def write_ddd_reservoir_reference_checkpoint(
    path: Path,
    *,
    problem: DddReservoirArcFlowProblem,
    network: DddAnonymousReservoirNetwork,
    reference: DddReservoirAllStopReference,
) -> None:
    import os
    import tempfile

    validate_ddd_anonymous_reservoir_selection(
        problem, network, reference.selected_arc_ids
    )
    payload = {
        "schema_version": 1,
        "problem_fingerprint": problem.fingerprint,
        "network_fingerprint": network.fingerprint,
        "scenario_id": problem.movement_core.scenario_id,
        "available_fleet_count": problem.available_fleet_count,
        "entry_state_id": problem.entry_state_id,
        "warmup_seconds": problem.warmup_seconds,
        "service_seconds": problem.service_seconds,
        "recovery_seconds": problem.recovery_seconds,
        "selected_arc_ids": list(reference.selected_arc_ids),
        "semantic_passenger_values": {
            "onboard": [list(value) for value in reference.onboard_values if value[2] > 1e-9],
            "board": [list(value) for value in reference.board_values if value[2] > 1e-9],
            "alight": [list(value) for value in reference.alight_values if value[2] > 1e-9],
            "unserved": [list(value) for value in reference.unserved_values],
        },
        "metrics": asdict(reference.metrics),
        "provenance": "independently_validated_all_stop_reference",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def import_ddd_reservoir_incumbent_checkpoint(
    path: Path,
    *,
    problem: DddReservoirArcFlowProblem,
    network: DddAnonymousReservoirNetwork,
) -> tuple[tuple[str, ...], dict[str, object]]:
    """Import a no-wait incumbent into a compatible richer waiting policy."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "scenario_id": problem.movement_core.scenario_id,
        "available_fleet_count": problem.available_fleet_count,
        "entry_state_id": problem.entry_state_id,
        "warmup_seconds": problem.warmup_seconds,
        "service_seconds": problem.service_seconds,
        "recovery_seconds": problem.recovery_seconds,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"reservoir imported checkpoint has incompatible {key}")
    selected = tuple(sorted(str(item) for item in payload["selected_arc_ids"]))
    validate_ddd_anonymous_reservoir_selection(problem, network, selected)
    semantic = dict(payload.get("semantic_passenger_values", {}))
    if not semantic:
        raise ValueError("reservoir imported checkpoint has no semantic Passenger seed")
    return selected, semantic


def _solver_status_name(status: int) -> str:
    """Keep native Gurobi termination separate from reservoir certificates."""
    for name in (
        "LOADED", "OPTIMAL", "INFEASIBLE", "INF_OR_UNBD", "UNBOUNDED",
        "CUTOFF", "ITERATION_LIMIT", "NODE_LIMIT", "TIME_LIMIT",
        "SOLUTION_LIMIT", "INTERRUPTED", "NUMERIC", "SUBOPTIMAL",
        "INPROGRESS", "USER_OBJ_LIMIT", "WORK_LIMIT", "MEM_LIMIT",
    ):
        if status == getattr(GRB, name, None):
            return name
    return f"STATUS_{status}"
