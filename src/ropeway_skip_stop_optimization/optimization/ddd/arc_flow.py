from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import math
from threading import Event, Lock, Thread
from time import perf_counter
from typing import Callable

import gurobipy as gp
from gurobipy import GRB

from .arc_flow_passenger_formulation import (
    DddArcFlowPassengerFormulationConfig, prepare_arc_flow_passengers,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_passenger_model import (
    DddArcFlowIntegratedPassengerModel,
    DddArcFlowPassengerModelBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_movement_master import (
    DddArcFlowMovementMasterBuilder,
    build_ddd_arc_flow_movement_values,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_network import (
    DddArcFlowBuildTimeLimitError,
    check_ddd_arc_flow_build_deadline,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import (
    DddArcFlowProblemPreparer,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_resource_separation import (
    DddArcFlowSelectedResourceCliqueSeparator,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKTrajectoryProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k_primal_seed import (
    DddFixedKPrimalSeed,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
    DddReferenceTrajectory,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanPassengerAssignmentDomain,
)


class DddArcFlowResourceRowMode(StrEnum):
    EAGER_MAXIMAL_CLIQUES = "eager_maximal_cliques"
    DELAYED_SELECTED_CLIQUES = "delayed_selected_cliques"


class DddFixedKArcFlowStatus(StrEnum):
    INTEGER_OPTIMAL = "integer_optimal"
    TIME_LIMIT_WITH_CERTIFIED_INTERVAL = "time_limit_with_certified_interval"
    MOVEMENT_INFEASIBLE = "movement_infeasible"
    UNKNOWN_NO_INCUMBENT = "unknown_no_incumbent"
    INTERNAL_VALIDATION_ERROR = "internal_validation_error"
    INTERNAL_CERTIFICATE_ERROR = "internal_certificate_error"


@dataclass(frozen=True, slots=True)
class DddFixedKArcFlowSolveConfig:
    time_limit_seconds: float = 600.0
    mip_gap: float = 0.0
    threads: int | None = None
    seed: int = 0
    mip_focus: int = 0
    output_flag: bool = False
    resource_row_mode: DddArcFlowResourceRowMode = (
        DddArcFlowResourceRowMode.EAGER_MAXIMAL_CLIQUES
    )
    certificate_tolerance: float = 1e-5
    progress_interval_seconds: float = 5.0
    passenger_formulation: DddArcFlowPassengerFormulationConfig = DddArcFlowPassengerFormulationConfig()
    require_full_service: bool = False

    def validate(self) -> None:
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("arc-flow time limit must be positive and finite")
        if not math.isfinite(self.mip_gap) or not 0 <= self.mip_gap <= 1:
            raise ValueError("arc-flow MIP gap must lie in [0, 1]")
        if self.threads is not None and self.threads <= 0:
            raise ValueError("arc-flow threads must be positive")
        if self.seed < 0 or self.mip_focus not in range(4):
            raise ValueError("arc-flow solver controls are invalid")
        if not isinstance(self.resource_row_mode, DddArcFlowResourceRowMode):
            raise ValueError("arc-flow resource-row mode is invalid")
        if self.certificate_tolerance <= 0:
            raise ValueError("arc-flow certificate tolerance must be positive")
        if type(self.require_full_service) is not bool:
            raise ValueError("require_full_service must be boolean")
        if (
            not math.isfinite(self.progress_interval_seconds)
            or self.progress_interval_seconds <= 0
        ):
            raise ValueError("arc-flow progress interval must be positive and finite")


@dataclass(frozen=True, slots=True)
class DddFixedKArcFlowProgress:
    elapsed_seconds: float
    node_count: float
    solver_incumbent: float | None
    solver_bound: float | None
    certified_lower_bound: float
    solver_gap: float | None
    solution_count: int
    movement_variable_count: int
    passenger_variable_count: int
    movement_constraint_count: int
    passenger_constraint_count: int
    resource_row_count: int
    linear_constraint_count: int
    remaining_seconds: float
    phase: str = "mip_solve"
    simplex_iteration_count: float | None = None
    barrier_iteration_count: int | None = None
    presolved_removed_row_count: int | None = None
    presolved_removed_column_count: int | None = None


@dataclass(frozen=True, slots=True)
class DddFixedKArcFlowResult:
    status: DddFixedKArcFlowStatus
    problem_fingerprint: str
    objective_value: float | None
    solver_best_bound: float | None
    root_cg_lower_bound: float | None
    certified_lower_bound: float
    validated_upper_bound: float | None
    relative_gap: float | None
    solution: DddReferenceSolution | None
    solver_status: int
    solution_count: int
    node_count: float
    movement_variable_count: int
    passenger_variable_count: int
    movement_constraint_count: int
    passenger_constraint_count: int
    resource_row_count: int
    linear_constraint_count: int
    network_build_seconds: float
    model_build_seconds: float
    solve_seconds: float
    total_seconds: float
    time_to_first_incumbent_seconds: float | None
    seed_kind: str | None = None
    primal_seed_objective_value: float | None = None
    detail: str | None = None
    passenger_profile: str = "legacy"
    model_fingerprint: str | None = None
    passenger_audit_json: str | None = None
    passenger_domain_build_seconds: float = 0.0
    integer_variable_count: int | None = None
    binary_variable_count: int | None = None
    nonzero_count: int | None = None


DddFixedKArcFlowProgressHook = Callable[[DddFixedKArcFlowProgress], None]


class DddArcFlowProgressHeartbeat:
    """Publish the latest safe snapshot even while Gurobi stays in one phase."""

    def __init__(
        self,
        *,
        hook: DddFixedKArcFlowProgressHook | None,
        initial: DddFixedKArcFlowProgress,
        time_limit_seconds: float,
        interval_seconds: float = 5.0,
    ) -> None:
        self._hook = hook
        self._current = initial
        self._time_limit_seconds = time_limit_seconds
        self._interval_seconds = interval_seconds
        self._started = perf_counter()
        self._state_lock = Lock()
        self._publish_lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._hook is None:
            return
        self._publish()
        self._thread = Thread(
            target=self._run,
            name="ddd-arc-flow-progress",
            daemon=True,
        )
        self._thread.start()

    def update(self, progress: DddFixedKArcFlowProgress) -> None:
        with self._state_lock:
            self._current = progress

    def stop(self) -> None:
        if self._hook is None:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._interval_seconds + 1.0))
        self._publish()

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            self._publish()

    def _publish(self) -> None:
        if self._hook is None:
            return
        elapsed = perf_counter() - self._started
        with self._state_lock:
            current = self._current
        snapshot = replace(
            current,
            elapsed_seconds=elapsed,
            remaining_seconds=max(0.0, self._time_limit_seconds - elapsed),
        )
        with self._publish_lock:
            self._hook(snapshot)


@dataclass(slots=True)
class DddFixedKArcFlowOptimizer:
    config: DddFixedKArcFlowSolveConfig = DddFixedKArcFlowSolveConfig()

    def solve(
        self,
        problem: DddFixedKTrajectoryProblem,
        *,
        seed_trajectories: tuple[DddReferenceTrajectory, ...] = (),
        primal_seed: DddFixedKPrimalSeed | None = None,
        seed_kind: str | None = None,
        root_cg_lower_bound: float | None = None,
        progress_hook: DddFixedKArcFlowProgressHook | None = None,
        incumbent_hook: Callable | None = None,
    ) -> DddFixedKArcFlowResult:
        self.config.validate()
        problem.validate()
        if primal_seed is not None:
            primal_seed.validate(problem)
            seed_trajectories = primal_seed.solution.trajectories
            seed_kind = primal_seed.provenance
        initial_lower_bound = max(
            problem.objective_floor,
            (
                problem.objective_floor
                if root_cg_lower_bound is None
                else root_cg_lower_bound
            ),
        )
        heartbeat = DddArcFlowProgressHeartbeat(
            hook=progress_hook,
            initial=DddFixedKArcFlowProgress(
                elapsed_seconds=0.0,
                node_count=0.0,
                solver_incumbent=(
                    None if primal_seed is None else primal_seed.objective_value
                ),
                solver_bound=None,
                certified_lower_bound=initial_lower_bound,
                solver_gap=None,
                solution_count=0,
                movement_variable_count=0,
                passenger_variable_count=0,
                movement_constraint_count=0,
                passenger_constraint_count=0,
                resource_row_count=0,
                linear_constraint_count=0,
                remaining_seconds=self.config.time_limit_seconds,
                phase="network_build",
            ),
            time_limit_seconds=self.config.time_limit_seconds,
            interval_seconds=self.config.progress_interval_seconds,
        )
        heartbeat.start()
        try:
            result = self._solve(
                problem,
                seed_trajectories=seed_trajectories,
                primal_seed=primal_seed,
                seed_kind=seed_kind,
                root_cg_lower_bound=root_cg_lower_bound,
                progress_hook=heartbeat.update,
                incumbent_hook=incumbent_hook,
            )
            heartbeat.update(
                DddFixedKArcFlowProgress(
                    elapsed_seconds=result.total_seconds,
                    node_count=result.node_count,
                    solver_incumbent=result.objective_value,
                    solver_bound=result.solver_best_bound,
                    certified_lower_bound=result.certified_lower_bound,
                    solver_gap=result.relative_gap,
                    solution_count=result.solution_count,
                    movement_variable_count=result.movement_variable_count,
                    passenger_variable_count=result.passenger_variable_count,
                    movement_constraint_count=result.movement_constraint_count,
                    passenger_constraint_count=result.passenger_constraint_count,
                    resource_row_count=result.resource_row_count,
                    linear_constraint_count=result.linear_constraint_count,
                    remaining_seconds=max(
                        0.0,
                        self.config.time_limit_seconds - result.total_seconds,
                    ),
                    phase="solve_complete",
                )
            )
            return replace(result, passenger_profile=self.config.passenger_formulation.profile)
        finally:
            heartbeat.stop()

    def _solve(
        self,
        problem: DddFixedKTrajectoryProblem,
        *,
        seed_trajectories: tuple[DddReferenceTrajectory, ...] = (),
        primal_seed: DddFixedKPrimalSeed | None = None,
        seed_kind: str | None = None,
        root_cg_lower_bound: float | None = None,
        progress_hook: DddFixedKArcFlowProgressHook | None = None,
        incumbent_hook: Callable | None = None,
    ) -> DddFixedKArcFlowResult:
        self.config.validate()
        problem.validate()
        started = perf_counter()
        external_upper_bound = (
            None if primal_seed is None else primal_seed.objective_value
        )
        movement_variable_count = 0
        passenger_variable_count = 0
        movement_constraint_count = 0
        passenger_constraint_count = 0
        resource_rows = 0

        def certified_bound(solver_bound: float | None = None) -> float:
            values = [problem.objective_floor]
            if root_cg_lower_bound is not None:
                values.append(root_cg_lower_bound)
            if solver_bound is not None:
                values.append(solver_bound)
            return max(values)

        def update_phase(phase: str) -> None:
            if progress_hook is None:
                return
            elapsed = perf_counter() - started
            progress_hook(
                DddFixedKArcFlowProgress(
                    elapsed_seconds=elapsed,
                    node_count=0.0,
                    solver_incumbent=external_upper_bound,
                    solver_bound=None,
                    certified_lower_bound=certified_bound(),
                    solver_gap=None,
                    solution_count=0,
                    movement_variable_count=movement_variable_count,
                    passenger_variable_count=passenger_variable_count,
                    movement_constraint_count=movement_constraint_count,
                    passenger_constraint_count=passenger_constraint_count,
                    resource_row_count=resource_rows,
                    linear_constraint_count=(
                        movement_constraint_count
                        + passenger_constraint_count
                        + resource_rows
                    ),
                    remaining_seconds=max(
                        0.0, self.config.time_limit_seconds - elapsed
                    ),
                    phase=phase,
                )
            )

        try:
            prepared = DddArcFlowProblemPreparer().build(
                problem,
                phase_hook=update_phase,
                build_labeled_resource_cliques=(
                    self.config.resource_row_mode
                    is DddArcFlowResourceRowMode.EAGER_MAXIMAL_CLIQUES
                ),
                deadline_monotonic=started + self.config.time_limit_seconds,
            )
        except DddArcFlowBuildTimeLimitError as error:
            total = perf_counter() - started
            return DddFixedKArcFlowResult(
                status=(
                    DddFixedKArcFlowStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL
                    if primal_seed is not None
                    else DddFixedKArcFlowStatus.UNKNOWN_NO_INCUMBENT
                ),
                problem_fingerprint=problem.fingerprint,
                objective_value=external_upper_bound,
                solver_best_bound=None,
                root_cg_lower_bound=root_cg_lower_bound,
                certified_lower_bound=certified_bound(),
                validated_upper_bound=external_upper_bound,
                relative_gap=_relative_gap(
                    certified_bound(), external_upper_bound
                ),
                solution=(None if primal_seed is None else primal_seed.solution),
                solver_status=int(GRB.TIME_LIMIT),
                solution_count=0,
                node_count=0.0,
                movement_variable_count=0,
                passenger_variable_count=0,
                movement_constraint_count=0,
                passenger_constraint_count=0,
                resource_row_count=0,
                linear_constraint_count=0,
                network_build_seconds=total,
                model_build_seconds=0.0,
                solve_seconds=0.0,
                total_seconds=total,
                time_to_first_incumbent_seconds=(
                    0.0 if primal_seed is not None else None
                ),
                seed_kind=(None if primal_seed is None else primal_seed.provenance),
                primal_seed_objective_value=external_upper_bound,
                detail=str(error),
            )
        movement_variable_count = len(prepared.arcs)
        network_build_seconds = prepared.network_build_seconds
        update_phase("model_variables")

        model_started = perf_counter()
        model = gp.Model("ddd_fixed_k_arc_flow")
        model.Params.OutputFlag = int(self.config.output_flag)
        model.Params.MIPGap = self.config.mip_gap
        model.Params.Seed = self.config.seed
        model.Params.MIPFocus = self.config.mip_focus
        if self.config.threads is not None:
            model.Params.Threads = self.config.threads
        model.ModelSense = GRB.MINIMIZE

        movement_master = DddArcFlowMovementMasterBuilder().build(
            model=model,
            prepared=prepared,
            add_eager_resource_rows=(
                self.config.resource_row_mode
                is DddArcFlowResourceRowMode.EAGER_MAXIMAL_CLIQUES
            ),
        )
        route = movement_master.route_by_arc_id
        movement_variable_count = movement_master.movement_variable_count
        movement_constraint_count = movement_master.movement_constraint_count
        update_phase("model_resource_rows")
        resource_rows = movement_master.resource_row_count
        update_phase("model_passengers")
        passenger_started = perf_counter()
        try:
            check_ddd_arc_flow_build_deadline(
                started + self.config.time_limit_seconds
            )
            passenger_encoding = prepare_arc_flow_passengers(
                prepared,
                self.config.passenger_formulation,
                deadline_monotonic=started + self.config.time_limit_seconds,
            )
            passenger_domain = passenger_encoding.source
            passenger_domain_build_seconds = perf_counter() - passenger_started
        except DddArcFlowBuildTimeLimitError as error:
            total = perf_counter() - started
            return DddFixedKArcFlowResult(
                status=(
                    DddFixedKArcFlowStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL
                    if primal_seed is not None
                    else DddFixedKArcFlowStatus.UNKNOWN_NO_INCUMBENT
                ),
                problem_fingerprint=problem.fingerprint,
                objective_value=external_upper_bound,
                solver_best_bound=None,
                root_cg_lower_bound=root_cg_lower_bound,
                certified_lower_bound=certified_bound(),
                validated_upper_bound=external_upper_bound,
                relative_gap=_relative_gap(
                    certified_bound(), external_upper_bound
                ),
                solution=(None if primal_seed is None else primal_seed.solution),
                solver_status=int(GRB.TIME_LIMIT),
                solution_count=0,
                node_count=0.0,
                movement_variable_count=movement_variable_count,
                passenger_variable_count=0,
                movement_constraint_count=movement_constraint_count,
                passenger_constraint_count=0,
                resource_row_count=resource_rows,
                linear_constraint_count=int(model.NumConstrs),
                network_build_seconds=network_build_seconds,
                model_build_seconds=perf_counter() - model_started,
                solve_seconds=0.0,
                total_seconds=total,
                time_to_first_incumbent_seconds=(
                    0.0 if primal_seed is not None else None
                ),
                seed_kind=(None if primal_seed is None else primal_seed.provenance),
                primal_seed_objective_value=external_upper_bound,
                detail=str(error),
            )
        passenger_model = DddArcFlowPassengerModelBuilder().build_integrated(
            model=model,
            domain=passenger_domain,
            route_by_arc_id=route,
            assignment_domain=EanPassengerAssignmentDomain.INTEGER,
            encoding=(passenger_encoding if self.config.passenger_formulation.profile != "legacy" else None),
            require_full_service=self.config.require_full_service,
        )
        passenger_variable_count = passenger_model.variable_count
        passenger_constraint_count = passenger_model.constraint_count
        movement_master.apply_seed(seed_trajectories)
        if primal_seed is not None:
            movement_values = build_ddd_arc_flow_movement_values(
                prepared,
                primal_seed.solution,
            )
            seeded_objective = passenger_model.apply_seed(
                ride_counts_by_candidate_id=(
                    primal_seed.ride_counts_by_candidate_id
                ),
                movement_values_by_arc_id=movement_values,
            )
            if not math.isclose(
                seeded_objective,
                primal_seed.objective_value,
                rel_tol=0.0,
                abs_tol=self.config.certificate_tolerance,
            ):
                raise ValueError(
                    "arc-flow Passenger MIP start objective differs from the "
                    "validated primal seed"
                )
            model.addConstr(
                model.getObjective()
                <= primal_seed.objective_value + self.config.certificate_tolerance,
                name="validated_primal_cutoff",
            )
        model.update()
        delayed_separator = (
            DddArcFlowSelectedResourceCliqueSeparator(prepared)
            if self.config.resource_row_mode
            is DddArcFlowResourceRowMode.DELAYED_SELECTED_CLIQUES
            else None
        )
        if delayed_separator is not None:
            model.Params.LazyConstraints = 1
        model_build_seconds = perf_counter() - model_started
        update_phase("presolve")

        first_incumbent: float | None = None
        last_sample_seconds = -math.inf
        latest_incumbent: float | None = external_upper_bound
        latest_bound: float | None = None
        latest_node_count = 0.0
        latest_solution_count = 0
        delayed_separation_error: str | None = None
        route_items = tuple(route.items())
        route_variables = tuple(variable for _, variable in route_items)
        last_emitted_objective = math.inf
        incumbent_hook_error = None

        def callback(callback_model: gp.Model, where: int) -> None:
            nonlocal first_incumbent, last_sample_seconds
            nonlocal latest_bound, latest_incumbent
            nonlocal latest_node_count, latest_solution_count
            nonlocal resource_rows, delayed_separation_error
            nonlocal last_emitted_objective, incumbent_hook_error
            if where == GRB.Callback.MIPSOL:
                if delayed_separator is not None:
                    selected_arc_ids = frozenset(
                        arc_id
                        for (arc_id, _), value in zip(
                            route_items,
                            callback_model.cbGetSolution(route_variables),
                            strict=True,
                        )
                        if value > 0.5
                    )
                    separation = delayed_separator.separate(selected_arc_ids)
                    if separation.duplicate_violation_count:
                        delayed_separation_error = (
                            "an integer candidate violates an already materialized "
                            "resource clique"
                        )
                        callback_model.terminate()
                        return
                    for clique in separation.new_violations:
                        callback_model.cbLazy(
                            gp.quicksum(
                                coefficient * route[arc_id]
                                for arc_id, coefficient in clique.coefficients
                            )
                            <= 1
                        )
                    if separation.new_violations:
                        delayed_separator.mark_materialized(
                            separation.new_violations
                        )
                        resource_rows = delayed_separator.materialized_row_count
                        return
                if first_incumbent is None:
                    first_incumbent = perf_counter() - started
                candidate_objective = callback_model.cbGet(GRB.Callback.MIPSOL_OBJ)
                if incumbent_hook is not None and candidate_objective < last_emitted_objective - self.config.certificate_tolerance:
                    try:
                        movement_values = dict(zip(route, callback_model.cbGetSolution(route_variables), strict=True))
                        raw = dict(zip(passenger_model.variable_by_id, callback_model.cbGetSolution(
                            list(passenger_model.variable_by_id.values())), strict=True))
                        canonical = passenger_model.canonical_values(raw, movement_values)
                        meta = passenger_domain.variable_by_id
                        counts = {f.candidate_id: sum(canonical[v] for _, v in f.variable_ids_by_arc_id
                                                     if meta[v].visit_index == f.board_visit_index)
                                  for f in passenger_domain.flows}
                        snapshot = movement_master.extract_solution(
                            values=movement_values,
                            boundary_occurrences=problem.boundary_context.resource_occurrences,
                        )
                        incumbent_hook(snapshot, counts, candidate_objective)
                        last_emitted_objective = candidate_objective
                    except Exception as error:
                        incumbent_hook_error = str(error)
                        callback_model.terminate()
                        return
            supported = {
                GRB.Callback.PRESOLVE,
                GRB.Callback.SIMPLEX,
                GRB.Callback.BARRIER,
                GRB.Callback.MIP,
                GRB.Callback.MIPNODE,
            }
            if progress_hook is None or where not in supported:
                return
            elapsed = perf_counter() - started
            if elapsed - last_sample_seconds < 1.0:
                return
            last_sample_seconds = elapsed
            phase = "presolve"
            simplex_iterations = None
            barrier_iterations = None
            removed_rows = None
            removed_columns = None
            if where == GRB.Callback.PRESOLVE:
                removed_rows = int(
                    callback_model.cbGet(GRB.Callback.PRE_ROWDEL)
                )
                removed_columns = int(
                    callback_model.cbGet(GRB.Callback.PRE_COLDEL)
                )
            elif where == GRB.Callback.SIMPLEX:
                phase = (
                    "root_simplex"
                    if latest_node_count <= 0
                    else "node_simplex"
                )
                simplex_iterations = float(
                    callback_model.cbGet(GRB.Callback.SPX_ITRCNT)
                )
            elif where == GRB.Callback.BARRIER:
                phase = (
                    "root_barrier"
                    if latest_node_count <= 0
                    else "node_barrier"
                )
                barrier_iterations = int(
                    callback_model.cbGet(GRB.Callback.BARRIER_ITRCNT)
                )
            elif where == GRB.Callback.MIP:
                phase = "branch_and_bound"
                latest_incumbent = _finite_solver_value(
                    float(callback_model.cbGet(GRB.Callback.MIP_OBJBST))
                )
                latest_incumbent = _minimum_optional(
                    latest_incumbent,
                    external_upper_bound,
                )
                latest_bound = _finite_solver_value(
                    float(callback_model.cbGet(GRB.Callback.MIP_OBJBND))
                )
                latest_node_count = float(
                    callback_model.cbGet(GRB.Callback.MIP_NODCNT)
                )
                latest_solution_count = int(
                    callback_model.cbGet(GRB.Callback.MIP_SOLCNT)
                )
            else:
                phase = (
                    "root_node"
                    if float(callback_model.cbGet(GRB.Callback.MIPNODE_NODCNT))
                    <= 0
                    else "branch_and_bound"
                )
                latest_incumbent = _finite_solver_value(
                    float(callback_model.cbGet(GRB.Callback.MIPNODE_OBJBST))
                )
                latest_incumbent = _minimum_optional(
                    latest_incumbent,
                    external_upper_bound,
                )
                latest_bound = _finite_solver_value(
                    float(callback_model.cbGet(GRB.Callback.MIPNODE_OBJBND))
                )
                latest_node_count = float(
                    callback_model.cbGet(GRB.Callback.MIPNODE_NODCNT)
                )
                latest_solution_count = int(
                    callback_model.cbGet(GRB.Callback.MIPNODE_SOLCNT)
                )
            progress_hook(
                DddFixedKArcFlowProgress(
                    elapsed_seconds=elapsed,
                    node_count=latest_node_count,
                    solver_incumbent=latest_incumbent,
                    solver_bound=latest_bound,
                    certified_lower_bound=certified_bound(latest_bound),
                    solver_gap=_relative_gap(latest_bound, latest_incumbent),
                    solution_count=latest_solution_count,
                    movement_variable_count=len(route),
                    passenger_variable_count=passenger_variable_count,
                    movement_constraint_count=movement_constraint_count,
                    passenger_constraint_count=passenger_constraint_count,
                    resource_row_count=resource_rows,
                    linear_constraint_count=int(model.NumConstrs),
                    remaining_seconds=max(
                        0.0, self.config.time_limit_seconds - elapsed
                    ),
                    phase=phase,
                    simplex_iteration_count=simplex_iterations,
                    barrier_iteration_count=barrier_iterations,
                    presolved_removed_row_count=removed_rows,
                    presolved_removed_column_count=removed_columns,
                )
            )

        solve_started = perf_counter()
        model.Params.TimeLimit = max(
            0.001,
            self.config.time_limit_seconds - (solve_started - started),
        )
        model.optimize(callback)
        solve_seconds = perf_counter() - solve_started
        if incumbent_hook_error is not None:
            raise RuntimeError(f"Arc-flow incumbent validation hook failed: {incumbent_hook_error}")

        solver_bound = _finite_solver_value(float(model.ObjBound))
        solver_objective = float(model.ObjVal) if model.SolCount > 0 else None
        objective = external_upper_bound
        solution: DddReferenceSolution | None = (
            None if primal_seed is None else primal_seed.solution
        )
        detail: str | None = None
        status = DddFixedKArcFlowStatus.UNKNOWN_NO_INCUMBENT
        if delayed_separation_error is not None:
            status = DddFixedKArcFlowStatus.INTERNAL_CERTIFICATE_ERROR
            detail = delayed_separation_error
        elif model.SolCount > 0:
            try:
                solver_solution = movement_master.extract_solution(
                    boundary_occurrences=problem.boundary_context.resource_occurrences,
                )
                validate_ddd_reference_solution(
                    prepared.movement,
                    solver_solution,
                    waiting_policy=(
                        problem.resolved_trajectory_problem.waiting_policy
                    ),
                )
                self._validate_passenger_solution(
                    problem=problem,
                    passenger_model=passenger_model,
                    objective=solver_objective,
                    model=model,
                )
            except (RuntimeError, ValueError) as error:
                detail = str(error)
                status = DddFixedKArcFlowStatus.INTERNAL_VALIDATION_ERROR
            else:
                if objective is None or (
                    solver_objective is not None
                    and solver_objective < objective - self.config.certificate_tolerance
                ):
                    objective = solver_objective
                    solution = solver_solution
                if delayed_separation_error is None:
                    status = (
                        DddFixedKArcFlowStatus.INTEGER_OPTIMAL
                        if model.Status == GRB.OPTIMAL
                        else DddFixedKArcFlowStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL
                    )
        elif model.Status == GRB.INFEASIBLE:
            if primal_seed is None:
                status = DddFixedKArcFlowStatus.MOVEMENT_INFEASIBLE
            else:
                status = DddFixedKArcFlowStatus.INTERNAL_CERTIFICATE_ERROR
                detail = "Gurobi declared a model with a validated primal seed infeasible"
                objective = None
                solution = None
        elif primal_seed is not None:
            status = DddFixedKArcFlowStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL

        lower_candidates = [problem.objective_floor]
        if solver_bound is not None:
            lower_candidates.append(solver_bound)
        if root_cg_lower_bound is not None:
            if not math.isfinite(root_cg_lower_bound):
                raise ValueError("Root-CG lower bound must be finite")
            lower_candidates.append(root_cg_lower_bound)
        certified_lower_bound = max(lower_candidates)
        if (
            objective is not None
            and certified_lower_bound > objective + self.config.certificate_tolerance
        ):
            status = DddFixedKArcFlowStatus.INTERNAL_CERTIFICATE_ERROR
            detail = "combined certified lower bound exceeds the validated incumbent"
            objective = None
            solution = None

        return DddFixedKArcFlowResult(
            status=status,
            problem_fingerprint=problem.fingerprint,
            objective_value=objective,
            solver_best_bound=solver_bound,
            root_cg_lower_bound=root_cg_lower_bound,
            certified_lower_bound=certified_lower_bound,
            validated_upper_bound=objective,
            relative_gap=_relative_gap(certified_lower_bound, objective),
            solution=solution,
            solver_status=int(model.Status),
            solution_count=int(model.SolCount),
            node_count=float(model.NodeCount),
            movement_variable_count=len(route),
            passenger_variable_count=passenger_variable_count,
            movement_constraint_count=movement_constraint_count,
            passenger_constraint_count=passenger_constraint_count,
            resource_row_count=resource_rows,
            linear_constraint_count=int(model.NumConstrs),
            network_build_seconds=network_build_seconds,
            model_build_seconds=model_build_seconds,
            solve_seconds=solve_seconds,
            total_seconds=perf_counter() - started,
            time_to_first_incumbent_seconds=(
                0.0 if primal_seed is not None else first_incumbent
            ),
            seed_kind=seed_kind,
            primal_seed_objective_value=external_upper_bound,
            detail=detail,
            passenger_profile=self.config.passenger_formulation.profile,
            model_fingerprint=passenger_encoding.fingerprint,
            passenger_audit_json=passenger_encoding.audit_json,
            passenger_domain_build_seconds=passenger_domain_build_seconds,
            integer_variable_count=int(model.NumIntVars),
            binary_variable_count=int(model.NumBinVars),
            nonzero_count=int(model.NumNZs),
        )

    @staticmethod
    def _validate_passenger_solution(
        *,
        problem: DddFixedKTrajectoryProblem,
        passenger_model: DddArcFlowIntegratedPassengerModel,
        objective: float | None,
        model: gp.Model,
    ) -> None:
        if objective is None or not math.isclose(
            objective, float(model.ObjVal), rel_tol=0.0, abs_tol=1e-4
        ):
            raise ValueError("arc-flow incumbent objective is inconsistent")
        demand = {group.id: 0.0 for group in problem.passenger_build.demand_groups}
        onboard_by_arc_id: dict[str, float] = {}
        variable_by_id = passenger_model.domain.variable_by_id
        canonical = passenger_model.canonical_values()
        for flow in passenger_model.domain.flows:
            for arc_id, variable_id in flow.variable_ids_by_arc_id:
                value = canonical[variable_id]
                if not math.isclose(value, round(value), abs_tol=1e-5):
                    raise ValueError("arc-flow passenger assignment is fractional")
                visit_index = variable_by_id[variable_id].visit_index
                if flow.board_visit_index <= visit_index < flow.alight_visit_index:
                    onboard_by_arc_id[arc_id] = (
                        onboard_by_arc_id.get(arc_id, 0.0) + value
                    )
            boarded = sum(
                canonical[variable_id]
                for _, variable_id in flow.variable_ids_by_arc_id
                if variable_by_id[variable_id].visit_index
                == flow.board_visit_index
            )
            demand[flow.demand_group_id] += boarded
        for group in problem.passenger_build.demand_groups:
            if demand[group.id] > group.count + 1e-5:
                raise ValueError("arc-flow passenger assignment exceeds demand")
        if any(
            value > problem.artifact.config.cabin_capacity + 1e-5
            for value in onboard_by_arc_id.values()
        ):
            raise ValueError("arc-flow passenger assignment exceeds cabin capacity")
def _relative_gap(lower: float | None, upper: float | None) -> float | None:
    if lower is None or upper is None:
        return None
    return max(0.0, upper - lower) / max(abs(upper), 1e-9)


def _finite_solver_value(value: float) -> float | None:
    return value if math.isfinite(value) and abs(value) < GRB.INFINITY / 2 else None


def _minimum_optional(left: float | None, right: float | None) -> float | None:
    values = tuple(value for value in (left, right) if value is not None)
    return None if not values else min(values)
