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
    DddArcFlowPassengerDomain,
    DddArcFlowPassengerDomainBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import (
    DddPreparedArcFlowProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.passenger_partial_master import (
    DddPartialPassengerDomainBuilder,
    DddPartialPassengerModelBuilder,
    DddPassengerCoreConfig,
    DddPassengerCorePartition,
)
from ropeway_skip_stop_optimization.optimization.ddd.passenger_pareto_cuts import (
    DddParetoPassengerCutGenerator,
    DddPassengerCorePoint,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanPassengerAssignmentDomain,
)


class DddPartialPassengerRootStatus(StrEnum):
    PROJECTED_LP_OPTIMAL = "projected_lp_optimal"
    TIME_LIMIT_WITH_CERTIFIED_BOUND = "time_limit_with_certified_bound"
    ITERATION_LIMIT_WITH_CERTIFIED_BOUND = "iteration_limit_with_certified_bound"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"
    INTERNAL_CERTIFICATE_ERROR = "internal_certificate_error"


class DddPartialPassengerCutStrategy(StrEnum):
    STANDARD = "standard"
    CORE_POINT = "core_point"


@dataclass(frozen=True, slots=True)
class DddPartialPassengerRootConfig:
    core: DddPassengerCoreConfig = DddPassengerCoreConfig()
    time_limit_seconds: float = 120.0
    max_iterations: int = 30
    threads: int | None = None
    output_flag: bool = False
    cut_violation_tolerance: float = 1e-5
    certificate_tolerance: float = 1e-5
    cut_strategy: DddPartialPassengerCutStrategy = (
        DddPartialPassengerCutStrategy.STANDARD
    )
    core_point_previous_weight: float = 0.5
    pareto_time_limit_seconds: float = 10.0

    def validate(self) -> None:
        self.core.validate()
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("partial Passenger root time limit must be positive")
        if self.max_iterations <= 0:
            raise ValueError("partial Passenger root iteration limit must be positive")
        if self.threads is not None and self.threads <= 0:
            raise ValueError("partial Passenger root threads must be positive")
        if self.cut_violation_tolerance <= 0 or self.certificate_tolerance <= 0:
            raise ValueError("partial Passenger root tolerances must be positive")
        if not isinstance(self.cut_strategy, DddPartialPassengerCutStrategy):
            raise ValueError("partial Passenger cut strategy is invalid")
        if not 0 < self.core_point_previous_weight < 1:
            raise ValueError("partial Passenger core-point weight is invalid")
        if (
            not math.isfinite(self.pareto_time_limit_seconds)
            or self.pareto_time_limit_seconds <= 0
        ):
            raise ValueError("partial Passenger Pareto budget must be positive")


@dataclass(frozen=True, slots=True)
class DddPartialPassengerRootIteration:
    iteration: int
    master_status: int
    master_objective: float | None
    master_bound: float | None
    residual_theta: float | None
    residual_objective: float | None
    cut_violation: float | None
    cut_added: bool
    cut_kind: str | None
    certified_lower_bound: float
    master_seconds: float
    recourse_seconds: float
    pareto_seconds: float
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class DddPartialPassengerRootProgress:
    phase: str
    iteration: int
    cut_count: int
    certified_lower_bound: float
    elapsed_seconds: float
    remaining_seconds: float


DddPartialPassengerRootProgressHook = Callable[
    [DddPartialPassengerRootProgress], None
]


@dataclass(frozen=True, slots=True)
class DddPartialPassengerRootResult:
    status: DddPartialPassengerRootStatus
    problem_fingerprint: str
    passenger_domain_fingerprint: str
    partition: DddPassengerCorePartition
    certified_lower_bound: float
    projected_lp_objective: float | None
    projected_lp_certified: bool
    cut_count: int
    iterations: tuple[DddPartialPassengerRootIteration, ...]
    movement_variable_count: int
    core_passenger_variable_count: int
    residual_passenger_variable_count: int
    movement_constraint_count: int
    core_passenger_constraint_count: int
    resource_row_count: int
    master_constraint_count: int
    passenger_domain_build_seconds: float
    master_build_seconds: float
    master_solve_seconds: float
    recourse_solve_seconds: float
    pareto_solve_seconds: float
    total_seconds: float
    detail: str | None = None


@dataclass(slots=True)
class DddPartialPassengerRootCutSolver:
    config: DddPartialPassengerRootConfig = DddPartialPassengerRootConfig()

    def solve(
        self,
        prepared: DddPreparedArcFlowProblem,
        *,
        passenger_domain: DddArcFlowPassengerDomain | None = None,
        progress_hook: DddPartialPassengerRootProgressHook | None = None,
    ) -> DddPartialPassengerRootResult:
        self.config.validate()
        prepared.validate()
        started = perf_counter()
        domain_started = perf_counter()
        full_domain = passenger_domain or DddArcFlowPassengerDomainBuilder().build(
            prepared
        )
        full_domain.validate(prepared)
        partial_domain = DddPartialPassengerDomainBuilder().build(
            prepared,
            full_domain,
            self.config.core,
        )
        domain_seconds = perf_counter() - domain_started
        self._publish(progress_hook, "master_build", 0, 0, 0.0, started)
        build_started = perf_counter()
        model = gp.Model("ddd_partial_passenger_root")
        model.Params.OutputFlag = int(self.config.output_flag)
        if self.config.threads is not None:
            model.Params.Threads = self.config.threads
        movement = DddArcFlowMovementMasterBuilder().build(
            model=model,
            prepared=prepared,
            variable_type=GRB.CONTINUOUS,
        )
        passenger_builder = DddPartialPassengerModelBuilder()
        passenger = passenger_builder.build_master_contribution(
            model=model,
            domain=partial_domain,
            route_by_arc_id=movement.route_by_arc_id,
            assignment_domain=EanPassengerAssignmentDomain.LP_RELAXATION,
        )
        recourse = passenger_builder.build_residual_recourse(
            domain=partial_domain,
            output_flag=self.config.output_flag,
            threads=self.config.threads,
        )
        model.update()
        build_seconds = perf_counter() - build_started
        lower_bound = prepared.problem.objective_floor
        projected_objective = None
        projected_certified = False
        status = DddPartialPassengerRootStatus.UNKNOWN
        detail = None
        iterations: list[DddPartialPassengerRootIteration] = []
        master_seconds_total = 0.0
        recourse_seconds_total = 0.0
        pareto_seconds_total = 0.0
        previous_master_bound: float | None = None
        core_point: DddPassengerCorePoint | None = None
        pareto_generator: DddParetoPassengerCutGenerator | None = None

        for iteration in range(1, self.config.max_iterations + 1):
            remaining = self.config.time_limit_seconds - (perf_counter() - started)
            if remaining <= 0:
                status = DddPartialPassengerRootStatus.TIME_LIMIT_WITH_CERTIFIED_BOUND
                break
            self._publish(
                progress_hook,
                "master",
                iteration,
                len(passenger.cut_constraint_by_id),
                lower_bound,
                started,
            )
            model.Params.TimeLimit = max(0.001, remaining)
            master_started = perf_counter()
            model.optimize()
            master_seconds = perf_counter() - master_started
            master_seconds_total += master_seconds
            master_bound = _finite(model.ObjBound)
            if master_bound is not None:
                if (
                    previous_master_bound is not None
                    and master_bound
                    < previous_master_bound - self.config.certificate_tolerance
                ):
                    status = DddPartialPassengerRootStatus.INTERNAL_CERTIFICATE_ERROR
                    detail = "partial Passenger root lower bound decreased"
                    break
                previous_master_bound = master_bound
                lower_bound = max(lower_bound, master_bound)
            if model.Status == GRB.INFEASIBLE:
                status = DddPartialPassengerRootStatus.INFEASIBLE
                break
            if int(model.SolCount) <= 0:
                status = (
                    DddPartialPassengerRootStatus.TIME_LIMIT_WITH_CERTIFIED_BOUND
                    if model.Status == GRB.TIME_LIMIT
                    else DddPartialPassengerRootStatus.UNKNOWN
                )
                break
            master_objective = float(model.ObjVal)
            if lower_bound > master_objective + self.config.certificate_tolerance:
                status = DddPartialPassengerRootStatus.INTERNAL_CERTIFICATE_ERROR
                detail = "partial Passenger root bound exceeds master objective"
                break
            theta = float(passenger.residual_theta.X)
            movement_values = {
                arc_id: float(variable.X)
                for arc_id, variable in movement.route_by_arc_id.items()
            }
            core_values = passenger.core_values()
            remaining = self.config.time_limit_seconds - (perf_counter() - started)
            if remaining <= 0:
                status = DddPartialPassengerRootStatus.TIME_LIMIT_WITH_CERTIFIED_BOUND
                break
            self._publish(
                progress_hook,
                "residual_lp",
                iteration,
                len(passenger.cut_constraint_by_id),
                lower_bound,
                started,
            )
            residual = recourse.evaluate(
                movement_values,
                core_values,
                time_limit_seconds=remaining,
                tightness_tolerance=self.config.certificate_tolerance,
            )
            recourse_seconds = residual.recourse.solve_seconds
            recourse_seconds_total += recourse_seconds
            if (
                not residual.recourse.optimal
                or residual.recourse.objective_value is None
                or residual.cut is None
            ):
                status = DddPartialPassengerRootStatus.TIME_LIMIT_WITH_CERTIFIED_BOUND
                break
            violation = residual.recourse.objective_value - theta
            cut_added = False
            selected_cut = residual.cut
            pareto_seconds = 0.0
            if core_point is None:
                core_point = DddPassengerCorePoint.from_point(
                    movement_values,
                    core_values,
                )
            else:
                core_point = core_point.update(
                    movement_values,
                    core_values,
                    previous_weight=self.config.core_point_previous_weight,
                )
                if (
                    violation > self.config.cut_violation_tolerance
                    and self.config.cut_strategy
                    is DddPartialPassengerCutStrategy.CORE_POINT
                ):
                    if pareto_generator is None:
                        pareto_started = perf_counter()
                        pareto_generator = DddParetoPassengerCutGenerator(
                            partial_domain,
                            output_flag=self.config.output_flag,
                            threads=self.config.threads,
                        )
                        pareto_seconds += perf_counter() - pareto_started
                    pareto_remaining = self.config.time_limit_seconds - (
                        perf_counter() - started
                    )
                    if pareto_remaining > 0:
                        strengthened = pareto_generator.generate(
                            source_movement_values=movement_values,
                            source_core_values=core_values,
                            source_objective=residual.recourse.objective_value,
                            core_point=core_point,
                            time_limit_seconds=min(
                                self.config.pareto_time_limit_seconds,
                                pareto_remaining,
                            ),
                            tightness_tolerance=self.config.certificate_tolerance,
                        )
                        pareto_seconds += strengthened.solve_seconds
                        if strengthened.cut is not None:
                            standard_core_value = residual.cut.evaluate(
                                core_point.movement_value_by_arc_id,
                                core_point.core_value_by_variable_id,
                            )
                            if (
                                strengthened.core_point_value is not None
                                and strengthened.core_point_value
                                >= standard_core_value
                                - self.config.certificate_tolerance
                            ):
                                selected_cut = strengthened.cut
            pareto_seconds_total += pareto_seconds
            if violation > self.config.cut_violation_tolerance:
                cut_added = passenger.add_cut(model, selected_cut)
                if not cut_added:
                    status = DddPartialPassengerRootStatus.INTERNAL_CERTIFICATE_ERROR
                    detail = "violated partial Passenger cut was already present"
            iterations.append(
                DddPartialPassengerRootIteration(
                    iteration=iteration,
                    master_status=int(model.Status),
                    master_objective=master_objective,
                    master_bound=master_bound,
                    residual_theta=theta,
                    residual_objective=residual.recourse.objective_value,
                    cut_violation=violation,
                    cut_added=cut_added,
                    cut_kind=(selected_cut.kind if cut_added else None),
                    certified_lower_bound=lower_bound,
                    master_seconds=master_seconds,
                    recourse_seconds=recourse_seconds,
                    pareto_seconds=pareto_seconds,
                    elapsed_seconds=perf_counter() - started,
                )
            )
            if status is DddPartialPassengerRootStatus.INTERNAL_CERTIFICATE_ERROR:
                break
            if not cut_added and model.Status == GRB.OPTIMAL:
                projected_objective = master_objective
                projected_certified = True
                lower_bound = max(lower_bound, master_objective)
                status = DddPartialPassengerRootStatus.PROJECTED_LP_OPTIMAL
                break
            model.update()
        else:
            status = DddPartialPassengerRootStatus.ITERATION_LIMIT_WITH_CERTIFIED_BOUND

        self._publish(
            progress_hook,
            "complete",
            len(iterations),
            len(passenger.cut_constraint_by_id),
            lower_bound,
            started,
        )
        return DddPartialPassengerRootResult(
            status=status,
            problem_fingerprint=prepared.problem.fingerprint,
            passenger_domain_fingerprint=full_domain.fingerprint,
            partition=partial_domain.partition,
            certified_lower_bound=lower_bound,
            projected_lp_objective=projected_objective,
            projected_lp_certified=projected_certified,
            cut_count=len(passenger.cut_constraint_by_id),
            iterations=tuple(iterations),
            movement_variable_count=movement.movement_variable_count,
            core_passenger_variable_count=len(partial_domain.core_domain.variables),
            residual_passenger_variable_count=len(
                partial_domain.residual_domain.variables
            ),
            movement_constraint_count=movement.movement_constraint_count,
            core_passenger_constraint_count=(
                passenger.passenger_core.constraint_count
            ),
            resource_row_count=movement.resource_row_count,
            master_constraint_count=int(model.NumConstrs),
            passenger_domain_build_seconds=domain_seconds,
            master_build_seconds=build_seconds,
            master_solve_seconds=master_seconds_total,
            recourse_solve_seconds=recourse_seconds_total,
            pareto_solve_seconds=pareto_seconds_total,
            total_seconds=perf_counter() - started,
            detail=detail,
        )

    def _publish(
        self,
        hook: DddPartialPassengerRootProgressHook | None,
        phase: str,
        iteration: int,
        cut_count: int,
        lower_bound: float,
        started: float,
    ) -> None:
        if hook is None:
            return
        elapsed = perf_counter() - started
        hook(
            DddPartialPassengerRootProgress(
                phase=phase,
                iteration=iteration,
                cut_count=cut_count,
                certified_lower_bound=lower_bound,
                elapsed_seconds=elapsed,
                remaining_seconds=max(0.0, self.config.time_limit_seconds - elapsed),
            )
        )


def _finite(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None
