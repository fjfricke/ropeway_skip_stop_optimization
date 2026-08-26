from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from time import perf_counter
from typing import Callable

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.arc_flow import (
    DddFixedKArcFlowProgress,
    DddFixedKArcFlowSolveConfig,
    DddFixedKArcFlowStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_movement_master import (
    build_ddd_arc_flow_movement_values,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import (
    DddArcFlowProblemPreparer,
    DddPreparedArcFlowProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.exact_anonymous_arc_flow_network import (
    DddExactAnonymousArc,
    DddExactAnonymousArcFlowNetwork,
    DddExactAnonymousArcFlowNetworkBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.exact_anonymous_passenger import (
    DddExactAnonymousPassengerModel,
    DddExactAnonymousPassengerModelBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKTrajectoryProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k_primal_seed import (
    DddFixedKPrimalSeed,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceOccurrence,
    DddReferenceSolution,
    DddReferenceTrajectory,
    build_ddd_reference_visit,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_tick_to_seconds,
)


@dataclass(frozen=True, slots=True)
class DddExactAnonymousArcFlowResult:
    status: DddFixedKArcFlowStatus
    problem_fingerprint: str
    network_fingerprint: str
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
    exact_node_count: int
    movement_variable_count: int
    passenger_variable_count: int
    movement_constraint_count: int
    passenger_constraint_count: int
    resource_row_count: int
    linear_constraint_count: int
    labeled_movement_arc_count: int
    network_build_seconds: float
    model_build_seconds: float
    solve_seconds: float
    total_seconds: float
    time_to_first_incumbent_seconds: float | None
    primal_seed_objective_value: float | None = None
    seed_kind: str | None = None
    detail: str | None = None

    @property
    def movement_compression_ratio(self) -> float:
        return self.movement_variable_count / max(self.labeled_movement_arc_count, 1)


DddExactAnonymousArcFlowProgressHook = Callable[[DddFixedKArcFlowProgress], None]


@dataclass(slots=True)
class _DddExactAnonymousMovementMaster:
    prepared: DddPreparedArcFlowProblem
    network: DddExactAnonymousArcFlowNetwork
    model: gp.Model
    route_by_arc_id: dict[str, gp.Var]
    movement_constraint_count: int
    resource_row_count: int

    def apply_seed(self, solution: DddReferenceSolution) -> None:
        values = build_ddd_exact_anonymous_movement_values(
            self.prepared,
            self.network,
            solution,
        )
        for arc_id, variable in self.route_by_arc_id.items():
            variable.Start = values[arc_id]

    def extract_solution(self) -> DddReferenceSolution:
        movement = self.prepared.movement
        option_by_id = {option.id: option for option in movement.route_options}
        selected = {
            arc_id
            for arc_id, variable in self.route_by_arc_id.items()
            if variable.X > 0.5
        }
        outgoing: dict[str, list[DddExactAnonymousArc]] = defaultdict(list)
        for arc in self.network.movement_arcs:
            assert arc.source_node_id is not None
            if arc.id in selected:
                outgoing[arc.source_node_id].append(arc)
        boundary_by_cabin: dict[int, list[DddReferenceResourceOccurrence]] = (
            defaultdict(list)
        )
        for occurrence in self.prepared.problem.boundary_context.resource_occurrences:
            boundary_by_cabin[occurrence.cabin_id].append(occurrence)
        trajectories: list[DddReferenceTrajectory] = []
        consumed: set[str] = set()
        for token in self.network.start_tokens:
            source = tuple(
                arc
                for arc in self.network.source_arcs
                if arc.source_token_id == token.id and arc.id in selected
            )
            if len(source) != 1:
                raise RuntimeError("anonymous solution does not select one source arc")
            arc = source[0]
            visits = []
            for visit_index in range(token.start.max_visit_count):
                consumed.add(arc.id)
                visits.append(
                    build_ddd_reference_visit(
                        start=token.start,
                        visit_index=visit_index,
                        switch_time_seconds=ddd_tick_to_seconds(arc.source_tick),
                        option=option_by_id[arc.option_id],
                        operational_end_seconds=movement.operational_end_seconds,
                        tolerance_seconds=0.0,
                    )
                )
                if arc.target_node_id is None:
                    break
                candidates = tuple(outgoing.get(arc.target_node_id, ()))
                if len(candidates) != 1:
                    raise RuntimeError(
                        "anonymous integral flow cannot be decomposed uniquely"
                    )
                arc = candidates[0]
            else:
                raise RuntimeError("anonymous path exhausted its visit bound")
            trajectories.append(
                DddReferenceTrajectory(
                    cabin_id=token.canonical_cabin_id,
                    visits=tuple(visits),
                    boundary_resource_occurrences=tuple(
                        sorted(
                            boundary_by_cabin.get(token.canonical_cabin_id, ()),
                            key=lambda item: (
                                item.resource_id,
                                item.follower_enter_time_seconds,
                                item.visit_index,
                            ),
                        )
                    ),
                )
            )
        if consumed != selected:
            raise RuntimeError("anonymous solution contains disconnected selected flow")
        result = DddReferenceSolution(tuple(trajectories))
        validate_ddd_reference_solution(movement, result)
        return result


@dataclass(frozen=True, slots=True)
class _DddExactAnonymousMovementMasterBuilder:
    def build(
        self,
        *,
        model: gp.Model,
        prepared: DddPreparedArcFlowProblem,
        network: DddExactAnonymousArcFlowNetwork,
    ) -> _DddExactAnonymousMovementMaster:
        prepared.validate()
        network.validate()
        route = {
            arc.id: model.addVar(
                lb=0.0,
                ub=1.0,
                vtype=GRB.BINARY,
                name=f"exact_route[{index}]",
            )
            for index, arc in enumerate(network.arcs)
        }
        outgoing: dict[str, list[DddExactAnonymousArc]] = defaultdict(list)
        incoming: dict[str, list[DddExactAnonymousArc]] = defaultdict(list)
        source_by_token: dict[str, list[DddExactAnonymousArc]] = defaultdict(list)
        for arc in network.arcs:
            if arc.source_token_id is not None:
                source_by_token[arc.source_token_id].append(arc)
            if arc.source_node_id is not None:
                outgoing[arc.source_node_id].append(arc)
            if arc.target_node_id is not None:
                incoming[arc.target_node_id].append(arc)
        movement_rows = 0
        for token in network.start_tokens:
            model.addConstr(
                gp.quicksum(route[arc.id] for arc in source_by_token[token.id]) == 1,
                name=f"exact_source[{token.id}]",
            )
            movement_rows += 1
        for node in network.nodes:
            incoming_variables = tuple(route[arc.id] for arc in incoming[node.id])
            outgoing_variables = tuple(route[arc.id] for arc in outgoing[node.id])
            if incoming_variables or outgoing_variables:
                model.addConstr(
                    gp.quicksum(incoming_variables) == gp.quicksum(outgoing_variables),
                    name=f"exact_flow[{movement_rows}]",
                )
                model.addConstr(
                    gp.quicksum(incoming_variables) <= 1,
                    name=f"exact_node_capacity[{movement_rows}]",
                )
                movement_rows += 2
        model.addConstr(
            gp.quicksum(route[arc.id] for arc in network.terminal_arcs)
            == len(network.start_tokens),
            name="exact_sink_cardinality",
        )
        movement_rows += 1
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
                name=f"exact_resource[{resource_rows}]",
            )
            resource_rows += 1
        return _DddExactAnonymousMovementMaster(
            prepared=prepared,
            network=network,
            model=model,
            route_by_arc_id=route,
            movement_constraint_count=movement_rows,
            resource_row_count=resource_rows,
        )


@dataclass(slots=True)
class DddExactAnonymousArcFlowOptimizer:
    config: DddFixedKArcFlowSolveConfig = DddFixedKArcFlowSolveConfig()

    def solve(
        self,
        problem: DddFixedKTrajectoryProblem,
        *,
        primal_seed: DddFixedKPrimalSeed | None = None,
        root_cg_lower_bound: float | None = None,
        progress_hook: DddExactAnonymousArcFlowProgressHook | None = None,
    ) -> DddExactAnonymousArcFlowResult:
        self.config.validate()
        problem.validate()
        if root_cg_lower_bound is not None and not math.isfinite(root_cg_lower_bound):
            raise ValueError("Root-CG lower bound must be finite")
        if primal_seed is not None:
            primal_seed.validate(problem)
        started = perf_counter()
        self._publish_empty(
            progress_hook,
            problem,
            started,
            "network_build",
            primal_seed,
            root_cg_lower_bound,
        )
        prepared = DddArcFlowProblemPreparer().build(problem)
        network = DddExactAnonymousArcFlowNetworkBuilder().build(prepared)
        network_build_seconds = perf_counter() - started
        self._publish_empty(
            progress_hook,
            problem,
            started,
            "model_build",
            primal_seed,
            root_cg_lower_bound,
        )
        model_started = perf_counter()
        model = gp.Model("ddd_exact_anonymous_fixed_k_arc_flow")
        model.Params.OutputFlag = int(self.config.output_flag)
        model.Params.Seed = self.config.seed
        model.Params.MIPFocus = self.config.mip_focus
        model.Params.MIPGap = self.config.mip_gap
        if self.config.threads is not None:
            model.Params.Threads = self.config.threads
        model.ModelSense = GRB.MINIMIZE
        movement_master = _DddExactAnonymousMovementMasterBuilder().build(
            model=model,
            prepared=prepared,
            network=network,
        )
        passenger_master = DddExactAnonymousPassengerModelBuilder().build(
            model=model,
            problem=problem,
            network=network,
            route_by_arc_id=movement_master.route_by_arc_id,
        )
        if primal_seed is not None:
            movement_master.apply_seed(primal_seed.solution)
            labeled_seed_values = build_ddd_arc_flow_movement_values(
                prepared,
                primal_seed.solution,
            )
            passenger_master.apply_seed(
                problem=problem,
                prepared=prepared,
                network=network,
                seed=primal_seed,
                labeled_movement_values=labeled_seed_values,
            )
            model.addConstr(
                model.getObjective()
                <= primal_seed.objective_value + self.config.certificate_tolerance,
                name="validated_primal_cutoff",
            )
        model.update()
        model_build_seconds = perf_counter() - model_started
        remaining = self.config.time_limit_seconds - (perf_counter() - started)
        if remaining <= 0:
            return self._budget_exhausted_result(
                problem,
                prepared,
                network,
                movement_master,
                passenger_master,
                started,
                network_build_seconds,
                model_build_seconds,
                primal_seed,
                root_cg_lower_bound,
            )
        model.Params.TimeLimit = remaining
        first_incumbent: float | None = None
        last_progress = -math.inf

        def callback(callback_model: gp.Model, where: int) -> None:
            nonlocal first_incumbent, last_progress
            elapsed = perf_counter() - started
            if where == GRB.Callback.MIPSOL and first_incumbent is None:
                first_incumbent = elapsed
            if progress_hook is None or where != GRB.Callback.MIP:
                return
            if elapsed - last_progress < self.config.progress_interval_seconds:
                return
            last_progress = elapsed
            incumbent = _finite_or_none(callback_model.cbGet(GRB.Callback.MIP_OBJBST))
            bound = _finite_or_none(callback_model.cbGet(GRB.Callback.MIP_OBJBND))
            external = None if primal_seed is None else primal_seed.objective_value
            incumbent = _minimum_optional(incumbent, external)
            certified = self._certified_bound(problem, root_cg_lower_bound, bound)
            progress_hook(
                DddFixedKArcFlowProgress(
                    elapsed_seconds=elapsed,
                    node_count=float(callback_model.cbGet(GRB.Callback.MIP_NODCNT)),
                    solver_incumbent=incumbent,
                    solver_bound=bound,
                    certified_lower_bound=certified,
                    solver_gap=_relative_gap(certified, incumbent),
                    solution_count=int(callback_model.cbGet(GRB.Callback.MIP_SOLCNT)),
                    movement_variable_count=len(movement_master.route_by_arc_id),
                    passenger_variable_count=passenger_master.variable_count,
                    movement_constraint_count=movement_master.movement_constraint_count,
                    passenger_constraint_count=passenger_master.constraint_count,
                    resource_row_count=movement_master.resource_row_count,
                    linear_constraint_count=int(model.NumConstrs),
                    remaining_seconds=max(
                        0.0, self.config.time_limit_seconds - elapsed
                    ),
                    phase="branch_and_bound",
                )
            )

        solve_started = perf_counter()
        model.optimize(callback)
        solve_seconds = perf_counter() - solve_started
        solver_bound = _finite_or_none(float(model.ObjBound))
        certified = self._certified_bound(problem, root_cg_lower_bound, solver_bound)
        solver_objective = float(model.ObjVal) if int(model.SolCount) > 0 else None
        solver_solution: DddReferenceSolution | None = None
        detail = None
        status = DddFixedKArcFlowStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL
        if solver_objective is not None:
            try:
                solver_solution = movement_master.extract_solution()
            except (RuntimeError, ValueError) as error:
                status = DddFixedKArcFlowStatus.INTERNAL_VALIDATION_ERROR
                detail = str(error)
                solver_objective = None
        seed_objective = None if primal_seed is None else primal_seed.objective_value
        objective = _minimum_optional(solver_objective, seed_objective)
        solution = (
            solver_solution
            if solver_objective is not None
            and (seed_objective is None or solver_objective < seed_objective - 1e-6)
            else (None if primal_seed is None else primal_seed.solution)
        )
        if status is not DddFixedKArcFlowStatus.INTERNAL_VALIDATION_ERROR:
            if model.Status == GRB.INFEASIBLE:
                if primal_seed is not None:
                    status = DddFixedKArcFlowStatus.INTERNAL_VALIDATION_ERROR
                    detail = "exact anonymous model rejected a validated primal seed"
                else:
                    status = DddFixedKArcFlowStatus.MOVEMENT_INFEASIBLE
            elif objective is None:
                status = DddFixedKArcFlowStatus.UNKNOWN_NO_INCUMBENT
            elif certified > objective + self.config.certificate_tolerance:
                status = DddFixedKArcFlowStatus.INTERNAL_CERTIFICATE_ERROR
                detail = (
                    "exact anonymous certified lower bound exceeds the validated UB"
                )
                objective = None
                solution = None
            elif (
                model.Status == GRB.OPTIMAL
                or objective - certified <= self.config.certificate_tolerance
            ):
                status = DddFixedKArcFlowStatus.INTEGER_OPTIMAL
        total = perf_counter() - started
        result = DddExactAnonymousArcFlowResult(
            status=status,
            problem_fingerprint=problem.fingerprint,
            network_fingerprint=network.fingerprint,
            objective_value=objective,
            solver_best_bound=solver_bound,
            root_cg_lower_bound=root_cg_lower_bound,
            certified_lower_bound=certified,
            validated_upper_bound=objective,
            relative_gap=_relative_gap(certified, objective),
            solution=solution,
            solver_status=int(model.Status),
            solution_count=int(model.SolCount),
            node_count=float(model.NodeCount),
            exact_node_count=len(network.nodes),
            movement_variable_count=len(movement_master.route_by_arc_id),
            passenger_variable_count=passenger_master.variable_count,
            movement_constraint_count=movement_master.movement_constraint_count,
            passenger_constraint_count=passenger_master.constraint_count,
            resource_row_count=movement_master.resource_row_count,
            linear_constraint_count=int(model.NumConstrs),
            labeled_movement_arc_count=len(prepared.arcs),
            network_build_seconds=network_build_seconds,
            model_build_seconds=model_build_seconds,
            solve_seconds=solve_seconds,
            total_seconds=total,
            time_to_first_incumbent_seconds=(
                0.0 if primal_seed is not None else first_incumbent
            ),
            primal_seed_objective_value=seed_objective,
            seed_kind=None if primal_seed is None else primal_seed.provenance,
            detail=detail,
        )
        if progress_hook is not None:
            progress_hook(
                DddFixedKArcFlowProgress(
                    elapsed_seconds=total,
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
                    remaining_seconds=max(0.0, self.config.time_limit_seconds - total),
                    phase="solve_complete",
                )
            )
        return result

    @staticmethod
    def _certified_bound(
        problem: DddFixedKTrajectoryProblem,
        root_cg_lower_bound: float | None,
        solver_bound: float | None,
    ) -> float:
        return max(
            value
            for value in (
                problem.objective_floor,
                root_cg_lower_bound,
                solver_bound,
            )
            if value is not None
        )

    def _publish_empty(
        self,
        hook: DddExactAnonymousArcFlowProgressHook | None,
        problem: DddFixedKTrajectoryProblem,
        started: float,
        phase: str,
        seed: DddFixedKPrimalSeed | None,
        root_cg_lower_bound: float | None,
    ) -> None:
        if hook is None:
            return
        elapsed = perf_counter() - started
        incumbent = None if seed is None else seed.objective_value
        certified = self._certified_bound(problem, root_cg_lower_bound, None)
        hook(
            DddFixedKArcFlowProgress(
                elapsed_seconds=elapsed,
                node_count=0.0,
                solver_incumbent=incumbent,
                solver_bound=None,
                certified_lower_bound=certified,
                solver_gap=_relative_gap(certified, incumbent),
                solution_count=0,
                movement_variable_count=0,
                passenger_variable_count=0,
                movement_constraint_count=0,
                passenger_constraint_count=0,
                resource_row_count=0,
                linear_constraint_count=0,
                remaining_seconds=max(0.0, self.config.time_limit_seconds - elapsed),
                phase=phase,
            )
        )

    def _budget_exhausted_result(
        self,
        problem: DddFixedKTrajectoryProblem,
        prepared: DddPreparedArcFlowProblem,
        network: DddExactAnonymousArcFlowNetwork,
        movement: _DddExactAnonymousMovementMaster,
        passenger: DddExactAnonymousPassengerModel,
        started: float,
        network_build_seconds: float,
        model_build_seconds: float,
        seed: DddFixedKPrimalSeed | None,
        root_cg_lower_bound: float | None,
    ) -> DddExactAnonymousArcFlowResult:
        lower = self._certified_bound(problem, root_cg_lower_bound, None)
        upper = None if seed is None else seed.objective_value
        return DddExactAnonymousArcFlowResult(
            status=(
                DddFixedKArcFlowStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL
                if seed is not None
                else DddFixedKArcFlowStatus.UNKNOWN_NO_INCUMBENT
            ),
            problem_fingerprint=problem.fingerprint,
            network_fingerprint=network.fingerprint,
            objective_value=upper,
            solver_best_bound=None,
            root_cg_lower_bound=root_cg_lower_bound,
            certified_lower_bound=lower,
            validated_upper_bound=upper,
            relative_gap=_relative_gap(lower, upper),
            solution=None if seed is None else seed.solution,
            solver_status=int(GRB.TIME_LIMIT),
            solution_count=0,
            node_count=0.0,
            exact_node_count=len(network.nodes),
            movement_variable_count=len(movement.route_by_arc_id),
            passenger_variable_count=passenger.variable_count,
            movement_constraint_count=movement.movement_constraint_count,
            passenger_constraint_count=passenger.constraint_count,
            resource_row_count=movement.resource_row_count,
            linear_constraint_count=int(movement.model.NumConstrs),
            labeled_movement_arc_count=len(prepared.arcs),
            network_build_seconds=network_build_seconds,
            model_build_seconds=model_build_seconds,
            solve_seconds=0.0,
            total_seconds=perf_counter() - started,
            time_to_first_incumbent_seconds=None,
            primal_seed_objective_value=upper,
            seed_kind=None if seed is None else seed.provenance,
            detail="total budget exhausted during exact anonymous model build",
        )


def build_ddd_exact_anonymous_movement_values(
    prepared: DddPreparedArcFlowProblem,
    network: DddExactAnonymousArcFlowNetwork,
    solution: DddReferenceSolution,
) -> dict[str, float]:
    """Project a labeled physical schedule into the exact anonymous quotient."""

    labeled = build_ddd_arc_flow_movement_values(prepared, solution)
    result: dict[str, float] = {}
    for arc in network.arcs:
        value = sum(labeled[item] for item in arc.represented_labeled_arc_ids)
        if value > 1.0 + 1e-6:
            raise ValueError("labeled seed collides after exact anonymous projection")
        result[arc.id] = 1.0 if value > 0.5 else 0.0
    return result


def _finite_or_none(value: float) -> float | None:
    numeric = float(value)
    return (
        numeric
        if math.isfinite(numeric) and abs(numeric) < GRB.INFINITY * 0.5
        else None
    )


def _minimum_optional(first: float | None, second: float | None) -> float | None:
    values = tuple(value for value in (first, second) if value is not None)
    return min(values) if values else None


def _relative_gap(lower: float, upper: float | None) -> float | None:
    if upper is None:
        return None
    return max(0.0, upper - lower) / max(abs(upper), 1e-9)
