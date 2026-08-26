from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from time import perf_counter
from typing import Callable

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_movement_master import (
    DddArcFlowMovementMasterBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_passenger_domain import (
    DddArcFlowPassengerDomainBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_passenger_model import (
    DddArcFlowPassengerModelBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import (
    DddPreparedArcFlowProblem,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanPassengerAssignmentDomain,
)


class DddArcFlowRelaxationMethod(StrEnum):
    AUTO = "auto"
    DUAL_SIMPLEX = "dual_simplex"
    BARRIER_NO_CROSSOVER = "barrier_no_crossover"


class DddArcFlowRelaxationStatus(StrEnum):
    OPTIMAL = "optimal"
    TIME_LIMIT_WITH_CERTIFIED_BOUND = "time_limit_with_certified_bound"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"
    INTERNAL_CERTIFICATE_ERROR = "internal_certificate_error"


@dataclass(frozen=True, slots=True)
class DddArcFlowRelaxationConfig:
    time_limit_seconds: float = 600.0
    method: DddArcFlowRelaxationMethod = (
        DddArcFlowRelaxationMethod.BARRIER_NO_CROSSOVER
    )
    threads: int | None = None
    output_flag: bool = False
    progress_interval_seconds: float = 5.0
    certificate_tolerance: float = 1e-5

    def validate(self) -> None:
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("arc-flow relaxation time limit must be positive")
        if not isinstance(self.method, DddArcFlowRelaxationMethod):
            raise ValueError("arc-flow relaxation method is invalid")
        if self.threads is not None and self.threads <= 0:
            raise ValueError("arc-flow relaxation threads must be positive")
        if self.progress_interval_seconds <= 0 or self.certificate_tolerance <= 0:
            raise ValueError("arc-flow relaxation tolerances must be positive")


@dataclass(frozen=True, slots=True)
class DddArcFlowRelaxationProgress:
    phase: str
    elapsed_seconds: float
    remaining_seconds: float
    simplex_iterations: float | None
    barrier_iterations: int | None
    local_primal_objective: float | None
    local_dual_objective: float | None
    movement_variable_count: int
    passenger_variable_count: int
    linear_constraint_count: int


DddArcFlowRelaxationProgressHook = Callable[
    [DddArcFlowRelaxationProgress], None
]


@dataclass(frozen=True, slots=True)
class DddArcFlowRelaxationResult:
    status: DddArcFlowRelaxationStatus
    problem_fingerprint: str
    passenger_domain_fingerprint: str
    certified_lower_bound: float
    lp_primal_objective: float | None
    solver_status: int
    solution_count: int
    movement_fractional_variable_count: int | None
    passenger_fractional_variable_count: int | None
    movement_variable_count: int
    passenger_variable_count: int
    movement_constraint_count: int
    passenger_constraint_count: int
    resource_row_count: int
    linear_constraint_count: int
    passenger_domain_build_seconds: float
    model_build_seconds: float
    solve_seconds: float
    total_seconds: float
    method: DddArcFlowRelaxationMethod
    detail: str | None = None


@dataclass(slots=True)
class DddArcFlowRelaxationOptimizer:
    config: DddArcFlowRelaxationConfig = DddArcFlowRelaxationConfig()

    def solve(
        self,
        prepared: DddPreparedArcFlowProblem,
        *,
        progress_hook: DddArcFlowRelaxationProgressHook | None = None,
    ) -> DddArcFlowRelaxationResult:
        self.config.validate()
        prepared.validate()
        started = perf_counter()
        domain_started = perf_counter()
        domain = DddArcFlowPassengerDomainBuilder().build(prepared)
        domain_seconds = perf_counter() - domain_started
        self._publish(
            progress_hook,
            phase="model_build",
            started=started,
            movement_variables=len(prepared.arcs),
            passenger_variables=len(domain.variables),
            constraints=0,
        )
        model_started = perf_counter()
        model = gp.Model("ddd_complete_arc_flow_relaxation")
        model.Params.OutputFlag = int(self.config.output_flag)
        if self.config.threads is not None:
            model.Params.Threads = self.config.threads
        if self.config.method is DddArcFlowRelaxationMethod.DUAL_SIMPLEX:
            model.Params.Method = 1
        elif self.config.method is DddArcFlowRelaxationMethod.BARRIER_NO_CROSSOVER:
            model.Params.Method = 2
            model.Params.Crossover = 0
        movement = DddArcFlowMovementMasterBuilder().build(
            model=model,
            prepared=prepared,
            variable_type=GRB.CONTINUOUS,
        )
        passenger = DddArcFlowPassengerModelBuilder().build_integrated(
            model=model,
            domain=domain,
            route_by_arc_id=movement.route_by_arc_id,
            assignment_domain=EanPassengerAssignmentDomain.LP_RELAXATION,
        )
        model.ModelSense = GRB.MINIMIZE
        model.update()
        model_build_seconds = perf_counter() - model_started
        last_progress = -math.inf

        def callback(callback_model: gp.Model, where: int) -> None:
            nonlocal last_progress
            if progress_hook is None or where not in {
                GRB.Callback.SIMPLEX,
                GRB.Callback.BARRIER,
            }:
                return
            elapsed = perf_counter() - started
            if elapsed - last_progress < self.config.progress_interval_seconds:
                return
            last_progress = elapsed
            if where == GRB.Callback.BARRIER:
                self._publish(
                    progress_hook,
                    phase="barrier",
                    started=started,
                    movement_variables=movement.movement_variable_count,
                    passenger_variables=passenger.variable_count,
                    constraints=int(model.NumConstrs),
                    barrier_iterations=int(
                        callback_model.cbGet(GRB.Callback.BARRIER_ITRCNT)
                    ),
                    local_primal=_callback_finite(
                        callback_model.cbGet(GRB.Callback.BARRIER_PRIMOBJ)
                    ),
                    local_dual=_callback_finite(
                        callback_model.cbGet(GRB.Callback.BARRIER_DUALOBJ)
                    ),
                )
            else:
                self._publish(
                    progress_hook,
                    phase="simplex",
                    started=started,
                    movement_variables=movement.movement_variable_count,
                    passenger_variables=passenger.variable_count,
                    constraints=int(model.NumConstrs),
                    simplex_iterations=float(
                        callback_model.cbGet(GRB.Callback.SPX_ITRCNT)
                    ),
                    local_primal=_callback_finite(
                        callback_model.cbGet(GRB.Callback.SPX_OBJVAL)
                    ),
                )

        solve_started = perf_counter()
        model.Params.TimeLimit = max(
            0.001,
            self.config.time_limit_seconds - (solve_started - started),
        )
        model.optimize(callback)
        solve_seconds = perf_counter() - solve_started
        bound = _finite_value(model.ObjBound)
        objective = (
            float(model.ObjVal) if int(model.SolCount) > 0 else None
        )
        certified = max(
            prepared.problem.objective_floor,
            prepared.problem.objective_floor if bound is None else bound,
        )
        detail = None
        if model.Status == GRB.OPTIMAL:
            status = DddArcFlowRelaxationStatus.OPTIMAL
        elif model.Status == GRB.TIME_LIMIT and bound is not None:
            status = DddArcFlowRelaxationStatus.TIME_LIMIT_WITH_CERTIFIED_BOUND
        elif model.Status == GRB.INFEASIBLE:
            status = DddArcFlowRelaxationStatus.INFEASIBLE
        else:
            status = DddArcFlowRelaxationStatus.UNKNOWN
        if (
            objective is not None
            and certified > objective + self.config.certificate_tolerance
        ):
            status = DddArcFlowRelaxationStatus.INTERNAL_CERTIFICATE_ERROR
            detail = "relaxation bound exceeds its primal objective"
        movement_fractional = None
        passenger_fractional = None
        if objective is not None:
            movement_fractional = sum(
                not math.isclose(variable.X, round(variable.X), abs_tol=1e-6)
                for variable in movement.route_by_arc_id.values()
            )
            passenger_fractional = sum(
                not math.isclose(variable.X, round(variable.X), abs_tol=1e-6)
                for variable in passenger.variable_by_id.values()
            )
        self._publish(
            progress_hook,
            phase="complete",
            started=started,
            movement_variables=movement.movement_variable_count,
            passenger_variables=passenger.variable_count,
            constraints=int(model.NumConstrs),
        )
        return DddArcFlowRelaxationResult(
            status=status,
            problem_fingerprint=prepared.problem.fingerprint,
            passenger_domain_fingerprint=domain.fingerprint,
            certified_lower_bound=certified,
            lp_primal_objective=objective,
            solver_status=int(model.Status),
            solution_count=int(model.SolCount),
            movement_fractional_variable_count=movement_fractional,
            passenger_fractional_variable_count=passenger_fractional,
            movement_variable_count=movement.movement_variable_count,
            passenger_variable_count=passenger.variable_count,
            movement_constraint_count=movement.movement_constraint_count,
            passenger_constraint_count=passenger.constraint_count,
            resource_row_count=movement.resource_row_count,
            linear_constraint_count=int(model.NumConstrs),
            passenger_domain_build_seconds=domain_seconds,
            model_build_seconds=model_build_seconds,
            solve_seconds=solve_seconds,
            total_seconds=perf_counter() - started,
            method=self.config.method,
            detail=detail,
        )

    def _publish(
        self,
        hook: DddArcFlowRelaxationProgressHook | None,
        *,
        phase: str,
        started: float,
        movement_variables: int,
        passenger_variables: int,
        constraints: int,
        simplex_iterations: float | None = None,
        barrier_iterations: int | None = None,
        local_primal: float | None = None,
        local_dual: float | None = None,
    ) -> None:
        if hook is None:
            return
        elapsed = perf_counter() - started
        hook(
            DddArcFlowRelaxationProgress(
                phase=phase,
                elapsed_seconds=elapsed,
                remaining_seconds=max(
                    0.0,
                    self.config.time_limit_seconds - elapsed,
                ),
                simplex_iterations=simplex_iterations,
                barrier_iterations=barrier_iterations,
                local_primal_objective=local_primal,
                local_dual_objective=local_dual,
                movement_variable_count=movement_variables,
                passenger_variable_count=passenger_variables,
                linear_constraint_count=constraints,
            )
        )


def _finite_value(value: float) -> float | None:
    return value if math.isfinite(value) and abs(value) < GRB.INFINITY / 2 else None


def _callback_finite(value: float) -> float | None:
    return _finite_value(float(value))
